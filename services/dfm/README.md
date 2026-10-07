<!-- Made with Claude (Claude Code, Anthropic) -->
# dfm — Diagnostic Fault Manager

Eclipse OpenSOVD [`fault-lib`](https://github.com/eclipse-opensovd/fault-lib) DFM (`dfm_bin`), set up as in the
[OpenSOVD Starter Template](https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/OpenSOVD-Starter-Template).
The guardian reports `Failed` / `Passed` for every fault it detects; the DFM keeps the fault records
(ISO 14229 lifecycle) and serves them on the iceoryx2 `dfm/query` service, which the OpenSOVD gateway reads.

```
guardian --MQTT rom/guardian/fault--> rom-dfm report --fault-lib Reporter (iceoryx2)--> dfm_bin --dfm/query--> OpenSOVD
```

## Output contract (what OpenSOVD reads)

The interface is fault-lib's own query API, not RoM code:

- trait `dfm_lib::DfmQueryApi`: `get_all_faults(path)`, `get_fault(path, code)`, `delete_all_faults`, `delete_fault`
- live implementation `dfm_lib::Iceoryx2DfmQuery` (iceoryx2 request-response service `dfm/query`)
- returns `dfm_lib::sovd_fault_manager::SovdFault` (+ `SovdEnvData` = `HashMap<String, String>` from `get_fault`)
- fault-lib revision: `12dac502616701734f90a61edca1326ae2ac6506` (use the same one, IPC types must match)

What RoM fixes on top of that:

| | Value |
|---|---|
| Entity path (catalog id) | `battery_guardian` → `GET /sovd/v1/apps/battery_guardian/faults` |
| Fault catalog | [`catalog/battery_guardian.json`](catalog/battery_guardian.json) — load this file, don't copy the codes |
| Env data keys | `temp_c`, `reason`, `seq`, `msg_id` (uProtocol message that caused it), `ts_ms` |
| Lifecycle | `Failed` when the condition starts, `Passed` when it clears (no debounce, every transition is a record) |

| Code | Name | Failed while the guardian is in | Severity |
|---|---|---|---|
| `battery_guardian.over_temp_warning` | BatteryOverTempWarning | `WARNING` | Warn |
| `battery_guardian.over_temp_critical` | BatteryOverTempCritical | `CRITICAL` or `MITIGATING` | Error |
| `battery_guardian.mitigation_failed` | BatteryMitigationFailed | `CRITICAL` "mitigation failed" | Fatal |
| `battery_guardian.signal_stale` | BatteryTempSignalStale | `SENSOR_FAULT` "stale signal" | Error |
| `battery_guardian.signal_stuck` | BatteryTempSignalStuck | `SENSOR_FAULT` "stuck signal" | Error |
| `battery_guardian.out_of_range` | BatteryTempOutOfRange | `SENSOR_FAULT` "out of range" | Error |

Example query output: [`fixtures/battery_guardian_faults.json`](fixtures/battery_guardian_faults.json) — generated,
not hand-written: the guardian test scenario ([`fixtures/guardian_events.jsonl`](fixtures/guardian_events.jsonl),
`rom-guardian --fault-events`) replayed into a real `dfm_bin`, then `rom-dfm query --stable` (no timestamps).
Regenerate with `make dfm-fixtures`; a guardian test fails if the events drift from the scenario.

## Run

```bash
make guardian       # whole stack incl. mosquitto + dfm
make dfm-faults     # fault records in the running DFM (JSON)
mosquitto_sub -t rom/guardian/fault -v   # raw guardian fault events
```

The `dfm` container runs `dfm_bin` (catalog dir `/etc/rom/catalog`, storage `/var/lib/rom-dfm`) and
`rom-dfm report` (Rust, [`src/main.rs`](src/main.rs)). Both are built inside the fault-lib workspace at the
pinned revision, so the IPC types match. Records are lost when the container is recreated (no storage volume yet).

| Command (inside the container) | What |
|---|---|
| `rom-dfm report` | MQTT `rom/guardian/fault` → fault-lib `Reporter` → DFM (default) |
| `rom-dfm replay <events.jsonl>` | same events from a file, e.g. `/etc/rom/fixtures/guardian_events.jsonl` |
| `rom-dfm query [--stable]` | all records of `battery_guardian` as JSON |

| Env | Default |
|---|---|
| `MQTT_HOST` / `MQTT_PORT` | `localhost` / `1883` |
| `CATALOG` | `/etc/rom/catalog/battery_guardian.json` |
| `DFM_PATH` (query) | `battery_guardian` |

Guardian event (`libs/rom-common` `build_fault_event`, QoS 1):
`{"fault":"BatteryTempSignalStale","stage":"Failed","ts_ms":…,"temp_c":30.0,"reason":"stale signal","seq":18,"msg_id":"…"}`

## Testing the OpenSOVD side without the RoM stack

- **Unit tests:** implement `DfmQueryApi` on a stub (or `mockall`) that returns `SovdFault`s built from
  `fixtures/battery_guardian_faults.json`.
- **In-process, real DFM logic:** `DirectDfmQuery::new(storage, registry)` with `KvsSovdFaultStateStorage` on a temp
  dir, records fed through `FaultRecordProcessor` — see fault-lib `src/dfm_lib/examples/sovd_fault_manager.rs`
  (`InMemoryStorage` is `cfg(test)` in fault-lib, not usable from outside).
- **Integration:** a real DFM with known records, no guardian, simulator or MQTT needed:
  ```bash
  docker compose -f infra/docker-compose.yml --profile tools up -d dfm
  docker compose -f infra/docker-compose.yml --profile tools exec dfm rom-dfm replay /etc/rom/fixtures/guardian_events.jsonl
  ```
  The gateway container joins the DFM's shared memory with `ipc: "service:dfm"` and
  `volumes: [iceoryx2:/tmp/iceoryx2]` in `infra/docker-compose.yml`.
