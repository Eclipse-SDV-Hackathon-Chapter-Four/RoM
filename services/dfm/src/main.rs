// Made with Claude (Claude Code, Anthropic)
//! RoM DFM bridge: guardian fault events -> fault-lib Reporter -> dfm_bin, and a query CLI.
//!
//!   rom-dfm report               MQTT rom/guardian/fault -> DFM (default)
//!   rom-dfm replay <events.jsonl> same events from a file (fixtures, OpenSOVD integration tests)
//!   rom-dfm query [--stable]     DFM fault records as JSON (--stable: without timestamps)

use std::{collections::HashMap, env, fs, thread, time::Duration};

use common::{
    fault::{LifecyclePhase, LifecycleStage},
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
use rumqttc::{Client, Event, MqttOptions, Packet, QoS};
use serde_json::{Value, json};

const TOPIC: &str = "rom/guardian/fault";
const ENV_KEYS: [&str; 5] = ["temp_c", "reason", "seq", "msg_id", "ts_ms"];

fn log(event: &str, fields: Value) {
    let ts_ms = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_millis());
    let mut rec = json!({"ts_ms": ts_ms, "component": "dfm", "event": event});
    if let (Some(r), Some(f)) = (rec.as_object_mut(), fields.as_object()) {
        r.extend(f.clone());
    }
    println!("{rec}");
}

fn var(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.to_string())
}

/// Guardian fault event (libs/rom-common contracts.build_fault_event) -> (fault name, stage, env data).
fn parse_event(payload: &[u8]) -> Result<(String, LifecycleStage, Vec<(&'static str, String)>), String> {
    let v: Value = serde_json::from_slice(payload).map_err(|e| format!("invalid_json: {e}"))?;
    let fault = v["fault"].as_str().ok_or("missing_fault")?.to_string();
    let stage = match v["stage"].as_str() {
        Some("Failed") => LifecycleStage::Failed,
        Some("Passed") => LifecycleStage::Passed,
        other => return Err(format!("unknown_stage: {other:?}")),
    };
    let env = ENV_KEYS
        .iter()
        .filter_map(|&k| match &v[k] {
            Value::Null => None,
            Value::String(s) => Some((k, s.clone())),
            other => Some((k, other.to_string())),
        })
        .collect();
    Ok((fault, stage, env))
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
            .map(|d| (d.name.to_string(), Reporter::new(&d.id, config.clone()).expect("fault in catalog")))
            .collect();
        let path = catalog.id().to_string();
        log("ready", json!({"path": path, "faults": catalog.len()}));
        Bridge { _api: api, path, reporters }
    }

    fn handle(&mut self, payload: &[u8]) {
        let (fault, stage, env) = match parse_event(payload) {
            Ok(e) => e,
            Err(reason) => return log("rejected", json!({"reason": reason})),
        };
        let Some(reporter) = self.reporters.get_mut(&fault) else {
            return log("rejected", json!({"reason": "unknown_fault", "fault": fault}));
        };
        let mut record = reporter.create_record(stage);
        for (k, v) in &env {
            if let (Ok(k), Ok(v)) = (to_static_short_string(k), to_static_short_string(v)) {
                let _ = record.env_data.push((k, v));
            }
        }
        match reporter.publish(&self.path, record) {
            Ok(()) => log("fault_record", json!({"fault": fault, "stage": format!("{stage:?}"), "env": env_json(&env)})),
            Err(e) => log("publish_failed", json!({"fault": fault, "error": format!("{e:?}")})),
        }
        // ponytail: the DFM polls every 10 ms and its iceoryx2 subscriber buffer is tiny, so a burst
        // (replay, or Passed+Failed in one tick) loses records; pace them. Raise the buffer in fault-lib to drop this.
        thread::sleep(Duration::from_millis(50));
    }
}

fn env_json(env: &[(&str, String)]) -> Value {
    env.iter().map(|(k, v)| ((*k).to_string(), Value::String(v.clone()))).collect::<serde_json::Map<_, _>>().into()
}

fn report(mut bridge: Bridge) {
    let port = var("MQTT_PORT", "1883").parse().expect("MQTT_PORT");
    let mut opts = MqttOptions::new(format!("rom-dfm-{}", std::process::id()), var("MQTT_HOST", "localhost"), port);
    opts.set_keep_alive(Duration::from_secs(30));
    let (client, mut connection) = Client::new(opts, 64);
    for event in connection.iter() {
        match event {
            // clean session: subscribe again after every (re)connect
            Ok(Event::Incoming(Packet::ConnAck(_))) => {
                let _ = client.try_subscribe(TOPIC, QoS::AtLeastOnce);
                log("subscribed", json!({"topic": TOPIC}));
            }
            Ok(Event::Incoming(Packet::Publish(p))) => bridge.handle(&p.payload),
            Ok(_) => {}
            Err(e) => {
                log("mqtt_error", json!({"error": e.to_string()}));
                thread::sleep(Duration::from_secs(1));
            }
        }
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
        let raw = br#"{"fault":"BatteryTempSignalStale","stage":"Failed","ts_ms":18000,"temp_c":30,"reason":"stale signal","seq":18,"msg_id":null}"#;
        let (fault, stage, env) = parse_event(raw).expect("valid event");
        assert_eq!((fault.as_str(), stage), ("BatteryTempSignalStale", LifecycleStage::Failed));
        assert_eq!(env, vec![("temp_c", "30".into()), ("reason", "stale signal".into()), ("seq", "18".into()),
                             ("ts_ms", "18000".into())]);
        assert!(parse_event(br#"{"fault":"X","stage":"Maybe"}"#).is_err());
        assert!(parse_event(b"nope").is_err());
    }
}
