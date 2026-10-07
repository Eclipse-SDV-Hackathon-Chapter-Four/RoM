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

Example query output: [`fixtures/battery_guardian_faults.json`](fixtures/battery_guardian_faults.json).
**Hand-written example until it is generated** from a real `dfm_bin` (guardian test scenario replayed into it).

## Testing the OpenSOVD side without the RoM stack

- **Unit tests:** implement `DfmQueryApi` on a stub (or `mockall`) that returns `SovdFault`s built from
  `fixtures/battery_guardian_faults.json`.
- **In-process, real DFM logic:** `DirectDfmQuery::new(storage, registry)` with `KvsSovdFaultStateStorage` on a temp
  dir, records fed through `FaultRecordProcessor` — see fault-lib `src/dfm_lib/examples/sovd_fault_manager.rs`
  (`InMemoryStorage` is `cfg(test)` in fault-lib, not usable from outside).
- **Integration:** run the `dfm` container and replay the scenario into it (no guardian, simulator or MQTT needed);
  the gateway shares its IPC namespace and `/tmp/iceoryx2` (`ipc: "service:dfm"` in compose).
