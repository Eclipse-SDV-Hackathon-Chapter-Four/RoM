// Made with Claude (Claude Code, Anthropic)
//! RoM DFM bridge: guardian fault events -> fault-lib Reporter -> dfm_bin, and a query CLI.
//!
//!   rom-dfm report               uProtocol up://<UP_AUTHORITY>/1002/1/8003 -> DFM (default)
//!   rom-dfm replay <events.jsonl> same events from a file (fixtures, OpenSOVD integration tests)
//!   rom-dfm query [--stable]     DFM fault records as JSON (--stable: without timestamps)

use std::{collections::HashMap, env, fs, str::FromStr, sync::{Arc, mpsc}, thread, time::Duration};

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
}

impl Bridge {
    /// Retries until dfm_bin is up: FaultApi checks the catalog hash with the running DFM.
    fn connect(catalog_file: &str) -> Bridge {
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
        Bridge { _api: api, path, reporters }
    }

    fn handle(&mut self, payload: &[u8]) {
        let Event { code, stage, env, run_id, ts_ms } = match parse_event(payload) {
            Ok(e) => e,
            Err(reason) => return log("rejected", json!({"reason": reason})),
        };
        let Some(reporter) = self.reporters.get_mut(&code) else {
            return log("rejected", json!({"reason": "unknown_code", "code": code}));
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
                log("fault_record", json!({"code": code, "stage": stage, "run_id": run_id,
                                           "latency_ms": latency_ms, "env": env_json(&env)}))
            }
            Err(e) => log("publish_failed", json!({"code": code, "stage": stage, "run_id": run_id, "error": format!("{e:?}")})),
        }
        // ponytail: the DFM polls every 10 ms and its iceoryx2 subscriber buffer is tiny, so a burst
        // (replay, or Passed+Failed in one tick) loses records; pace them. Raise the buffer in fault-lib to drop this.
        thread::sleep(Duration::from_millis(50));
    }
}

fn env_json(env: &[(&str, String)]) -> Value {
    env.iter().map(|(k, v)| ((*k).to_string(), Value::String(v.clone()))).collect::<serde_json::Map<_, _>>().into()
}

/// Hands every payload to the thread that owns the Bridge (fault-lib is sync, Zenoh calls back on its own threads).
struct Forward(mpsc::Sender<Vec<u8>>);

#[async_trait]
impl UListener for Forward {
    async fn on_receive(&self, msg: UMessage) {
        if let Some(payload) = msg.payload {
            let _ = self.0.send(payload.to_vec());
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
    for payload in rx {
        bridge.handle(&payload);
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
        None | Some("report") => report(Bridge::connect(&catalog)),
        Some("replay") => {
            let file = args.get(1).expect("usage: rom-dfm replay <events.jsonl>");
            let mut bridge = Bridge::connect(&catalog);
            for line in fs::read_to_string(file).expect("read events").lines().filter(|l| !l.is_empty()) {
                bridge.handle(line.as_bytes());
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
}
