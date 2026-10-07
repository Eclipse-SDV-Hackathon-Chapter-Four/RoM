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

"Demo controls" (collapsed by default, for testing only) jumps the stream to Normal, Warning, Critical, Cell faults
or Stream loss; the stream keeps running afterwards. The demo never needs it.

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
- `src/data/DashboardDataSource.ts`: the interface (`subscribe(onData, onError)`, optional `scenarios`).
- `src/data/mockTimeline.ts`, `mockGuardian.ts` and `MockDashboardDataSource.ts`: the simulated stream.
- `src/App.tsx`: the one place that chooses the source.

To go live, add `src/data/OpenSovdDataSource.ts` that polls (or streams) the OpenSOVD JSON, maps it to
`DashboardData` (the only file that should parse OpenSOVD) and calls `onData` on every update, then construct it in
`App.tsx`. A live source leaves `scenarios` undefined, so the demo controls disappear. The components under
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
