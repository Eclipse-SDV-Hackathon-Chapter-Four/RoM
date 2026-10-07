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

The dashboard behaves like a live monitoring screen on **simulated telemetry**: `MockDashboardDataSource` publishes a
new `DashboardData` every second (seq +1, latency 80..120 ms) from a deterministic, looping timeline
(`src/data/mockTimeline.ts`, about 59 s per loop):

MONITORING 31 → 37 °C, WARNING 38.2 → 43, CRITICAL / too hot, MITIGATING / cooling requested, MITIGATING /
cooling in progress, CRITICAL / mitigation failed, cooling back through 44 → 41 → 37 → 34 to MONITORING, then a
sensor-fault segment (messages stop, SENSOR_FAULT / stale signal, sensor OFFLINE) and recovery.

States and reasons follow what the real Guardian produces for such a curve. Recent Events gets a row whenever the
state or reason changes. Times are shown in the viewer's local time.

"Demo controls" (collapsed by default, for testing only) jumps the stream to Normal, Warning, Critical or Sensor
fault; the stream keeps running afterwards. The demo never needs it.

## Data boundary (how OpenSOVD plugs in later)

```
React components  ->  useDashboardData(source)  ->  DashboardDataSource.subscribe(cb)
                                                      ->  MockDashboardDataSource (now)
                                                      ->  OpenSovdDataSource (later)
```

- `src/types/dashboard.ts`: the normalized `DashboardData` contract. Components only know this.
- `src/data/DashboardDataSource.ts`: the interface (`subscribe(onData, onError)`, optional `scenarios`).
- `src/data/mockTimeline.ts` and `MockDashboardDataSource.ts`: the simulated stream.
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

AZ3166 → MQTT → Mosquitto → MQTT→KUKSA adapter → KUKSA Databroker → VSS uProtocol client → (uProtocol / Zenoh) →
Guardian, and Guardian → MQTT `rom/actuator/display/cmd` → AZ3166 OLED. The Guardian does not read KUKSA, and the
display command does not use uProtocol.
