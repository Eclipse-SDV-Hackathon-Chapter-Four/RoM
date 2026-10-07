// Made with Claude (Claude Code, Anthropic)
//! RoM DFM bridge: guardian fault events -> fault-lib Reporter -> dfm_bin, and a query CLI.
//!
//!   rom-dfm report               uProtocol up://<UP_AUTHORITY>/1002/1/8003 -> DFM (default)
//!   rom-dfm replay <events.jsonl> same events from a file (fixtures, OpenSOVD integration tests)
//!   rom-dfm query [--stable]     DFM fault records as JSON (--stable: without timestamps)
//!
//! Diagnostic fault injection (fault-injector target "dfm", HTTP on DFM_FAULT_API_PORT, unset / 0 = off, no auth):
//!   write_delay {ms}       every DFM write waits ms first             -> delayed DFM write
//!   drop_write {codes}     records of these codes are never written    -> partial OpenSOVD visibility (empty = all)
//! The guardian and the evidence collector still see the fault events: only the diagnostics are late or missing.

use std::{collections::HashMap, env, fs, io::Read, str::FromStr, sync::{Arc, Mutex, mpsc}, thread, time::Duration};

use async_trait::async_trait;

use common::{
    fault::{FaultId, LifecyclePhase, LifecycleStage},
    ids::SourceId,
    types::{MetadataVec, to_static_short_string},
};
use dfm_lib::{DfmQueryApi, Iceoryx2DfmQuery};
use iceoryx2_bb_container::vector::Vector;
use fault_lib::{
    FaultApi,
    catalog::FaultCatalogBuilder,
    reporter::{Reporter, ReporterApi, ReporterConfig},
};
use serde_json::{Value, json};
use up_rust::{UListener, UMessage, UTransport, UUri};
use up_transport_zenoh::{UPTransportZenoh, zenoh_config};

/// Guardian fault topic (libs/rom-uprotocol: UP_GUARDIAN_UE_ID 0x1002, UP_RESOURCE_GUARDIAN_FAULT 0x8003)
const FAULT_TOPIC: &str = "1002/1/8003";
/// Environment data keys, as rom_uprotocol.contract.FaultEvent.environment_data() (8 = fault-lib MetadataVec capacity)
const ENV_KEYS: [&str; 8] = ["cell", "temp_c", "cells", "reason", "seq", "msg_id", "ts_ms", "run_id"];

fn now_ms() -> u128 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_millis())
}

fn log(event: &str, fields: Value) {
    let mut rec = json!({"ts_ms": now_ms(), "component": "dfm", "event": event});
    if let (Some(r), Some(f)) = (rec.as_object_mut(), fields.as_object()) {
        r.extend(f.clone());
    }
    println!("{rec}");
}

fn var(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.to_string())
}

struct Event {
    code: String,
    stage: LifecycleStage,
    env: Vec<(&'static str, String)>,
    run_id: Value,
    ts_ms: Option<u64>,
}

/// Guardian fault event (rom_uprotocol.contract.build_fault_event); env data skips null / empty, all strings.
fn parse_event(payload: &[u8]) -> Result<Event, String> {
    let v: Value = serde_json::from_slice(payload).map_err(|e| format!("invalid_json: {e}"))?;
    let code = v["code"].as_str().ok_or("missing_code")?.to_string();
    let stage = match v["stage"].as_str() {
        Some("FAILED") => LifecycleStage::Failed,
        Some("PASSED") => LifecycleStage::Passed,
        other => return Err(format!("unknown_stage: {other:?}")),
    };
    let env = ENV_KEYS
        .iter()
        .filter_map(|&k| match &v[k] {
            Value::Null => None,
            Value::String(s) if s.is_empty() => None,
            Value::String(s) => Some((k, s.clone())),
            other => Some((k, other.to_string())),
        })
        .collect();
    Ok(Event { code, stage, env, run_id: v["run_id"].clone(), ts_ms: v["ts_ms"].as_u64() })
}

struct Bridge {
    _api: FaultApi, // keeps the IPC sink alive
    path: String,
    reporters: HashMap<String, Reporter>,
    faults: Faults,
}

#[derive(Clone)]
struct DfmFault {
    id: u64,
    kind: String,
    params: Value,
}

impl DfmFault {
    fn json(&self) -> Value {
        json!({"id": self.id, "type": self.kind, "params": self.params})
    }
}

#[derive(Default)]
struct DfmFaults {
    next: u64,
    active: Vec<DfmFault>,
}

type Faults = Arc<Mutex<DfmFaults>>;

impl DfmFaults {
    /// (write delay in ms, drop this code?) for one record.
    fn decide(&self, code: &str) -> (u64, bool) {
        let delay = self.active.iter().filter(|f| f.kind == "write_delay").filter_map(|f| f.params["ms"].as_u64()).max();
        let drop = self.active.iter().any(|f| {
            f.kind == "drop_write"
                && f.params["codes"].as_array().is_none_or(|c| c.is_empty() || c.iter().any(|v| v.as_str() == Some(code)))
        });
        (delay.unwrap_or(0), drop)
    }

    /// Same request / response shape as the simulator and vss-uprotocol-client fault APIs (rom_common.control).
    fn api(&mut self, method: &str, url: &str, body: &str) -> (u16, Value) {
        let req: Value = serde_json::from_str(body).unwrap_or(Value::Null);
        match (method, url) {
            ("GET", "/health") => (200, json!({"ok": true})),
            ("GET", "/faults") => (200, Value::Array(self.active.iter().map(DfmFault::json).collect())),
            ("POST", "/run") => {
                for f in self.active.drain(..) {
                    log("fault_cleared", json!({"reason": "new_run", "fault": f.json()}));
                }
                log("run_started", json!({"run_id": req["run_id"]}));
                (200, json!({"run_id": req["run_id"]}))
            }
            ("POST", "/faults") => {
                let kind = req["type"].as_str().unwrap_or_default();
                let params = if req["params"].is_object() { req["params"].clone() } else { json!({}) };
                if kind != "write_delay" && kind != "drop_write" {
                    return (422, json!({"error": format!("unknown fault type {kind:?}, use write_delay or drop_write")}));
                }
                if kind == "write_delay" && params["ms"].as_u64().is_none_or(|ms| ms == 0) {
                    return (422, json!({"error": "params.ms must be a positive integer"}));
                }
                self.next += 1;
                let fault = DfmFault { id: self.next, kind: kind.to_string(), params };
                log("fault_injected", fault.json());
                self.active.push(fault.clone());
                (201, fault.json())
            }
            ("DELETE", "/faults") => {
                let ids: Vec<u64> = self.active.drain(..).map(|f| f.id).collect();
                (200, json!({"cleared": ids}))
            }
            ("DELETE", u) if u.starts_with("/faults/") => {
                let id = u["/faults/".len()..].parse::<u64>().ok();
                match self.active.iter().position(|f| Some(f.id) == id) {
                    Some(i) => {
                        let f = self.active.remove(i);
                        log("fault_cleared", json!({"reason": "api", "fault": f.json()}));
                        (200, json!({"cleared": f.id}))
                    }
                    None => (404, json!({"error": "no such fault"})),
                }
            }
            _ => (404, json!({"error": "not found"})),
        }
    }
}

fn serve_fault_api(port: u16, faults: Faults) {
    let server = tiny_http::Server::http(("0.0.0.0", port)).expect("DFM fault API port");
    log("fault_api_started", json!({"port": port}));
    for mut request in server.incoming_requests() {
        let mut body = String::new();
        let _ = request.as_reader().read_to_string(&mut body);
        let (status, out) = faults.lock().expect("faults").api(request.method().as_str(), request.url(), &body);
        let header = tiny_http::Header::from_bytes("Content-Type", "application/json").expect("header");
        let _ = request.respond(tiny_http::Response::from_string(out.to_string()).with_status_code(status).with_header(header));
    }
}

impl Bridge {
    /// Retries until dfm_bin is up: FaultApi checks the catalog hash with the running DFM.
    fn connect(catalog_file: &str, faults: Faults) -> Bridge {
        let api = loop {
            let catalog = FaultCatalogBuilder::new()
                .json_file(catalog_file.into())
                .unwrap_or_else(|e| panic!("bad catalog {catalog_file}: {e:?}"))
                .build();
            match FaultApi::try_new(catalog) {
                Ok(api) => break api,
                Err(e) => log("waiting_for_dfm", json!({"error": e.to_string()})),
            }
            thread::sleep(Duration::from_secs(1));
        };
        let config = ReporterConfig {
            source: SourceId {
                entity: to_static_short_string("guardian").expect("short"),
                ecu: None,
                domain: Some(to_static_short_string("battery").expect("short")),
                sw_component: Some(to_static_short_string("battery_thermal_guardian").expect("short")),
                instance: None,
            },
            lifecycle_phase: LifecyclePhase::Running,
            default_env_data: MetadataVec::new(),
        };
        let catalog = FaultApi::get_fault_catalog();
        let reporters = catalog
            .descriptors()
            .filter_map(|d| match &d.id {
                FaultId::Text(code) => Some((code.to_string(), Reporter::new(&d.id, config.clone()).expect("fault in catalog"))),
                _ => None,
            })
            .collect();
        let path = catalog.id().to_string();
        log("ready", json!({"path": path, "faults": catalog.len()}));
        Bridge { _api: api, path, reporters, faults }
    }

    /// fault_msg_id: the uProtocol id of the fault-event message (the guardian logs it as `published.msg_id`).
    fn handle(&mut self, payload: &[u8], fault_msg_id: Option<&str>) {
        let Event { code, stage, env, run_id, ts_ms } = match parse_event(payload) {
            Ok(e) => e,
            Err(reason) => return log("rejected", json!({"reason": reason, "fault_msg_id": fault_msg_id})),
        };
        let (delay_ms, dropped) = self.faults.lock().expect("faults").decide(&code);
        if dropped {
            return log("write_dropped", json!({"code": code, "run_id": run_id, "fault_msg_id": fault_msg_id}));
        }
        if delay_ms > 0 {
            log("write_delayed", json!({"code": code, "run_id": run_id, "ms": delay_ms, "fault_msg_id": fault_msg_id}));
            thread::sleep(Duration::from_millis(delay_ms));
        }
        let Some(reporter) = self.reporters.get_mut(&code) else {
            return log("rejected", json!({"reason": "unknown_code", "code": code, "fault_msg_id": fault_msg_id}));
        };
        let mut record = reporter.create_record(stage);
        for (k, v) in &env {
            match (to_static_short_string(k), to_static_short_string(v)) {
                (Ok(k), Ok(v)) if record.env_data.push((k, v)).is_ok() => {}
                _ => log("env_dropped", json!({"code": code, "key": k, "value": v})),  // > 64 bytes
            }
        }
        let stage = format!("{stage:?}").to_uppercase();
        match reporter.publish(&self.path, record) {
            Ok(()) => {
                // write latency for the evidence collector: guardian edge (ts_ms) -> handed to the DFM
                let latency_ms = ts_ms.map(|t| now_ms() as i128 - t as i128);
                log("fault_record", json!({"code": code, "stage": stage, "run_id": run_id, "fault_msg_id": fault_msg_id,
                                           "latency_ms": latency_ms, "env": env_json(&env)}))
            }
            Err(e) => log("publish_failed", json!({"code": code, "stage": stage, "run_id": run_id,
                                                   "fault_msg_id": fault_msg_id, "error": format!("{e:?}")})),
        }
        // ponytail: the DFM polls every 10 ms and its iceoryx2 subscriber buffer is tiny, so a burst
        // (replay, or Passed+Failed in one tick) loses records; pace them. Raise the buffer in fault-lib to drop this.
        thread::sleep(Duration::from_millis(50));
    }
}

fn env_json(env: &[(&str, String)]) -> Value {
    env.iter().map(|(k, v)| ((*k).to_string(), Value::String(v.clone()))).collect::<serde_json::Map<_, _>>().into()
}

/// Hands every payload + its uProtocol message id to the thread that owns the Bridge (fault-lib is sync, Zenoh
/// calls back on its own threads).
struct Forward(mpsc::Sender<(Vec<u8>, Option<String>)>);

#[async_trait]
impl UListener for Forward {
    async fn on_receive(&self, msg: UMessage) {
        let id = msg.attributes.as_ref().and_then(|a| a.id.as_ref()).map(|id| id.to_hyphenated_string());
        if let Some(payload) = msg.payload {
            let _ = self.0.send((payload.to_vec(), id));
        }
    }
}

/// Zenoh session from the same env as libs/rom-uprotocol: ZENOH_MODE, ZENOH_CONNECT, ZENOH_LISTEN (comma lists).
fn zenoh_cfg() -> zenoh_config::Config {
    let mut cfg = zenoh_config::Config::default();
    let list = |name: &str| -> Vec<String> {
        var(name, "").split(',').map(str::trim).filter(|s| !s.is_empty()).map(String::from).collect()
    };
    cfg.insert_json5("mode", &json!(var("ZENOH_MODE", "peer")).to_string()).expect("ZENOH_MODE");
    for (key, name) in [("connect/endpoints", "ZENOH_CONNECT"), ("listen/endpoints", "ZENOH_LISTEN")] {
        let endpoints = list(name);
        if !endpoints.is_empty() {
            cfg.insert_json5(key, &json!(endpoints).to_string()).expect(name);
        }
    }
    cfg
}

fn report(mut bridge: Bridge) {
    let authority = var("UP_AUTHORITY", "rom-vehicle");
    let topic = UUri::from_str(&format!("//{authority}/{FAULT_TOPIC}")).expect("fault topic");
    let (tx, rx) = mpsc::channel();
    let rt = tokio::runtime::Runtime::new().expect("tokio");
    let _transport = rt.block_on(async {
        let transport = UPTransportZenoh::builder(authority.as_str())
            .expect("UP_AUTHORITY")
            .with_config(zenoh_cfg())
            .build()
            .await
            .expect("zenoh session");
        transport.register_listener(&topic, None, Arc::new(Forward(tx))).await.expect("register listener");
        transport
    });
    log("subscribed", json!({"topic": topic.to_uri(true)}));
    for (payload, id) in rx {
        bridge.handle(&payload, id.as_deref());
    }
}

fn query(path: &str, stable: bool) {
    let dfm = Iceoryx2DfmQuery::new().unwrap_or_else(|e| panic!("dfm/query: {e}"));
    let mut faults = dfm.get_all_faults(path).unwrap_or_else(|e| panic!("get_all_faults({path}): {e}"));
    faults.sort_by(|a, b| a.code.cmp(&b.code));
    let out: Vec<Value> = faults
        .iter()
        .map(|f| {
            let mut env = dfm.get_fault(path, &f.code).map(|(_, env)| env).unwrap_or_default();
            let mut rec = json!({"code": f.code, "fault_name": f.fault_name, "severity": f.severity,
                "status": f.status, "occurrence_counter": f.occurrence_counter});
            if stable {
                env.remove("ts_ms");
            } else {
                rec["first_occurrence"] = json!(f.first_occurrence);
                rec["last_occurrence"] = json!(f.last_occurrence);
            }
            rec["env"] = json!(env.into_iter().collect::<std::collections::BTreeMap<_, _>>());
            rec
        })
        .collect();
    println!("{}", serde_json::to_string_pretty(&out).expect("json"));
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let catalog = var("CATALOG", "/etc/rom/catalog/battery_guardian.json");
    match args.first().map(String::as_str) {
        None | Some("report") => {
            let faults = Faults::default();
            let port: u16 = var("DFM_FAULT_API_PORT", "0").parse().expect("DFM_FAULT_API_PORT");
            if port > 0 {
                let f = faults.clone();
                thread::spawn(move || serve_fault_api(port, f));
            }
            report(Bridge::connect(&catalog, faults))
        }
        Some("replay") => {
            let file = args.get(1).expect("usage: rom-dfm replay <events.jsonl>");
            let mut bridge = Bridge::connect(&catalog, Faults::default());
            for line in fs::read_to_string(file).expect("read events").lines().filter(|l| !l.is_empty()) {
                bridge.handle(line.as_bytes(), None);
            }
            // ponytail: fixed wait for the IPC worker to flush, poll the DFM if replays grow large
            thread::sleep(Duration::from_secs(1));
        }
        Some("query") => query(&var("DFM_PATH", "battery_guardian"), args.iter().any(|a| a == "--stable")),
        Some(other) => panic!("unknown command {other}: report | replay <file> | query [--stable]"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_guardian_event_and_rejects_bad_stage() {
        // services/dfm/README.md example
        let raw = br#"{"code":"battery_guardian.cell3.signal_stuck","stage":"FAILED","ts_ms":1791367830419,"cell":3,
            "temp_c":26.75,"cells":"26.75,25.59,23.39,23.42","reason":"stuck signal","seq":31,
            "msg_id":"01a115d7-3974-7762-9130-3d31e9e56013","run_id":"sensor-stuck-cell3-01"}"#;
        let e = parse_event(raw).expect("valid event");
        assert_eq!((e.code.as_str(), e.stage), ("battery_guardian.cell3.signal_stuck", LifecycleStage::Failed));
        assert_eq!(e.env, vec![("cell", "3".into()), ("temp_c", "26.75".into()), ("cells", "26.75,25.59,23.39,23.42".into()),
                               ("reason", "stuck signal".into()), ("seq", "31".into()),
                               ("msg_id", "01a115d7-3974-7762-9130-3d31e9e56013".into()), ("ts_ms", "1791367830419".into()),
                               ("run_id", "sensor-stuck-cell3-01".into())]);
        let passed = parse_event(br#"{"code":"battery_guardian.signal_stale","stage":"PASSED","ts_ms":1,"cell":null,"cells":""}"#)
            .expect("valid event");
        assert_eq!((passed.stage, passed.env), (LifecycleStage::Passed, vec![("ts_ms", "1".into())]));
        assert!(parse_event(br#"{"code":"X","stage":"Failed"}"#).is_err());
        assert!(parse_event(b"nope").is_err());
    }

    #[test]
    fn fault_api_delays_and_drops_writes_per_code() {
        let mut f = DfmFaults::default();
        assert_eq!(f.decide("a"), (0, false));
        assert_eq!(f.api("POST", "/faults", r#"{"type":"write_delay","params":{"ms":3000}}"#).0, 201);
        assert_eq!(f.api("POST", "/faults", r#"{"type":"drop_write","params":{"codes":["b"]}}"#).0, 201);
        assert_eq!((f.decide("a"), f.decide("b")), ((3000, false), (3000, true)));
        assert_eq!(f.api("POST", "/faults", r#"{"type":"nope"}"#).0, 422);
        assert_eq!(f.api("DELETE", "/faults/1", "").0, 200);
        assert_eq!(f.api("POST", "/run", r#"{"run_id":"r"}"#).0, 200);
        assert_eq!(f.decide("b"), (0, false));
    }
}
