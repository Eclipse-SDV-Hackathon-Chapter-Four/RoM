// Made with Claude (Claude Code, Anthropic)
//! SOVD `faults` resource (ISO 17978-3) for one entity, backed by the fault-lib DFM query API.
//!
//! opensovd-core reserves `EntityCapabilities.faults` but has no route for it yet
//! (eclipse-opensovd/opensovd-core#156), so this module adds one, mounted by `main.rs` at
//! `{base}/v1/apps/{app}/faults`:
//!
//!   GET    .../faults            {"items": [Fault]}   filters: ?status[testFailed]=1 (repeat = OR), ?severity=N
//!   GET    .../faults/{code}     {"item": Fault, "environment_data": {...}}
//!   DELETE .../faults            clear all faults of the entity   -> 204
//!   DELETE .../faults/{code}     clear one fault                  -> 204
//!
//! The Fault JSON follows the OpenSOVD Classic Diagnostic Adapter (`cda-sovd-interfaces`,
//! `components::ecu::faults::Fault`): `code`, `display_code`, `scope`, `fault_name`, `severity` and
//! `status` with the ISO 14229-1 DTC status bits plus `mask`; the DFM extras (occurrence/aging/healing
//! counters, first/last occurrence, symptom) are added when present.

use std::{
    sync::{Arc, Mutex},
    time::Duration,
};

use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
};
use dfm_lib::{
    DfmQueryApi, Iceoryx2DfmQuery,
    sovd_fault_manager::{Error as DfmError, SovdEnvData, SovdFault, SovdFaultStatus},
};
use iceoryx2::prelude::{Config, Node, ipc_threadsafe};
use opensovd_models::error::GenericError;
use serde_json::{Map, Value, json};

#[derive(Clone)]
struct Entity {
    dfm: Arc<dyn DfmQueryApi>,
    /// DFM entity path = fault catalog id (e.g. `battery_guardian`).
    path: String,
}

/// Router for one entity's `faults` collection; mount it with `ServerBuilder::service`.
pub fn router(dfm: Arc<dyn DfmQueryApi>, path: impl Into<String>) -> Router {
    Router::new()
        .route("/", get(list).delete(clear_all))
        .route("/{code}", get(detail).delete(clear_one))
        .with_state(Entity { dfm, path: path.into() })
}

async fn list(State(e): State<Entity>, Query(query): Query<Vec<(String, String)>>) -> Response {
    let filter = match Filter::parse(&query) {
        Ok(f) => f,
        Err(msg) => return error(StatusCode::BAD_REQUEST, "invalid-query", msg),
    };
    let path = e.path.clone();
    match blocking(e.dfm, move |dfm| dfm.get_all_faults(&path)).await {
        Ok(mut faults) => {
            faults.sort_by(|a, b| a.code.cmp(&b.code)); // the DFM returns hash-map order; keep evidence diffs stable
            let items: Vec<Value> = faults.iter().filter(|f| filter.matches(f)).map(fault_json).collect();
            Json(json!({ "items": items })).into_response()
        }
        Err(err) => dfm_error(&err, &e.path, None),
    }
}

async fn detail(State(e): State<Entity>, Path(code): Path<String>) -> Response {
    let (path, c) = (e.path.clone(), code.clone());
    match blocking(e.dfm, move |dfm| dfm.get_fault(&path, &c)).await {
        Ok((fault, env)) => {
            Json(json!({ "item": fault_json(&fault), "environment_data": env_json(&env) })).into_response()
        }
        Err(err) => dfm_error(&err, &e.path, Some(&code)),
    }
}

async fn clear_all(State(e): State<Entity>) -> Response {
    let path = e.path.clone();
    match blocking(e.dfm, move |dfm| dfm.delete_all_faults(&path)).await {
        Ok(()) => StatusCode::NO_CONTENT.into_response(),
        Err(err) => dfm_error(&err, &e.path, None),
    }
}

async fn clear_one(State(e): State<Entity>, Path(code): Path<String>) -> Response {
    let (path, c) = (e.path.clone(), code.clone());
    match blocking(e.dfm, move |dfm| dfm.delete_fault(&path, &c)).await {
        Ok(()) => StatusCode::NO_CONTENT.into_response(),
        Err(err) => dfm_error(&err, &e.path, Some(&code)),
    }
}

/// DFM queries block (iceoryx2 request/response with a timeout), so they run off the async runtime.
async fn blocking<T: Send + 'static>(
    dfm: Arc<dyn DfmQueryApi>,
    f: impl FnOnce(&dyn DfmQueryApi) -> Result<T, DfmError> + Send + 'static,
) -> Result<T, DfmError> {
    tokio::task::spawn_blocking(move || f(dfm.as_ref()))
        .await
        .unwrap_or_else(|e| Err(DfmError::Storage(format!("query task failed: {e}"))))
}

fn error(status: StatusCode, vendor_code: &str, message: impl Into<String>) -> Response {
    (status, Json(GenericError::with_vendor_code(vendor_code, message))).into_response()
}

fn dfm_error(err: &DfmError, path: &str, code: Option<&str>) -> Response {
    let resource = code.map_or_else(|| path.to_owned(), |c| format!("{path}/{c}"));
    match err {
        DfmError::NotFound => error(StatusCode::NOT_FOUND, "resource-not-found", format!("Fault not found: {resource}")),
        DfmError::BadArgument => error(StatusCode::BAD_REQUEST, "bad-argument", format!("Invalid fault request: {resource}")),
        // Storage covers "DFM not running / query timeout" as well as KVS errors inside the DFM.
        DfmError::Storage(msg) => {
            tracing::warn!(%resource, error = %msg, "DFM query failed");
            error(StatusCode::SERVICE_UNAVAILABLE, "dfm-unavailable", format!("DFM query failed: {msg}"))
        }
        other => error(StatusCode::INTERNAL_SERVER_ERROR, "dfm-error", other.to_string()),
    }
}

// --- JSON mapping -----------------------------------------------------------------------------

const STATUS_BITS: [(&str, fn(&SovdFaultStatus) -> Option<bool>); 8] = [
    ("test_failed", |s| s.test_failed),
    ("test_failed_this_operation_cycle", |s| s.test_failed_this_operation_cycle),
    ("pending_dtc", |s| s.pending_dtc),
    ("confirmed_dtc", |s| s.confirmed_dtc),
    ("test_not_completed_since_last_clear", |s| s.test_not_completed_since_last_clear),
    ("test_failed_since_last_clear", |s| s.test_failed_since_last_clear),
    ("test_not_completed_this_operation_cycle", |s| s.test_not_completed_this_operation_cycle),
    ("warning_indicator_requested", |s| s.warning_indicator_requested),
];

fn status_json(f: &SovdFault) -> Value {
    let Some(s) = &f.typed_status else {
        // Older DFMs only fill the string map ({"testFailed": "1", ...}); pass it through.
        return json!(f.status);
    };
    let mut m = Map::new();
    for (name, bit) in STATUS_BITS {
        if let Some(v) = bit(s) {
            m.insert(name.into(), v.into());
        }
    }
    let mask = s.mask.clone().unwrap_or_else(|| format!("0x{:02X}", s.compute_mask()));
    m.insert("mask".into(), mask.into());
    Value::Object(m)
}

fn fault_json(f: &SovdFault) -> Value {
    let mut m = Map::new();
    m.insert("code".into(), f.code.clone().into());
    m.insert("display_code".into(), f.display_code.clone().into());
    m.insert("scope".into(), f.scope.clone().into());
    m.insert("fault_name".into(), f.fault_name.clone().into());
    m.insert("fault_translation_id".into(), f.fault_translation_id.clone().into());
    m.insert("severity".into(), f.severity.into());
    m.insert("status".into(), status_json(f));
    let optional: [(&str, Option<Value>); 7] = [
        ("symptom", f.symptom.clone().map(Value::from)),
        ("symptom_translation_id", f.symptom_translation_id.clone().map(Value::from)),
        ("occurrence_counter", f.occurrence_counter.map(Value::from)),
        ("aging_counter", f.aging_counter.map(Value::from)),
        ("healing_counter", f.healing_counter.map(Value::from)),
        ("first_occurrence", f.first_occurrence.clone().map(Value::from)),
        ("last_occurrence", f.last_occurrence.clone().map(Value::from)),
    ];
    for (k, v) in optional {
        if let Some(v) = v {
            m.insert(k.into(), v);
        }
    }
    Value::Object(m)
}

/// The DFM stores environment data as strings; numbers (temp_c, seq, ts_ms) go out as JSON numbers.
fn env_json(env: &SovdEnvData) -> Value {
    let mut keys: Vec<&String> = env.keys().collect();
    keys.sort(); // stable output for evidence diffs
    let mut m = Map::new();
    for k in keys {
        let v = &env[k];
        let value = match (v.parse::<i64>(), v.parse::<f64>()) {
            (Ok(i), _) => Value::from(i),
            (_, Ok(x)) if x.is_finite() => Value::from(x),
            _ => Value::from(v.clone()),
        };
        m.insert(k.clone(), value);
    }
    Value::Object(m)
}

// --- Query filter ------------------------------------------------------------------------------

/// `?status[<bit>]=0|1|true|false` (repeated = OR, bit names in camelCase or snake_case, or `mask`)
/// and `?severity=N`, as in the Classic Diagnostic Adapter.
struct Filter {
    severity: Option<u32>,
    status: Vec<(String, String)>,
}

fn norm(key: &str) -> String {
    key.replace('_', "").to_ascii_lowercase()
}

impl Filter {
    fn parse(query: &[(String, String)]) -> Result<Self, String> {
        let mut filter = Filter { severity: None, status: Vec::new() };
        for (k, v) in query {
            if k == "severity" {
                filter.severity = Some(v.parse().map_err(|_| format!("severity must be a number, got {v:?}"))?);
            } else if let Some(bit) = k.strip_prefix("status[").and_then(|r| r.strip_suffix(']')) {
                let bit = norm(bit);
                if bit != "mask" && !STATUS_BITS.iter().any(|(name, _)| norm(name) == bit) {
                    return Err(format!("unknown status key {bit:?}"));
                }
                filter.status.push((bit, v.to_ascii_lowercase()));
            }
            // Other parameters (include-schema, scope, ...) are accepted and ignored.
        }
        Ok(filter)
    }

    fn matches(&self, f: &SovdFault) -> bool {
        if self.severity.is_some_and(|s| s != f.severity) {
            return false;
        }
        if self.status.is_empty() {
            return true;
        }
        let Some(s) = &f.typed_status else { return false };
        self.status.iter().any(|(bit, want)| {
            if bit == "mask" {
                let mask = s.mask.clone().unwrap_or_else(|| format!("0x{:02X}", s.compute_mask()));
                return mask.eq_ignore_ascii_case(want);
            }
            let want = matches!(want.as_str(), "1" | "true");
            STATUS_BITS.iter().any(|(name, get)| norm(name) == *bit && get(s) == Some(want))
        })
    }
}

// --- Live DFM client ---------------------------------------------------------------------------

/// `DfmQueryApi` over the DFM's iceoryx2 `dfm/query` service. The client is created on first use and
/// recreated after a failed query, so the server starts before the DFM and survives DFM restarts.
/// A DFM that was killed leaves its iceoryx2 resources behind (`ServiceInCorruptedState` on the next
/// open), so before reconnecting the resources of dead nodes are removed.
pub struct IpcDfm {
    timeout: Duration,
    client: Mutex<Option<Iceoryx2DfmQuery>>,
}

impl IpcDfm {
    pub fn new(timeout: Duration) -> Self {
        Self { timeout, client: Mutex::new(None) }
    }

    fn call<T>(&self, f: impl FnOnce(&Iceoryx2DfmQuery) -> Result<T, DfmError>) -> Result<T, DfmError> {
        let mut guard = self.client.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        let client = match guard.take() {
            Some(c) => c,
            None => {
                let cleanup = Node::<ipc_threadsafe::Service>::cleanup_dead_nodes(Config::global_config());
                if cleanup.cleanups > 0 || cleanup.failed_cleanups > 0 {
                    tracing::info!(removed = cleanup.cleanups, failed = cleanup.failed_cleanups, "cleaned up dead iceoryx2 nodes");
                }
                Iceoryx2DfmQuery::with_timeout(self.timeout)?
            }
        };
        let result = f(&client);
        if !matches!(result, Err(DfmError::Storage(_))) {
            *guard = Some(client); // keep it; a transport error drops it and reconnects next time
        }
        result
    }
}

impl DfmQueryApi for IpcDfm {
    fn get_all_faults(&self, path: &str) -> Result<Vec<SovdFault>, DfmError> {
        self.call(|c| c.get_all_faults(path))
    }

    fn get_fault(&self, path: &str, fault_code: &str) -> Result<(SovdFault, SovdEnvData), DfmError> {
        self.call(|c| c.get_fault(path, fault_code))
    }

    fn delete_all_faults(&self, path: &str) -> Result<(), DfmError> {
        self.call(|c| c.delete_all_faults(path))
    }

    fn delete_fault(&self, path: &str, fault_code: &str) -> Result<(), DfmError> {
        self.call(|c| c.delete_fault(path, fault_code))
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use axum::body::Body;
    use http::Request;
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    use super::*;

    /// Stand-in for the DFM: two faults of `battery_guardian`, one active, one healed.
    struct StubDfm {
        storage_error: bool,
        deleted: Mutex<Vec<String>>,
    }

    fn fault(code: &str, name: &str, failed: bool) -> SovdFault {
        SovdFault {
            code: code.into(),
            display_code: code.into(),
            scope: "ecu".into(),
            fault_name: name.into(),
            fault_translation_id: format!("fault.{code}"),
            severity: 2,
            typed_status: Some(SovdFaultStatus {
                test_failed: Some(failed),
                test_failed_since_last_clear: Some(true),
                ..Default::default()
            }),
            occurrence_counter: Some(1),
            ..Default::default()
        }
    }

    impl DfmQueryApi for StubDfm {
        fn get_all_faults(&self, path: &str) -> Result<Vec<SovdFault>, DfmError> {
            if self.storage_error {
                return Err(DfmError::Storage("query timeout".into()));
            }
            if path != "battery_guardian" {
                return Err(DfmError::NotFound);
            }
            Ok(vec![
                fault("battery_guardian.over_temp_warning", "BatteryOverTempWarning", true),
                fault("battery_guardian.cell2.signal_stuck", "BatteryCell2TempStuck", false),
            ])
        }

        fn get_fault(&self, path: &str, code: &str) -> Result<(SovdFault, SovdEnvData), DfmError> {
            let f = self.get_all_faults(path)?.into_iter().find(|f| f.code == code).ok_or(DfmError::NotFound)?;
            let env = HashMap::from([
                ("temp_c".to_string(), "38.4".to_string()),
                ("cell".to_string(), "2".to_string()),
                ("cells".to_string(), "38.4,31.2,,30.9".to_string()),
                ("seq".to_string(), "4".to_string()),
                ("reason".to_string(), "getting hot".to_string()),
                ("msg_id".to_string(), "01a11579-8206-7984-8a95-5cb1f12f78e7".to_string()),
            ]);
            Ok((f, env))
        }

        fn delete_all_faults(&self, path: &str) -> Result<(), DfmError> {
            self.deleted.lock().unwrap().push(path.to_string());
            Ok(())
        }

        fn delete_fault(&self, path: &str, code: &str) -> Result<(), DfmError> {
            self.deleted.lock().unwrap().push(format!("{path}/{code}"));
            Ok(())
        }
    }

    fn stub(storage_error: bool) -> Arc<StubDfm> {
        Arc::new(StubDfm { storage_error, deleted: Mutex::new(Vec::new()) })
    }

    async fn call(dfm: Arc<StubDfm>, method: &str, uri: &str) -> (StatusCode, Value) {
        let resp = router(dfm, "battery_guardian")
            .oneshot(Request::builder().method(method).uri(uri).body(Body::empty()).unwrap())
            .await
            .unwrap();
        let status = resp.status();
        let bytes = resp.into_body().collect().await.unwrap().to_bytes();
        let body = if bytes.is_empty() { Value::Null } else { serde_json::from_slice(&bytes).unwrap() };
        (status, body)
    }

    #[tokio::test]
    async fn lists_faults_in_sovd_shape() {
        let (status, body) = call(stub(false), "GET", "/").await;
        assert_eq!(status, StatusCode::OK);
        let items = body["items"].as_array().unwrap();
        assert_eq!(items.len(), 2);
        assert_eq!(items[0]["code"], "battery_guardian.cell2.signal_stuck"); // sorted by code
        let first = &items[1];
        assert_eq!(first["code"], "battery_guardian.over_temp_warning");
        assert_eq!(first["fault_name"], "BatteryOverTempWarning");
        assert_eq!(first["status"]["test_failed"], true);
        assert_eq!(first["status"]["mask"], "0x21"); // testFailed | testFailedSinceLastClear
        assert_eq!(first["occurrence_counter"], 1);
        assert!(first.get("first_occurrence").is_none());
    }

    #[tokio::test]
    async fn filters_by_status_and_severity() {
        let (_, body) = call(stub(false), "GET", "/?status%5BtestFailed%5D=1").await;
        let codes: Vec<&str> = body["items"].as_array().unwrap().iter().map(|f| f["code"].as_str().unwrap()).collect();
        assert_eq!(codes, ["battery_guardian.over_temp_warning"]);

        let (_, body) = call(stub(false), "GET", "/?status%5Btest_failed%5D=false").await;
        assert_eq!(body["items"][0]["code"], "battery_guardian.cell2.signal_stuck");

        let (_, body) = call(stub(false), "GET", "/?severity=3").await;
        assert!(body["items"].as_array().unwrap().is_empty());

        let (status, body) = call(stub(false), "GET", "/?status%5Bbogus%5D=1").await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
        assert_eq!(body["error_code"], "vendor-specific");
    }

    #[tokio::test]
    async fn detail_carries_environment_data_with_numbers() {
        let (status, body) = call(stub(false), "GET", "/battery_guardian.over_temp_warning").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["item"]["code"], "battery_guardian.over_temp_warning");
        let env = &body["environment_data"];
        assert_eq!(env["temp_c"], 38.4);
        assert_eq!(env["cell"], 2);
        assert_eq!(env["cells"], "38.4,31.2,,30.9"); // not a number: stays a string
        assert_eq!(env["seq"], 4);
        assert_eq!(env["reason"], "getting hot");
        assert_eq!(env["msg_id"], "01a11579-8206-7984-8a95-5cb1f12f78e7");
    }

    #[tokio::test]
    async fn maps_dfm_errors_to_sovd_errors() {
        let (status, body) = call(stub(false), "GET", "/battery_guardian.nope").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(body["vendor_code"], "resource-not-found");

        let (status, body) = call(stub(true), "GET", "/").await;
        assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(body["vendor_code"], "dfm-unavailable");
    }

    #[tokio::test]
    async fn delete_clears_through_the_dfm() {
        let dfm = stub(false);
        assert_eq!(call(dfm.clone(), "DELETE", "/battery_guardian.cell2.signal_stuck").await.0, StatusCode::NO_CONTENT);
        assert_eq!(call(dfm.clone(), "DELETE", "/").await.0, StatusCode::NO_CONTENT);
        assert_eq!(*dfm.deleted.lock().unwrap(), ["battery_guardian/battery_guardian.cell2.signal_stuck", "battery_guardian"]);
    }
}
