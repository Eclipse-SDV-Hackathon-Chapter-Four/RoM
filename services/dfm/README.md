<!-- Made with Claude (Claude Code, Anthropic) -->
# dfm — Diagnostic Fault Manager (handover: 4-cell contract is ready, Rust reporter is TODO)

```
guardian --uProtocol up://rom-vehicle/1002/1/8003 (FaultEvent JSON)--> rom-dfm report --fault-lib Reporter--> dfm_bin
        --iceoryx2 dfm/query--> rom-opensovd (services/opensovd) --HTTP--> /sovd/v1/apps/battery_guardian/faults
```

Everything up to the fault topic is done and verified live (see "Verified" below). What is left for this service:
receive the events and write them into the DFM with fault-lib.

The Python package here (`rom-dfm`, `dfm/__main__.py`) is still the placeholder; replace it with the Rust reporter.

## 1. Catalog — [`catalog/battery_guardian.json`](catalog/battery_guardian.json)

fault-lib catalog format, `"id": "battery_guardian"` (= DFM entity path = SOVD app id), 17 `Text` codes,
no debounce (the guardian already debounces: `STUCK_S`, `IMBALANCE_S`, `STALE_MS`).

| Code | Severity | Raised by the guardian when |
|---|---|---|
| `battery_guardian.over_temp_warning` | Warn | hottest **valid** cell ≥ `WARN_C` (38 °C) |
| `battery_guardian.over_temp_critical` | Error | hottest valid cell ≥ `CRIT_C` (45 °C) |
| `battery_guardian.mitigation_failed` | Fatal | still critical 5 s after cooling was requested |
| `battery_guardian.signal_stale` | Error | no cell message at all for `STALE_MS` (2 s) |
| `battery_guardian.cell_imbalance` | Error | hottest − coldest valid cell > `IMBALANCE_C` (10 °C) for `IMBALANCE_S` (2 s) |
| `battery_guardian.cell{1..4}.signal_stale` | Error | that cell missing for 2 s while the others arrive |
| `battery_guardian.cell{1..4}.signal_stuck` | Error | that cell unchanged for `STUCK_S` (10 s) |
| `battery_guardian.cell{1..4}.out_of_range` | Error | that cell outside −40..150 °C |

The same list is `rom_common.contracts.FAULT_CODES`; `tests/test_catalog.py` fails if the two drift apart.
**Add a code in both places in the same PR.**

## 2. Fault events — what the reporter subscribes to

| | |
|---|---|
| Topic | `up://rom-vehicle/1002/1/8003` (guardian uEntity `0x1002`, version 1, resource `0x8003`) |
| Zenoh key | `up/rom-vehicle/1002/0/1/8003/{}/{}/{}/{}/{}` (up-spec 10-segment key, attachment = `0x01` + protobuf `UAttributes`) |
| Endpoint | the guardian listens on `tcp/0.0.0.0:7447`; in compose connect to `tcp/guardian:7447` (`ZENOH_CONNECT`) |
| Message | publish, `UPAYLOAD_FORMAT_JSON`, **no TTL** (an edge never expires) |
| When | once per edge: `FAILED` when a fault starts, `PASSED` when it clears. Never per tick. |

```json
{"code":"battery_guardian.cell3.signal_stuck","stage":"FAILED","ts_ms":1791367830419,"cell":3,
 "temp_c":26.75,"cells":"26.75,25.59,23.39,23.42","reason":"stuck signal","seq":31,
 "msg_id":"01a115d7-3974-7762-9130-3d31e9e56013","run_id":"sensor-stuck-cell3-01"}
```

| Field | Type | Meaning |
|---|---|---|
| `code` | string | one of the 17 catalog codes |
| `stage` | `FAILED` / `PASSED` | → `LifecycleStage::Failed` / `Passed` |
| `ts_ms` | int | when the guardian saw the edge (epoch ms) |
| `cell` | int / null | cell of a sensor fault; hottest cell for thermal faults and imbalance; null for `signal_stale` |
| `temp_c` | float / null | pack temperature (max of the valid cells) at the edge |
| `cells` | string | all four cells, `"31.2,30.1,,29.9"` (cell 1..4, empty = never arrived) |
| `reason` | string | human-readable (`stuck signal`, `getting hot`, ...; `cleared` on `PASSED`) |
| `seq`, `msg_id` | int, string / null | the cell message that triggered the edge: correlation with the guardian log |
| `run_id` | string / null | campaign run (from the fault-injector), null outside campaigns |

Python reference: `rom_uprotocol.contract.FaultEvent` / `parse_fault_event`.

### Environment data for the DFM record

Put these keys into the record's environment data (all strings, skip null / empty), exactly as
`FaultEvent.environment_data()` builds them: `cell`, `temp_c`, `cells`, `reason`, `seq`, `msg_id`, `ts_ms`, `run_id`.
OpenSOVD passes them through and turns the numeric ones back into JSON numbers.

## 3. What to build (Rust)

1. **Spike first (≤ 1 h):** a Rust `up-transport-zenoh` subscriber on the key above receives one event from the
   running stack. If keys or attachments do not match, fix `libs/rom-uprotocol/rom_uprotocol/transport/zenoh.py`
   (its tests already check the key against every up-spec example).
2. `rom-dfm report`: catalog → one `Reporter` per code; for every event
   `reporter.publish("battery_guardian", reporter.create_record(Failed|Passed))` with the environment data above.
3. Image: `dfm_bin --catalog-dir /catalog` + the reporter in one container (iceoryx2 between them),
   same `fault-lib` rev as `services/opensovd` (`12dac50`), iceoryx2 volumes as in `infra/docker-compose.yml`.
4. Log every write (`code`, `stage`, `run_id`, write time) as a JSON line: the evidence collector needs the DFM write latency.

Contract notes for OpenSOVD (iceoryx2, restarts, same user) are in [`../opensovd/README.md`](../opensovd/README.md#contract-with-servicesdfm).

## 4. See the events without the DFM

```bash
make guardian                                     # stack (if port 1883 is taken by a system mosquitto, see services/adapter/README.md)
docker compose -f infra/docker-compose.yml --profile tools run --rm --no-deps \
  -e ZENOH_CONNECT=tcp/guardian:7447 dev rom-up-monitor --faults       # prints every FaultEvent
make campaign C=sensor_stuck_cell3                # in another terminal
```

## Verified (2026-10-07, live, simulator → KUKSA → client → guardian → fault topic)

| Campaign | Fault events on `…/1002/1/8003` | Guardian state |
|---|---|---|
| `sensor_stuck_cell3` | `cell3.signal_stuck` FAILED 10 s after the freeze, PASSED after it | stays `MONITORING` |
| `cell_dropout_cell2` | `cell2.signal_stale` FAILED ~2.4 s after the dropout, PASSED after it | stays `MONITORING` |
| `out_of_range` (cell 1 = 200 °C) | `cell1.out_of_range` FAILED at once, PASSED after | stays `MONITORING` |
| `sensor_stuck` (all cells) | `cell1..4.signal_stuck` FAILED, then PASSED | `SENSOR_FAULT` "stuck signal" |
| `thermal_runaway` (drift on cell 1) | `cell_imbalance`, `over_temp_warning`, `over_temp_critical`, `mitigation_failed` FAILED, all PASSED at the end | `WARNING` → `CRITICAL` → `MITIGATING` → `CRITICAL` |

Every event carried the campaign `run_id`.
