# dashboard: Battery Thermal Guardian demo UI

React + Vite + TypeScript. Two top-level views (tabs, also reachable by URL):

| View | URL | What it shows |
|---|---|---|
| **Live Monitoring** | <http://localhost:5173/#/live> | the running stack in real time: cells, Pack Max, Guardian state, events, chart, and the **Run Scenario** control |
| **Safety Evidence** | <http://localhost:5173/#/evidence> | the Evidence Collector's own `report.html` of a completed run, embedded unchanged, with run id and PASS / FAIL / INCONCLUSIVE counts |

Data comes from the real stack through the Evidence Collector (`VITE_DASHBOARD_SOURCE=live`); a mock source with
simulated telemetry also exists (see [Mock mode](#mock-mode)). Nothing on screen is simulated in live mode.

## Setup for a teammate (from a fresh clone)

**Prerequisites:** Git, Docker Engine with the Compose plugin (`docker compose version`), `curl`, `python3`, a browser, and
roughly 20 GB of free disk (the first build of the Rust services `dfm` and `opensovd` used about 10 GB here). You do **not**
need Node.js: the dashboard runs in a Docker container. Your user must be able to use Docker without `sudo`
(`docker info` works; otherwise `sudo usermod -aG docker $USER` and log in again). Developed and tested on Linux
(Ubuntu); the dashboard container uses `--network host`, which behaves differently on Docker Desktop (macOS / Windows), where this
flow is untested.

```bash
git clone https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/RoM.git
cd RoM
git checkout gui            # the dashboard lives on the gui branch
```

**1. Runtime stack** (terminal 1): databroker, simulator, VSS uProtocol client, Guardian, DFM, OpenSOVD, Evidence Collector.

```bash
make images                 # once: builds the service images, including the fault injector that Run Scenario uses
make guardian               # starts the stack and then FOLLOWS the guardian log; Ctrl+C stops following, not the stack
```

Wait until it is healthy (second terminal, the first build takes a while):

```bash
curl -s localhost:8082/health      # "guardian_state":"MONITORING"
```

**2. Dashboard** (terminal 2, same clone):

```bash
make dashboard              # = scripts/dashboard-dev.sh; first start runs npm ci inside the container
```

Open <http://localhost:5173/#/live>. `make dashboard-stop` stops it (`scripts/dashboard-dev.sh logs` shows its log).

What `make dashboard` sets up, so you do not have to: an image with Node + the Docker CLI (`Dockerfile.dev`), host networking
(the collector is on the host's `localhost:8082`), `/var/run/docker.sock`, and the repository mounted at its **own absolute
path** with `ROM_RUNTIME_REPO` set to it. The last two matter because **Run Scenario** runs `docker compose` from inside the
container, while the bind mounts of `infra/docker-compose.yml` are resolved by the *host* Docker daemon; the same path on both
sides keeps them valid, wherever you cloned. If the stack runs from another checkout:
`ROM_RUNTIME_REPO=/path/to/that/checkout make dashboard`.

**3. Stop everything:** `make dashboard-stop` and `make down` (stops the whole runtime stack).

### Demo quick start (copy / paste)

```bash
# terminal 1
make images && make guardian
# terminal 2, once the health check above says MONITORING
make dashboard
```

Browser <http://localhost:5173/#/live> → pick **Thermal Runaway** → **Run Scenario** → watch the temperature and the Guardian state
change (WARNING, MITIGATING, back to MONITORING) → when it says "Scenario completed", run `make evidence-snapshot` and open
<http://localhost:5173/#/evidence>.

## Run Scenario (Live Monitoring)

`Scenario [ dropdown ] [ Run Scenario ]` starts **one real fault-injection campaign** against the running stack. It is not a
frontend simulation: the dev server (`vite/scenarios.mjs`) runs exactly what `make campaign C=<id>` runs,

```bash
docker compose -f infra/docker-compose.yml --profile tools run --rm -T fault-injector rom-fault-injector run <campaign_id>
```

so the fault injector drives the simulator / publisher, the Guardian reacts through its real state machine, and the Evidence
Collector judges the run and writes an evidence record.

1. Choose a scenario, click **Run Scenario** (nothing runs on page load).
2. The selector and button lock; the status line shows `Running: <scenario>`. Live telemetry keeps updating.
3. When the process ends: `Scenario completed (exit code 0)` or `Scenario failed (exit code N)` with the tail of its output.
   The exit code only says the injector finished; the PASS / FAIL verdict is the evidence record (Safety Evidence).
4. **Stop** (enabled only while a scenario runs) interrupts the real campaign: `Stopping: <scenario>`, then `Scenario stopped: <scenario>`.
   The server sends SIGINT to exactly that campaign container (named `rom-dashboard-campaign-<id>-<random>`, labelled
   `rom.dashboard.campaign`), so the fault injector clears its injected faults and logs `campaign_end: interrupted`; only if it
   has not exited after 5 s is that same container force-killed and removed. The rest of the stack is untouched. "Stopped" is an
   orchestration status, never PASS: the Evidence Collector records an interrupted run as INCONCLUSIVE ("campaign interrupted").

Rules enforced by the server (`vite/scenarios.mjs`, tested in `vite/scenarios.test.mjs`): only the 15 IDs below are accepted
(the browser sends an ID, never a command; anything else gets `400`); one campaign at a time (`409` for a second request);
`409` also while a stop is in progress, `503` when the stack is not healthy, i.e. the collector does not answer, the Guardian is not `MONITORING`, or a campaign is
still open in the collector (an overlapping run would be judged INCONCLUSIVE). Run them one after another, the two we timed took 30 s and 75 s. API: `GET /api/scenarios`, `GET /api/scenarios/status` (`idle`, `running`, `stopping`, `completed`, `failed`, `stopped`),
`POST /api/scenarios/run {"scenario":"<id>"}`, `POST /api/scenarios/stop` (no body; `409` if nothing is running).
It exists only on the dev server (`make dashboard` / `npm run dev`), not in a static build.

| UI label | Campaign ID | Purpose (from the campaign definition) |
|---|---|---|
| Thermal Runaway | `thermal_runaway` | one cell heats up steadily; warn at 38 °C, request cooling at 45 °C (expects CRITICAL) |
| Transport Drop | `transport_drop` | the uProtocol message stream is lost; a silent signal is a sensor fault after 2 s |
| Transport Delay | `transport_delay` | delayed delivery; late data must not be treated as current |
| Sensor Stuck | `sensor_stuck` | frozen temperature signal is detected within 10 s and treated as a sensor fault |
| Sensor Stuck, Cell 3 | `sensor_stuck_cell3` | one frozen cell sensor is detected within 10 s and no longer trusted; the pack warning stays armed |
| Out of Range | `out_of_range` | readings outside -40..150 °C are a sensor fault, not an overheat |
| Source Dropout | `source_dropout` | the temperature source goes silent; sensor fault after 2 s |
| Cell Dropout, Cell 2 | `cell_dropout_cell2` | one cell goes silent (sensor fault after 2 s); the pack stays monitored on the other cells |
| Faulty Cell While Another Cell Is Hot | `cell_faulty_while_other_hot` | runaway in one cell while another sensor is faulty; still warn and request cooling |
| Combined Runaway + Lossy Link | `combined_runaway_lossy_link` | runaway while the message stream is degraded; still warn and request cooling |
| Databroker Down | `databroker_down` | KUKSA databroker unavailable; named within 3 s ("KUKSA down") |
| Chip Heartbeat Loss | `chip_heartbeat_loss` | sensor chip hung while data keeps flowing; named within 3 s ("chip silent") |
| Producer Heartbeat Loss | `producer_heartbeat_loss` | the signal producer process is dead; named within 3 s ("sim down") |
| uProtocol Heartbeat Loss | `uprotocol_heartbeat_loss` | uProtocol link heartbeat missing; reported as the link, not as a sensor problem ("uP link lost") |
| Replay Interruption | `replay_interruption` | interrupted signal / source stall; sensor fault after 2 s and recovery when it resumes |

`make campaigns` lists the IDs, `make campaigns-all` runs all of them one after another (about 15 minutes), the dropdown does not.
The definitions are `services/fault-injector/fault_injector/campaigns/*.yaml`.

## Safety Evidence

Two different sources, do not mix them up:

* **Live Evidence Collector** (`localhost:8082`, proxied as `/evidence-api`): everything recorded since the collector started,
  one record per campaign run. Live Monitoring reads the bus events from it.
* **Completed run snapshot** `runs/<RUN_ID>/`: a saved copy. **Safety Evidence shows only this**, so it does not change until you
  save a new one.

The view picks the newest `runs/<YYYYMMDD-HHMMSS>/` that holds all of `evidence.json`, `summary.json` and `evidence-bundle.zip`
(incomplete runs are never candidates; a folder with another name is only a fallback). It extracts the bundle to
`runs/<id>/bundle/`, serves its `report.html` at `/evidence-report/report.html` (metadata: `/evidence-report/meta.json`), checks
the files against `manifest.json` and takes the counts from `evidence.json`. Without a run it says "No completed evidence run
available."; it never shows a stand-in.

Save a snapshot of what the collector holds right now (stack must be up, at least one campaign must have run):

```bash
make evidence-snapshot      # = scripts/evidence_snapshot.sh -> runs/<timestamp>/, verifies the bundle, prints the counts
```

Then press **Rescan** in Safety Evidence (or reload). The report lists every run, so a campaign you ran twice appears twice.
`runs/` is **gitignored** runtime output: do not commit it. (`make final-run` writes the same layout; see below.)

The bundle (`evidence-bundle.zip`, also `curl -O localhost:8082/evidence/bundle.zip`) holds `report.html` (static, inline CSS, no JS),
`manifest.json` (SHA-256 of every file), `events.jsonl`, `safety_case.yaml` and `evidence/<record_id>.json`. Offline check:

```bash
docker compose -f infra/docker-compose.yml run --rm --no-deps -T dev rom-evidence-collector verify /app/runs/<RUN_ID>/evidence-bundle.zip
```

(`make evidence-snapshot` already does this; `/app` is the repository inside the `dev` container.)

## Hardware (AZ3166) and simulator-only

Live mode shows the hybrid topology: **cell 1 = the AZ3166 board, cells 2-4 = simulator**. Hardware pipeline: AZ3166 → MQTT →
MQTT→KUKSA adapter → KUKSA Databroker → VSS uProtocol client → uProtocol/Zenoh → Guardian, and Guardian → MQTT →
the board's OLED. `make hw` starts that variant of the stack (the board must publish to your machine's port 1883; firmware, Wi-Fi
and broker setup: root README, "AZ3166 hardware node"). **The campaign and evidence runs described here ran on
`make guardian` (simulator only), without the board**; the board is not needed to demonstrate them, and a run on simulator data
must not be presented as a hardware measurement.

`make final-run` (Eclipse Ankaios + Podman, `infra/ankaios/`) is a separate orchestration path with its own prerequisites. It did
**not** work on the Podman 3.4.4 of our development machine (CNI network and rootless tmpfs volumes), so the flow above uses
Docker Compose, which produces the same Evidence Collector artifacts.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `make dashboard`: port 5173 in use | `make dashboard-stop`, or stop whatever holds the port (`ss -ltnp \| grep 5173`) |
| `make dashboard`: cannot talk to Docker / permission denied on docker.sock | add your user to the `docker` group and log in again |
| `EACCES` in `node_modules` / `dist` when the container starts | a container that ran as root created files there earlier: `sudo chown -R $USER node_modules dist` in `services/dashboard` (Vite's cache itself lives inside the dashboard container, not in `node_modules/.vite`) |
| red "Evidence Collector unreachable", `curl localhost:8082/health` fails | the stack is not running: `make guardian`; look at `docker compose -f infra/docker-compose.yml --profile tools ps` |
| `localhost:7690/sovd/...` fails | `opensovd` / `dfm` not up (or still building): `make sovd`, `make logs` |
| Run Scenario: `503 Runtime stack is not healthy` | the message names the cause: collector down, Guardian not `MONITORING` yet (wait a few seconds after a campaign), or a campaign still open |
| Run Scenario: "scenario control unavailable" / failed with `could not start` | the dashboard was started without `make dashboard` (e.g. a plain `node` container or `npm run dev` without Docker): it needs the Docker CLI, the socket and `ROM_RUNTIME_REPO` |
| Run Scenario fails at once, `Get "http://localhost/v2/"` in the output | the fault-injector image is missing and Docker tried to pull `localhost/rom/...`: run `make images` |
| Safety Evidence: "No completed evidence run available." | there is no `runs/<id>/` with the three files: `make evidence-snapshot` |
| Safety Evidence shows an old run | it shows the newest saved snapshot, not the live collector: `make evidence-snapshot`, then Rescan |
| builds fail with "no space left on device" | free disk (`df -h /`), `docker builder prune`, remove images you do not need |

## Mock mode

Without `VITE_DASHBOARD_SOURCE=live` (e.g. plain `npm run dev` on a host with Node) the page uses the mock source below: simulated
telemetry, no stack needed, no scenario control. `make dashboard` always starts in live mode.

### Live demo stream (mock)

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

Run it: `make guardian` (or `make hw`) and then `make dashboard`, see [Setup](#setup-for-a-teammate-from-a-fresh-clone). Without
Docker: `VITE_DASHBOARD_SOURCE=live npm run dev` (Run Scenario then also needs the Docker CLI on the host). `EVIDENCE_API_TARGET`
(default `http://localhost:8082`) is where the proxy points, `VITE_EVIDENCE_API_BASE` (default `/evidence-api`) what the browser
calls, `ROM_RUNTIME_REPO` the checkout that runs the stack (default: this repository). See `.env.example`.

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
