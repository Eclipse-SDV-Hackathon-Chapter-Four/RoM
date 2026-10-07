<!-- Made with Claude (Claude Code, Anthropic) -->
# dfm — Diagnostic Fault Manager

```
guardian --uProtocol up://rom-vehicle/1002/1/8003 (FaultEvent JSON)--> rom-dfm report --fault-lib Reporter--> dfm_bin
        --iceoryx2 dfm/query--> rom-opensovd (services/opensovd) --HTTP--> /sovd/v1/apps/battery_guardian/faults
```

Eclipse OpenSOVD [`fault-lib`](https://github.com/eclipse-opensovd/fault-lib) DFM (`dfm_bin`) plus `rom-dfm report`
(Rust, [`src/main.rs`](src/main.rs)): every guardian `FAILED` / `PASSED` edge becomes a fault-lib record
(ISO 14229 lifecycle), served on iceoryx2 `dfm/query` to `services/opensovd`.

## 1. Catalog — [`catalog/battery_guardian.json`](catalog/battery_guardian.json)

fault-lib catalog format, `"id": "battery_guardian"` (= DFM entity path = SOVD app id), 27 `Text` codes,
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
| `battery_guardian.cell{1..4}.rate_implausible` | Warn | that cell changed faster than `MAX_RATE_C_PER_S` (10 °C/s); the reading is kept |
| `battery_guardian.link_integrity` | Warn | 3 duplicated / reordered cell messages within 5 s (discarded) |
| `battery_guardian.{uprotocol_lost,databroker_down,adapter_down,simulator_down,chip_silent}` | Error | heartbeat root cause, see [`../guardian/README.md`](../guardian/README.md) |

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
| `code` | string | one of the 27 catalog codes |
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

## 3. Reporter (`rom-dfm`)

- catalog → one fault-lib `Reporter` per `Text` code; every event →
  `reporter.publish("battery_guardian", reporter.create_record(Failed|Passed))` with the environment data above
  (8 keys = fault-lib `MetadataVec` capacity; values over 64 bytes are dropped and logged as `env_dropped`).
- One container (iceoryx2 between them): `dfm_bin --catalog-dir /etc/rom/catalog --storage-dir /var/lib/rom-dfm`
  + `rom-dfm report`, both built inside the fault-lib workspace at `12dac50` (same rev as `services/opensovd`).
  If either exits, the container exits (compose restarts it). Records survive restarts (`dfm-storage` volume).
- iceoryx2: tmpfs volumes `iceoryx2-shm` (`/dev/shm`) and `iceoryx2` (`/tmp/iceoryx2`) shared with `opensovd`;
  runs as root like `opensovd` (iceoryx2 files are owner-only).
- Every write is a JSON line:
  `{"event":"fault_record","code":…,"stage":"FAILED","run_id":…,"latency_ms":…,"ts_ms":<write time>,"env":{…}}`
  (`latency_ms` = write time − the guardian's `ts_ms`; on failure `publish_failed`, bad payloads `rejected`).

| Command (inside the container) | What |
|---|---|
| `rom-dfm report` | uProtocol `up://<UP_AUTHORITY>/1002/1/8003` → DFM (default) |
| `rom-dfm replay <events.jsonl>` | same events from a file, e.g. `/etc/rom/fixtures/guardian_events.jsonl` |
| `rom-dfm query [--stable]` | all records of `battery_guardian` as JSON (`--stable`: no timestamps) |

| Env | Default |
|---|---|
| `UP_AUTHORITY` | `rom-vehicle` |
| `ZENOH_MODE` / `ZENOH_CONNECT` / `ZENOH_LISTEN` | `peer` / – / – (compose: `ZENOH_CONNECT=tcp/guardian:7447`) |
| `CATALOG` | `/etc/rom/catalog/battery_guardian.json` |
| `DFM_PATH` (query) | `battery_guardian` |

```bash
make guardian       # whole stack incl. dfm + opensovd
make campaign C=sensor_stuck_cell3
make dfm-faults     # records straight from the DFM (JSON)
make sovd-faults    # the same over SOVD
```

Fixtures: [`fixtures/guardian_events.jsonl`](fixtures/guardian_events.jsonl) is the guardian test scenario
(`rom-guardian --fault-events`), [`fixtures/battery_guardian_faults.json`](fixtures/battery_guardian_faults.json)
is that replayed into a real `dfm_bin` (`rom-dfm query --stable`). Regenerate with `make dfm-fixtures`; CI and a
guardian test fail if they drift.

Known limits: fault events are not buffered (the guardian starts after the dfm; dfm's Zenoh retries until the
guardian listens); the reporter waits 50 ms after each record because the DFM's iceoryx2 subscriber buffer is
small and a burst would lose records.

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
