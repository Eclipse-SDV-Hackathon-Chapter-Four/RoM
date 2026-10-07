# dashboard: Battery Thermal Guardian demo UI

React + Vite + TypeScript. **Mock data only** for now: OpenSOVD is not ready, so the page reads predefined JSON
snapshots. It does not talk to MQTT, KUKSA, uProtocol or the Guardian.

## Run

```bash
cd services/dashboard
npm install
npm run dev        # http://localhost:5173
npm run build      # typecheck (tsc) + production build into dist/
```

Without a local Node.js: `docker run --rm -it -p 5173:5173 -v "$PWD":/app -w /app node:22-alpine sh -c "npm install && npm run dev -- --host"`.

## Live demo stream

The dashboard behaves like a live monitoring screen on **simulated telemetry** of a **4-cell pack**
(final-demo topology: cell 1 = AZ3166 board, `HW`; cells 2-4 = simulator, `SIM`). `MockDashboardDataSource`
publishes a new `DashboardData` every second (one shared `seq`, latency 80..120 ms) from a deterministic, looping
timeline (`src/data/mockTimeline.ts`, 81 s per loop):

1. Normal, all cells 30-34 °C, MONITORING; cell 1 warms up.
2. Cell 1 crosses 38 °C: WARNING; crosses 45 °C: CRITICAL / too hot, then MITIGATING / cooling requested,
   cooling in progress, then CRITICAL / mitigation failed after 5 s. Cells 2-4 stay lower, so `cell_imbalance` fires.
3. Cooling below 38 °C: MONITORING.
4. Single-cell sensor faults: cell 3 drops out of the message (STALE), cell 2 freezes (STUCK), cell 4 reads
   175 °C (OUT OF RANGE). Each faulty cell shows `-- °C`, is excluded from Pack Max, and the Guardian **stays
   MONITORING** on the remaining cells.
5. Whole stream lost: after 2 s no cell can be trusted, SENSOR_FAULT / stale signal, both sources show NO DATA (neutral: missing telemetry does not prove a source is offline). Then recovery.

The scripted part is only the per-cell values. Pack max, Guardian state and reason, per-cell status and the DFM
fault edges are computed by `src/data/mockGuardian.ts`, a small replica of the rules in
`services/guardian/guardian/guardian.py` (stale 2 s, stuck 10 s, plausibility -40..150, imbalance 10 °C for 2 s,
mitigation timeout 5 s, pack temperature = hottest valid cell, SENSOR_FAULT only without any valid cell).
Heartbeat root causes ("uP link lost", "KUKSA down", ...) are not modelled.

Recent Events has two kinds of rows, told apart by the Scope column: a **Guardian state** row (scope `Pack`) when the
state or reason changes, and a **diagnostic fault** row (`FAULT` / `CLEARED`, scope `Cell n` or `Pack`) for each
DFM fault edge that is not already a state row (cell faults and `cell_imbalance`). Hovering a row shows the real code,
e.g. `battery_guardian.cell3.signal_stale`. Times are shown in the viewer's local time.

"Demo controls" (collapsed by default, mock only, never touches the real board) let you pick a **target** (Pack or one
of C1-C4) and a **scenario** (Normal, Warning, Critical, Stale, Stuck, Out of range, Stream loss) and then resume the
automatic loop with **Resume live**. They change simulated *inputs* only (`src/data/mockOverride.ts`): a cell heats up
(+2 °C per tick to 40.5 / 47.5 °C), stops reporting, freezes at its last value, or reports 175 °C; Stream loss silences
every cell. The mock Guardian then derives the status of each cell, Pack Max, the pack state and the fault codes, so
e.g. C3 + Stale gives STALE on Cell 3 and a pack that keeps supervising the other three (never a global SENSOR_FAULT),
C2 + Stuck takes the real 10 s to show STUCK, and Pack + Stream loss ends in SENSOR_FAULT. Overrides on different
cells stack. Pack + Warning / Critical heats the current Pack Max cell, Pack + Stuck / Out of range means *all* cells
(labelled "All stuck" / "All out of range"), and the nonsensical Pack + Stale and cell + Stream loss are disabled. A cell
target also focuses that cell in Battery Cells, the chart and Recent Events; a pack target returns to the overview.
While an override is active a "Mock override" badge stays visible even if the panel is collapsed.

## Live mode: the running stack (Evidence Collector)

`VITE_DASHBOARD_SOURCE` selects the source explicitly: `mock` (default: simulated telemetry, demo controls) or `live`.
There is deliberately **no automatic fallback** from live to mock, so simulated numbers can never pass for real ones.

```
AZ3166 -> MQTT -> adapter -> KUKSA Cell1 \
simulator ----------------> KUKSA Cells 2-4 -> VSS uProtocol client -> uProtocol/Zenoh -> Guardian
                                                              (cells 8002, heartbeat 8004, fault 8003, state 8006)
                                                                            |
                      Evidence Collector  GET :8082/events?since=&limit=  <--+      (records every bus message)
                                |  (Vite proxy /evidence-api, same origin, because the collector sends no CORS headers)
                                v
              EvidenceCollectorDataSource -> LiveModel -> DashboardData -> the unchanged React components
```

Run it (dev server in Docker needs host networking, because the collector is published on the host's 127.0.0.1:8082):

```bash
make hw        # or make guardian: the stack, including the evidence collector
docker run --rm --network host -v "$PWD/services/dashboard":/app -w /app \
  -e VITE_DASHBOARD_SOURCE=live node:22-alpine sh -lc "npm run dev -- --host 0.0.0.0"
```

Without Docker: `VITE_DASHBOARD_SOURCE=live npm run dev`. `EVIDENCE_API_TARGET` (default `http://localhost:8082`) is where the proxy
points, `VITE_EVIDENCE_API_BASE` (default `/evidence-api`) what the browser calls. See `.env.example`.

**The dashboard displays the Guardian; it does not recompute it.** `src/data/liveModel.ts` only reads the bus messages:

| Dashboard | Comes from |
|---|---|
| pack state, reason | Guardian `state` events (8006); a row in Recent Events only when state or reason changes, not for the ~1 Hz repeat |
| Pack Max (temperature, cell) | Guardian `state.temp_c` / `state.cell`; shown as `--` while the Guardian is in SENSOR_FAULT |
| cell temperatures | `cells` messages (8002). A message holds only the cells written in that update (the AZ3166 adapter writes Cell 1, the simulator Cells 2-4), so a missing cell is **not** a fault: the last value is held |
| cell status (STALE, STUCK, OUT_OF_RANGE) | active Guardian `fault` events: FAILED sets it, PASSED clears it. Whole-stream faults and SENSOR_FAULT without a cell code show STALE / UNTRUSTED |
| FAULT / CLEARED rows | Guardian `fault` events, real `battery_guardian.*` codes in the row tooltip; thermal codes and stream/heartbeat faults are already a state row |
| Data Sources | `heartbeat` messages (8004): `chip` for the AZ3166, `simulator` for Cells 2-4. ALIVE (ok), DOWN (explicit), NO HEARTBEAT (none for 3 s, state unknown) |
| Seq, Last update | `seq` of the latest cells message and the time the collector received the last event |
| Latency | real: collector receive time minus the cell's `source_ts_ms` (KUKSA write to bus), typically 50-110 ms. Not board-to-browser |
| chart | one point per `cells` message, trusted values only; a faulty cell breaks its line |

Polling: the collector returns the *oldest* lines after `since`, so the source finds the tail with a few one-line probes, loads
the last ~2000 lines once (about 2 minutes of history and events), then fetches only new lines every 500 ms. If the API is
unreachable the red "Evidence Collector unreachable" state is shown and the last real data stays on screen; it recovers by
itself, also after a collector restart or reset.

Known limits: a fault that started before that ~2-minute window is not known until its PASSED edge arrives; WARN/CRIT
(38/45 °C) are the Guardian defaults, the events do not carry them; times assume the dashboard and the stack share a clock.

## Data boundary (how OpenSOVD plugs in later)

```
React components  ->  useDashboardData(source)  ->  DashboardDataSource.subscribe(cb)
                                                      ->  MockDashboardDataSource (now)
                                                      ->  OpenSovdDataSource (later)
```

- `src/types/dashboard.ts`: the normalized `DashboardData` contract. Components only know this. Battery data is
  `cells[]` (id, `temperature_c` or null, status OK / STALE / STUCK / OUT_OF_RANGE / NO_DATA, source HW / SIM) plus
  `pack_max_c` / `pack_max_cell`. A real source maps the backend cell message
  `{"cells": {"1": 31.2, "2": 30.1, "4": 29.9}, "seq": 42, "ts_ms": ...}` to it: a cell id that is absent becomes a
  cell with `temperature_c: null` and the status the Guardian reports.
- `src/data/DashboardDataSource.ts`: the interface (`subscribe(onData, onError)`, optional `demo` controls).
- `src/data/mockTimeline.ts`, `mockGuardian.ts` and `MockDashboardDataSource.ts`: the simulated stream.
- `src/App.tsx`: the one place that chooses the source.

To go live, add `src/data/OpenSovdDataSource.ts` that polls (or streams) the OpenSOVD JSON, maps it to
`DashboardData` (the only file that should parse OpenSOVD) and calls `onData` on every update, then construct it in
`App.tsx`. A live source leaves `demo` undefined, so the demo controls disappear. The components under
`src/components/` stay unchanged.

## Thresholds

`warn_c` / `crit_c` (38 / 45 °C) come from the data and are conservative supervisory demo values, not universal
limits. The Guardian's plausibility bounds (−40 / 150 °C) only validate the sensor reading; the UI never shows
them as thermal thresholds.

## System flow shown

AZ3166 (cell 1) → MQTT → Mosquitto → MQTT→KUKSA adapter → KUKSA Databroker; the simulator (cells 2-4) writes to
KUKSA directly; KUKSA → VSS uProtocol client → (uProtocol / Zenoh) → Guardian (one node), and Guardian → MQTT
`rom/actuator/display/cmd` → AZ3166 OLED. The Guardian does not read KUKSA, and the
display command does not use uProtocol.
