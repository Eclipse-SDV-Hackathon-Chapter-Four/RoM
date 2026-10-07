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

## Demo scenarios

The buttons under the header (Normal, Warning, Critical, Sensor fault) switch between four snapshots in
`src/data/mock-dashboard.json`. Each snapshot is a complete `DashboardData`, so temperature, Guardian state,
sensor status, last message, chart and events all change together. Reasons and state sequences follow the real
Guardian (for example `CRITICAL / too hot`, then `MITIGATING / cooling requested`, then `CRITICAL / mitigation failed`).

## Data boundary (how OpenSOVD plugs in later)

```
React components  ->  useDashboardData(source)  ->  DashboardDataSource  ->  MockDashboardDataSource (now)
                                                                         ->  OpenSovdDataSource (later)
```

- `src/types/dashboard.ts`: the normalized `DashboardData` contract. Components only know this.
- `src/data/DashboardDataSource.ts`: the interface (`fetch()`, optional `scenarios`).
- `src/data/MockDashboardDataSource.ts`: serves the JSON snapshots.
- `src/App.tsx`: the one place that chooses the source.

To go live, add `src/data/OpenSovdDataSource.ts` that fetches the OpenSOVD JSON and maps it to `DashboardData`
(that file is the only one that should parse OpenSOVD), then construct it in `App.tsx` and pass a poll interval to
`<Dashboard pollMs={2000} />`. A live source leaves `scenarios` undefined, so the scenario buttons disappear.
The components under `src/components/` stay unchanged.

## Thresholds

`warn_c` / `crit_c` (38 / 45 °C) come from the data and are conservative supervisory demo values, not universal
limits. The Guardian's plausibility bounds (−40 / 150 °C) only validate the sensor reading; the UI never shows
them as thermal thresholds.

## System flow shown

AZ3166 → MQTT → Mosquitto → MQTT→KUKSA adapter → KUKSA Databroker → VSS uProtocol client → (uProtocol / Zenoh) →
Guardian, and Guardian → MQTT `rom/actuator/display/cmd` → AZ3166 OLED. The Guardian does not read KUKSA, and the
display command does not use uProtocol.
