<!-- Made with Claude (Claude Code, Anthropic) -->
# Plan: cell-aware diagnostics (4 battery cells → guardian → DFM → OpenSOVD)

## Status (2026-10-07)

| Part | Status |
|---|---|
| Contracts C1, C2, C3 | ✅ done: `rom_uprotocol.contract`, `rom_common.contracts.FAULT_CODES`, `services/dfm/catalog/battery_guardian.json` |
| WP1 rom_uprotocol + vss-uprotocol-client | ✅ done, plus `coalesce()`: the databroker notifies each path separately |
| WP2 guardian | ✅ done, verified live with 5 campaigns |
| WP3 DFM reporter (Rust) | ⏳ open: handover in [`services/dfm/README.md`](../services/dfm/README.md) |
| WP4 OpenSOVD | ✅ fixtures and docs (no logic change needed); `data/` resource still open |
| WP5 campaigns | ✅ `expected_faults` on every campaign, 2 new single-cell campaigns |

## Why

The simulator now writes four cells (`Vehicle.Powertrain.TractionBattery.Cells.Cell1..4.Temperature`,
overlay [`infra/vss/rom_cells.json`](../infra/vss/rom_cells.json)) plus `Temperature.Max`. Everything after
KUKSA still sees only `Max`:

| Component | Today | Consequence |
|---|---|---|
| vss-uprotocol-client | forwards `Temperature.Max` on `up://rom-vehicle/1001/1/8001` | cells never leave KUKSA |
| guardian | one state machine on one value | a fault on a cell that is not the hottest is invisible; freezing one cell is not detected |
| guardian → DFM | nothing is sent yet | no DFM records from real runs |
| DFM catalog | does not exist in the repo | `services/dfm` is a placeholder |
| OpenSOVD (`services/opensovd`) | generic: passes codes and environment data through | only fixtures and docs name concrete codes |

Goal: every cell is monitored on its own, a bad sensor raises **its own DTC**, and one bad sensor never
disarms the thermal warning for the healthy cells.

## Decisions

1. **Sensor faults get one code per cell** (`battery_guardian.cell2.signal_stuck`). Pack faults keep one code
   and carry `cell` in the environment data. Two broken cells show up as two independent SOVD records.
2. **Guardian → DFM goes over uProtocol** (challenge: fault and mitigation events over uProtocol).
   The DFM reporter is Rust: `up-rust` + `up-transport-zenoh`; our Python transport follows the same up-spec key format.
3. `up://…/1001/1/8001` (Max) stays unchanged, so the current guardian and campaigns keep working during the switch.

## Contracts (land these first, in one small PR, so everyone codes against them)

### C1. Cell topic — vss-uprotocol-client → guardian

| | |
|---|---|
| Topic | `up://<UP_AUTHORITY>/1001/1/8002` (`UP_RESOURCE_BATTERY_CELLS = 0x8002`) |
| Payload (JSON) | `{"cells":{"1":31.2,"2":30.1,"4":29.9},"seq":42,"ts_ms":…,"source_ts_ms":…}` |
| Rule | one message per KUKSA update; a cell that was **not written** in that update is **absent** (that is how a single-cell dropout becomes visible) |

### C2. Guardian fault events — guardian → DFM reporter

| | |
|---|---|
| Topic | `up://<UP_AUTHORITY>/1002/1/8003` (guardian entity 0x1002, `UP_RESOURCE_GUARDIAN_FAULT = 0x8003`) |
| Payload (JSON) | `{"code":"battery_guardian.cell2.signal_stuck","stage":"FAILED","cell":2,"temp_c":30.1,"cells":"31.2,30.1,29.8,29.9","reason":"stuck signal","seq":42,"msg_id":"…","ts_ms":…,"run_id":"sensor-stuck-cell2-01"}` |
| `stage` | `FAILED` when the fault starts, `PASSED` when it clears (the DFM does healing / aging) |
| Rule | one event per edge, never per tick; `cell` = the faulty cell, the hottest cell for thermal faults and imbalance, `null` for `signal_stale` |

`run_id` comes from the campaign (the guardian learns it from a run marker or env; until then `null`).

### C3. DFM catalog — `services/dfm/catalog/battery_guardian.json`

fault-lib catalog format (see `fault-lib/src/fault_lib/tests/data/hvac_fault_catalog.json`), `"id": "battery_guardian"`,
`Text` ids. 17 codes:

| Code | Severity | Raised when |
|---|---|---|
| `battery_guardian.over_temp_warning` | Warn | max of the **valid** cells ≥ `WARN_C` |
| `battery_guardian.over_temp_critical` | Error | max of the valid cells ≥ `CRIT_C` |
| `battery_guardian.mitigation_failed` | Fatal | still hot `MITIGATION_TIMEOUT_S` after cooling was requested |
| `battery_guardian.signal_stale` | Error | no cell message at all for `STALE_MS` (transport drop / delay, replay interruption) |
| `battery_guardian.cell_imbalance` | Error | max − min of the valid cells > `IMBALANCE_C` (default 10 °C) for 2 s |
| `battery_guardian.cell{1..4}.signal_stale` | Error | that cell missing for `STALE_MS` while others arrive (cell dropout) |
| `battery_guardian.cell{1..4}.signal_stuck` | Error | that cell unchanged for `STUCK_S` |
| `battery_guardian.cell{1..4}.out_of_range` | Error | that cell outside `MIN/MAX_PLAUSIBLE_C` |

Environment data keys (strings in the DFM, numbers in SOVD): `temp_c`, `cell`, `cells`, `reason`, `seq`, `msg_id`, `ts_ms`, `run_id`.

## Work packages

### WP1 — rom_uprotocol + vss-uprotocol-client (Person B)
- `rom_uprotocol/contract.py`: `UP_RESOURCE_BATTERY_CELLS`, `UP_RESOURCE_GUARDIAN_FAULT`, `build_/parse_cells_msg`, `build_/parse_fault_event`.
- `rom_uprotocol/uris.py`: `battery_cells_topic()`, `guardian_fault_topic()`.
- `rom_uprotocol/publisher.py`: publish a prebuilt payload on any topic through the same interceptor chain, so
  `TransportFaults` (drop, delay, duplicate, reorder) hits the cell topic too.
- vss-uprotocol-client: `KuksaCellsSource` subscribes to `contracts.VSS_CELL_TEMPS` and yields one dict per update;
  `__main__` publishes it on C1 next to the existing Max topic.
- Tests: payload round trip, a missing cell stays missing, interceptors apply to the cell topic.

### WP2 — guardian (guardian owner)
- Per-cell monitor: last value, last receive time, last change → `signal_stale` / `signal_stuck` / `out_of_range` per cell.
- Pack temperature = max of the valid cells. `SENSOR_FAULT` only when **no** cell is valid or the whole stream is stale;
  otherwise the thermal state machine keeps running on the healthy cells (safety argument: one bad sensor never disarms the warning).
- `cell_imbalance` on the valid cells.
- Keep the set of active codes; on every change publish C2 `FAILED` / `PASSED` edges; log `fault_event` with the same fields.
- Subscribe to C1 instead of 0x8001.
- Tests: single-cell stuck / dropout / out-of-range raise only that cell's code and keep the thermal state; all cells stuck → `SENSOR_FAULT`.

### WP3 — DFM (DFM colleague)
- Commit the catalog C3.
- `rom-dfm report` in Rust: subscribe to C2 (`up-rust` + `up-transport-zenoh`, endpoint from env, e.g. `tcp/vss-uprotocol-client:7447`),
  one `Reporter` per catalog code, `publish("battery_guardian", record(Failed|Passed))` with the environment data from C3.
- Run `dfm_bin --catalog-dir services/dfm/catalog` next to it; same `fault-lib` rev as `services/opensovd` (`12dac50`).
- **Do first (spike, ≤ 1 h):** a Python `SignalPublisher` message on C2 received by a Rust `up-transport-zenoh` subscriber.
  If keys or attachments do not match, fix `rom_uprotocol/transport/zenoh.py` (the spec examples are already tested there).

### WP4 — OpenSOVD (Person B, small)
- `src/faults.rs` needs no logic change (codes and env keys pass through, numbers stay numbers).
- Update the test fixtures to cell codes (`battery_guardian.cell2.signal_stuck` with `cell` = 2) and the README contract section.
- Later: `data/` resource on `battery_guardian` with the live cell temperatures.

### WP5 — fault-injector campaigns (campaign owner)
- New field `expected_faults: [codes]` per campaign, for the evidence collector to check in SOVD.
- Update expectations that change with per-cell monitoring:

| Campaign | Fault | New `expected_state` | `expected_faults` |
|---|---|---|---|
| `out_of_range` | cell 1 = 200 °C | `MONITORING` (was `SENSOR_FAULT`) | `cell1.out_of_range` |
| `sensor_stuck` | all cells stuck | `SENSOR_FAULT` | `cell1..4.signal_stuck` |
| `source_dropout` | all cells dropped | `SENSOR_FAULT` | `signal_stale` |
| `thermal_runaway` | drift on cell 1 | `CRITICAL` | `over_temp_warning`, `over_temp_critical`, `cell_imbalance` |
| `transport_drop` / `transport_delay` / `replay_interruption` | stream lost / late | `SENSOR_FAULT` | `signal_stale` |

- New campaigns now possible: `sensor_stuck_cell3` (one cell frozen), `cell_dropout_cell2`.

## Order

1. Contract PR (C1, C2, C3 + this file) → merge to `main`.
2. In parallel: WP1, WP2, WP3 (spike first), WP5.
3. WP4 once WP3 writes real records.
4. End-to-end check below.

## Verification

```bash
make test                                              # all Python tests
make guardian                                          # chain up
make sovd                                              # dfm + opensovd
make campaign C=sensor_stuck_cell3
make sovd-faults                                       # battery_guardian.cell3.signal_stuck, test_failed: true
curl -s localhost:7690/sovd/v1/apps/battery_guardian/faults/battery_guardian.cell3.signal_stuck   # environment_data.cell = 3
```

Pass criteria: the code appears in SOVD within 2 s of the guardian's `fault_event`, `environment_data.msg_id` matches
the guardian log, and the guardian state stays thermal (not `SENSOR_FAULT`) while three cells are healthy.
