# Battery Thermal Guardian: demo dashboard and operator runbook

This is the guide for running, demoing and debugging the whole thing without asking anyone. Everything here was run
against the real stack; commands are copy/paste. Below the runbook (from [Developer reference](#developer-reference-mock-mode-live-data-model))
is the technical description of the dashboard's data model.

## Demo quick start

```
Terminal 1:   make images
              make guardian            # stays attached to the guardian log; leave it running

Terminal 2:   make dashboard           # run when `curl -s localhost:8082/health` shows "guardian_state":"MONITORING"

Browser:      http://localhost:5173/#/live

Run a scenario:    pick "Thermal Runaway"  ->  Run Scenario   (Stop button ends it early)
Refresh evidence:  make evidence-snapshot
Safety report:     http://localhost:5173/#/evidence           (press Rescan after a new snapshot)

Shutdown:     make dashboard-stop
              make down
```

### If Meryem is unavailable (tonight's checklist)

1. `docker ps` works? (if not: Docker is not running, or `sudo usermod -aG docker $USER` and log in again) · `df -h /` has 10 GB+ free?
2. Stack down? `make guardian` (terminal 1). Wait for `curl -s localhost:8082/health` -> `"guardian_state":"MONITORING"`.
3. Dashboard down? `make dashboard` (terminal 2), then open `http://localhost:5173/#/live`.
4. Scenario button does nothing / error: read the red message (`503` = stack not calm, wait 10 s; `409` = one is still running, press Stop).
   Still broken -> `make campaign C=thermal_runaway` in a terminal; the dashboard still shows the reaction.
5. Safety Evidence empty or old: `make evidence-snapshot`, then **Rescan**. Still nothing: open `http://localhost:8082/ui/`.
6. Something unknown: `docker compose -f infra/docker-compose.yml --profile tools ps` and `... logs --tail 50 guardian evidence-collector`.
7. Reset: `make dashboard-stop && make down`, then start again from step 2. This keeps all saved evidence; never delete evidence to make it look green (a stopped scenario is INCONCLUSIVE on purpose).
8. After a `git pull`: `make images` first, otherwise the containers are the old ones.

Everything in detail (architecture, file map, every scenario, verdicts, demo script, troubleshooting): the sections below.

**Contents**
1. [What this project does](#1-what-this-project-does) · 2. [Architecture](#2-architecture) · 3. [Where is what](#3-where-is-what) ·
4. [Prerequisites](#4-prerequisites) · 5. [Quick start (fresh clone)](#5-quick-start-fresh-clone) · 6. [Startup, step by step](#6-startup-step-by-step) ·
7. [Ports](#7-ports-and-urls) · 8. [The dashboard](#8-the-dashboard) · 9. [Run and stop scenarios from the UI](#9-run-and-stop-scenarios-from-the-ui) ·
10. [The scenarios](#10-the-scenarios) · 11. [Scenarios from the command line](#11-scenarios-from-the-command-line) ·
12. [Evidence Collector and verdicts](#12-evidence-collector-and-verdicts) · 13. [Evidence snapshots](#13-evidence-snapshots-safety-evidence) ·
14. [Demo script](#14-demo-script-35-minutes) · 15. [Simulator-only, hardware, Ankaios](#15-simulator-only-hardware-ankaios) ·
16. [Logs](#16-logs-and-inspection) · 17. [Troubleshooting](#17-troubleshooting) · 18. [Stop and clean up](#18-stop-and-clean-up) ·
19. [Command cheat sheet](#19-command-cheat-sheet) · 20. [Emergency checklist](#20-emergency-checklist)

## 1. What this project does

A battery pack has four cell temperature sensors. The safety question: **can the system tell apart a real thermal event, a
sensor fault, and a communication failure, and then react correctly to each, with proof?**

```
hazard  ->  fault injection  ->  detection  ->  mitigation  ->  evidence  ->  verdict
(H1..H11)   (campaign YAML)      (Guardian)     (cooling req.)   (Collector)   (PASS / FAIL / INCONCLUSIVE)
```

* The **Battery Thermal Guardian** supervises the four cells and reports its state and diagnostic fault codes (DTCs).
* A **fault campaign** (a YAML file) injects one specific fault into the running system at a given time and removes it again.
* The **Evidence Collector** records every message of the run, checks it against the **safety case** and stores a verdict.
* The **dashboard** shows the system live, can **start and stop the real campaigns** from the UI (it simulates nothing in the
  browser) and shows the generated evidence report.

## 2. Architecture

```
 (hardware, optional)                                        (simulator-only: the simulator writes all 4 cells)
 AZ3166 --MQTT--> Mosquitto --> adapter --+
                                          +--> KUKSA Databroker --> VSS uProtocol client --uProtocol/Zenoh--> Guardian --+--> DFM --> OpenSOVD
 Simulator (cells 2-4, or 1-4) -----------+                                          |                           |       (fault records, SOVD REST)
                                                                                     |                           +--MQTT--> AZ3166 OLED
                                                          Evidence Collector <-------+-- records every topic, queries OpenSOVD
 Fault injector --HTTP--> Simulator / VSS uProtocol client (fault APIs)        |
 Dashboard (Vite, :5173) --proxy--> Evidence Collector (:8082)  +  runs docker compose for scenarios
```

* **Hybrid / hardware:** cell 1 = the physical AZ3166, cells 2-4 = simulator (`make hw`).
* **Simulator-only:** the simulator provides all four cells (`make guardian`). This is enough for every campaign and for the
  evidence; **the evidence runs recorded so far were simulator-only**, not hardware measurements.
* The Guardian reads cells over uProtocol only, never from KUKSA. Its display command goes to the board over MQTT.
* More detail: root [`README.md`](../../README.md) (service table, settings, heartbeats, Guardian states, hardware node).

## 3. Where is what

| Path | What | Touch it when | Kind |
|---|---|---|---|
| `Makefile` | every command you need (`make help`) | adding a command | source |
| `infra/docker-compose.yml` | the whole stack: services, ports, volumes (`tools` profile = everything but brokers) | changing ports / env | source |
| `services/guardian/` | the Guardian (state machine, per-cell checks, DFM fault events) | changing detection logic | source |
| `services/simulator/` | 4-cell temperature simulator + HTTP fault API (`:8080`) | changing baseline wave | source |
| `services/vss-uprotocol-client/` | KUKSA -> uProtocol publisher + transport-fault API (`:8081`) | transport faults | source |
| `services/adapter/` | MQTT -> KUKSA (AZ3166 data, `make hw` only) | hardware path | source |
| `services/dfm/`, `services/opensovd/` | Diagnostic Fault Manager (Rust) and the SOVD REST server (`:7690`) | fault catalogue | source |
| `services/fault-injector/` | the campaign runner (`rom-fault-injector list / run`) | new campaign logic | source |
| `services/fault-injector/fault_injector/campaigns/*.yaml` | **the campaign definitions** (`make campaigns` lists them) | adding / tuning a scenario | source |
| `services/evidence-collector/` | Collector: records, judges, bundle, report; `safety_case.yaml` = hazards, safety goals | verdict rules | source |
| `services/dashboard/` | this React/Vite app | UI work | source |
| `services/dashboard/src/components/` | UI cards: `BatteryCellsCard`, `GuardianStateCard`, `DataSourcesCard`, `LastMessageCard`, `TemperatureChart`, `RecentEvents`, `SystemFlow`, `ScenarioRunner` (Run/Stop), `SafetyEvidence`, `ViewTabs` | UI changes | source |
| `services/dashboard/src/data/` | `EvidenceCollectorDataSource` + `liveModel` (live data), `scenarioApi` (Run/Stop client), `evidenceReport` (report client), `Mock*` (mock mode) | data logic | source |
| `services/dashboard/vite/scenarios.mjs` | **dev-server API** `/api/scenarios/*`: lists, starts and stops real campaigns | scenario behaviour | source |
| `services/dashboard/vite/evidence-report.mjs` | dev-server API `/evidence-report/*`: serves the newest `runs/<id>/` report | evidence view | source |
| `services/dashboard/vite/*.test.mjs` | tests of the two above and of the UI controller | `npm test` | source |
| `services/dashboard/Dockerfile.dev` | dashboard dev image (Node + Docker CLI) | rarely | source |
| `scripts/dashboard-dev.sh` | `make dashboard`: builds that image, starts the container with the right mounts | rarely | source |
| `scripts/evidence_snapshot.sh` | `make evidence-snapshot`: saves the collector's evidence to `runs/<timestamp>/` | rarely | source |
| `scripts/watch.sh` | `make watch C=<id>`: one campaign live in one terminal + its verdict | rarely | source |
| `scripts/final_run.sh`, `infra/ankaios/` | the Eclipse Ankaios orchestration path (`make final-run`) | Ankaios work | source |
| `MXChip/AZ3166/` | AZ3166 firmware (C, Eclipse ThreadX), its own README | hardware work | source |
| `runs/<RUN_ID>/` | **saved evidence snapshots** (gitignored) | never commit | generated |
| Docker volume `evidence-data` | the collector's database and raw event log | see 12 | generated |

## 4. Prerequisites

For the recommended Docker flow: **Git, Docker Engine with the Compose v2 plugin, GNU make, bash, curl, python3**, a
browser, and about 20 GB of free disk (the first build of the Rust services `dfm` and `opensovd` used about 10 GB here).
`jq` is only needed by `make watch`. **Node.js / npm are not needed on the host:** `make dashboard` runs the dashboard in Docker.
Developed and tested on Linux (Ubuntu). `make dashboard` uses `--network host`, which behaves differently on Docker Desktop
(macOS / Windows); that is untested.

Your user must be able to run Docker **without sudo**. Quick diagnosis:

```bash
docker --version
docker compose version
docker ps            # must work as your user; "permission denied" -> sudo usermod -aG docker $USER, then log in again
df -h /              # keep at least ~10 GB free while building
```

Podman and Ankaios are **not** needed for the local demo (see [15](#15-simulator-only-hardware-ankaios)).

## 5. Quick start (fresh clone)

```bash
git clone https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/RoM.git
cd RoM

make images          # once, minutes: builds the service images
make guardian        # terminal 1: starts the stack, then FOLLOWS the guardian log (Ctrl+C only stops following)
```

```bash
# terminal 2, in the same folder, once `curl -s localhost:8082/health` shows "guardian_state":"MONITORING"
make dashboard       # first start also runs npm ci inside the container
```

Open **<http://localhost:5173/#/live>** (Live Monitoring) and **<http://localhost:5173/#/evidence>** (Safety Evidence).
Stop: `make dashboard-stop` and `make down`.

## 6. Startup, step by step

| # | Do | What it does | Success looks like |
|---|---|---|---|
| 1 | `git clone ... && cd RoM` | gets the code (default branch `main`) | |
| 2 | nothing to configure | all settings have defaults (`.env` is optional; see root README "Settings") | |
| 3 | `make images` | builds `localhost/rom/<service>:dev` for vss-uprotocol-client, guardian, fault-injector, dfm, opensovd, evidence-collector | `docker images \| grep rom/` lists them |
| 4 | `make guardian` | recreates Mosquitto, builds anything missing, starts databroker, simulator, vss-uprotocol-client, guardian, dfm, opensovd, evidence-collector, then follows the guardian log. **The terminal stays attached**: use a second terminal | guardian log shows state `MONITORING` |
| 5 | `curl -s localhost:8082/health` | Collector health | `"ok":true`, `"guardian_state":"MONITORING"`, `"open_run":null` |
| 5b | `curl -s localhost:7690/sovd/v1/apps/battery_guardian/faults \| head -c 300` | OpenSOVD answers | a JSON list of `battery_guardian.*` faults |
| 6 | `make dashboard` | builds the dashboard image, starts container `rom-dashboard-dev`, waits for `/api/scenarios` | prints the two URLs |
| 7 | open `http://localhost:5173/#/live` | Live Monitoring | cells with temperatures, state `MONITORING`, "LIVE MODE" badge |
| 8 | pick a scenario, **Run Scenario** | runs a real campaign ([9](#9-run-and-stop-scenarios-from-the-ui)) | status line `Running: ...`, later `Scenario completed` |
| 9 | `make evidence-snapshot` | saves the evidence ([13](#13-evidence-snapshots-safety-evidence)) | `bundle verified`, `saved runs/<id>` |
| 10 | `make dashboard-stop`, `make down` | stops the dashboard, then the stack | |

After you pull new commits, run `make images` and `make guardian` again so the containers are rebuilt and recreated.

## 7. Ports and URLs

| Port | Service | Purpose | Open it? |
|---|---|---|---|
| **5173** | dashboard (Vite) | Live Monitoring / Safety Evidence / scenario API | **yes** |
| 8082 (127.0.0.1) | Evidence Collector | `/health`, `/evidence`, `/ui/` report, `/events`, bundle | for the report / checks |
| 7690 | OpenSOVD | SOVD REST, `/sovd/v1/apps/battery_guardian/faults` | for checks |
| 1883 | Mosquitto (MQTT) | the AZ3166 publishes here (`MQTT_HOST_PORT` to change) | no |
| 55555 | KUKSA Databroker | gRPC (`make kuksa` is a client shell) | no |
| 8080 (127.0.0.1) | simulator fault API | used by the fault injector | no |
| 8081 (127.0.0.1) | vss-uprotocol-client fault API | transport faults, used by the fault injector | no |
| 8083 (compose network only) | DFM fault API | diagnostic faults (`write_delay`, `drop_write`), used by the fault injector | no |
| 7447 | Zenoh (inside the compose network only) | uProtocol transport between services | no |

Useful URLs: `http://localhost:5173/api/scenarios`, `.../api/scenarios/status`, `.../evidence-api/health` (proxy to the
collector), `.../evidence-report/meta.json`, `http://localhost:8082/ui/`.

## 8. The dashboard

**Live Monitoring** (`#/live`): everything comes from the real stack through the Evidence Collector; it does not recompute
the Guardian, it displays what the Guardian published.

| Card | Shows |
|---|---|
| Battery Cells | the four cells: temperature, status (OK / STALE / STUCK / OUT OF RANGE / NO DATA), source badge `HW` / `SIM`. Click a cell to focus the chart and events on it |
| Pack Max | the hottest **valid** cell (the Guardian's value). A faulty or excluded cell is never used for it |
| Guardian State | `MONITORING`, `WARNING`, `CRITICAL`, `MITIGATING`, `SENSOR_FAULT` and the reason (root README, "Guardian states") |
| Data Sources | heartbeats: AZ3166 chip, simulator, and the chain (uProtocol link, databroker): ALIVE / DOWN / NO HEARTBEAT |
| Last Message | sequence number, time of the last event, real latency (collector receive time minus the cell's source timestamp) |
| Temperature History | one line per cell, last ~2 minutes; a faulty cell breaks its line |
| Recent Events | state changes and `FAULT` / `CLEARED` rows with the real code in the tooltip (e.g. `battery_guardian.cell3.signal_stuck`) |
| System Flow | the pipeline diagram |
| Scenario control | Run / Stop ([9](#9-run-and-stop-scenarios-from-the-ui)) |

Things to know:
* **One bad cell does not mean a global fault.** Example `sensor_stuck_cell3`: before detection (10 s) Cell 3 still shows a
  number; after it Cell 3 is `STUCK`, shows `-- °C`, is left out of Pack Max, `battery_guardian.cell3.signal_stuck` appears in
  Recent Events, and the Guardian stays `MONITORING` because the other cells are healthy. `SENSOR_FAULT` is only for "no cell
  can be trusted" or a lost heartbeat.
* **The `HW` badge on Cell 1 and the header line "Cell 1 AZ3166 · Cells 2-4 simulator" are fixed labels** for the hybrid
  topology. In a simulator-only run (`make guardian`) Cell 1 is also simulated and the "AZ3166" data source shows
  `NO HEARTBEAT`. Do not present a simulator-only run as hardware.

**Safety Evidence** (`#/evidence`) has two modes. **Live** (default): the running Evidence Collector's report, reloaded as
soon as a new verdict arrives, with the PASS / FAIL / INCONCLUSIVE counts and the run being judged right now; a scenario
started from the dropdown shows up here without any command. **Saved run**: the `report.html` of a saved snapshot
(`runs/<id>/`), embedded unchanged, with a checksum badge; see [13](#13-evidence-snapshots-safety-evidence). The two tabs are plain links (`#/live`, `#/evidence`), so a reload or a shared URL stays on the same view.

## 9. Run and stop scenarios from the UI

`Scenario [ dropdown ] [ Run Scenario ] [ Stop ]` in Live Monitoring starts **one real fault campaign**. The dev server runs
exactly what `make campaign C=<id>` runs:

```bash
docker compose -f infra/docker-compose.yml --profile tools run --rm -T fault-injector rom-fault-injector run <campaign_id>
```

**Run**
1. Choose a scenario, click **Run Scenario** (nothing runs on page load).
2. The dropdown and Run lock, the status line says `Running: <scenario>`, Stop becomes enabled. Telemetry keeps updating.
3. The fault injector injects its fault at the scripted time, the Guardian reacts, the injector clears the fault again.
4. The status ends as `Scenario completed (exit code 0)` or `Scenario failed (exit code N)` + the tail of its output.
   The exit code only says the injector finished. **The verdict is the evidence record**, not this status.

**Stop**
* Enabled only while a scenario runs; click once (`Stopping: ...`), then `Scenario stopped: <scenario>`, controls unlock.
* It stops **only that campaign's container**. Guardian, Collector, KUKSA, simulator and the rest keep running; it never
  runs `make down`.
* It first sends SIGINT to that container, so the fault injector **clears the faults it injected** and logs
  `campaign_end: interrupted`. Only if the container is still alive after 5 s is that same container force-killed and
  removed. Guardian and telemetry recover on their own (Cell 3 goes valid again, state returns to `MONITORING`).
* A stopped campaign is **never PASS**. The Collector records it as **INCONCLUSIVE ("campaign interrupted")**. That is
  intended behavior, not an error.

**Rules enforced by the server** (`vite/scenarios.mjs`, tested in `vite/scenarios.test.mjs`): the browser sends an id, never a
command; only ids of bundled campaign YAMLs are accepted (anything else: `400`); one campaign at a time (`409` for a second
run, a second stop, or a run while stopping); `503` if the stack is unhealthy (collector not answering, Guardian not
`MONITORING`, or a campaign still open in the collector). Wait a few seconds after a scenario before starting the next.

API: `GET /api/scenarios`, `GET /api/scenarios/status` (`idle`, `running`, `stopping`, `completed`, `failed`, `stopped`),
`POST /api/scenarios/run {"scenario":"<id>"}`, `POST /api/scenarios/stop` (no body). It exists only on the dev server that
`make dashboard` starts, not in a static build. Containers started by the UI are named `rom-dashboard-campaign-<id>-<random>`
and labelled `rom.dashboard.campaign`.

## 10. The scenarios

The dropdown lists the YAML files in `services/fault-injector/fault_injector/campaigns/` (a new YAML appears automatically, with
a label made from its name). There were 22 when this was written; `make campaigns` is the authority.
"Expected" is `expected_state` / `expected_faults` of the YAML. Times are seconds into the campaign; each fault starts at
10 s unless noted.

| UI label | Canonical ID | Injected fault | Expected |
|---|---|---|---|
| Thermal Runaway | `thermal_runaway` | cell 1 heats +0.7 °C/s for 50 s | CRITICAL: warning at 38 °C, cooling requested at 45 °C (`over_temp_warning`, `over_temp_critical`, `cell_imbalance`) |
| Transport Drop | `transport_drop` | every uProtocol cell message is lost for 8 s (KUKSA still fresh) | SENSOR_FAULT `signal_stale` within 4 s |
| Transport Delay | `transport_delay` | messages arrive 2.5 s late for 10 s | SENSOR_FAULT `signal_stale` (late data is not current) (tolerated: `link_integrity` when the delay ends) |
| Sensor Stuck | `sensor_stuck` | all four cell sensors frozen for 20 s | SENSOR_FAULT, stuck detected within 10 s |
| Sensor Stuck, Cell 3 | `sensor_stuck_cell3` | cell 3 frozen for 20 s | MONITORING; `cell3.signal_stuck`, cell 3 excluded |
| Out of Range | `out_of_range` | cell 1 reads 200 °C for 10 s | MONITORING; `cell1.out_of_range`, no false overheat |
| Source Dropout | `source_dropout` | simulator stops writing all cells for 8 s | SENSOR_FAULT `signal_stale` after 2 s |
| Cell Dropout, Cell 2 | `cell_dropout_cell2` | cell 2 stops for 8 s | MONITORING; `cell2.signal_stale` |
| Faulty Cell While Another Cell Is Hot | `cell_faulty_while_other_hot` | cell 3 stuck (from 5 s) while cell 1 overheats | CRITICAL with `cell3.signal_stuck`; warning not disarmed |
| Combined Runaway + Lossy Link | `combined_runaway_lossy_link` | overheat while messages are duplicated and delayed 600 ms | CRITICAL; link noise does not hide it |
| Databroker Down | `databroker_down` | the client reports KUKSA as down for 8 s | SENSOR_FAULT "KUKSA down" (`databroker_down`) |
| Chip Heartbeat Loss | `chip_heartbeat_loss` | the chip heartbeat stops for 8 s, data keeps flowing | SENSOR_FAULT "chip silent" (`chip_silent`) |
| Producer Heartbeat Loss | `producer_heartbeat_loss` | the simulator heartbeat stops for 8 s | SENSOR_FAULT "sim down" (`simulator_down`) |
| uProtocol Heartbeat Loss | `uprotocol_heartbeat_loss` | uProtocol heartbeats dropped for 8 s, cells still arrive | SENSOR_FAULT "uP link lost" (`uprotocol_lost`) |
| Replay Interruption | `replay_interruption` | the source stalls for 8 s, then resumes | SENSOR_FAULT `signal_stale`; recovers on resume |
| Transport Duplicate | `transport_duplicate` | every cell message arrives twice for 10 s | MONITORING; copies dropped, `link_integrity` named within 3 s |
| Transport Reorder | `transport_reorder` | cell messages swap places in pairs for 10 s | MONITORING; old value not used, `link_integrity` |
| Sensor Spike, Cell 2 | `sensor_spike_cell2` | cell 2 drops 15 °C for two samples at 10 s | MONITORING; `cell2.rate_implausible` within 1.5 s |
| Reorder During Runaway | `reorder_during_runaway` | overheat while cell messages are reordered | CRITICAL; a late cooler value never lowers the state, link named |
| Heartbeat Duplicate / Reorder | `heartbeat_duplicate_reorder` | heartbeats duplicated, then reordered; data fine | MONITORING; harmless, no fault expected |
| DFM Write Delay | `dfm_write_delay` | cell 3 frozen while every DFM write is held 3 s (needs the DFM fault API) | MONITORING; `cell3.signal_stuck` reaches OpenSOVD ~3 s late, still within the 5 s limit; the record shows the diagnostic latency |
| OpenSOVD Partial Visibility | `opensovd_partial_visibility` | cell 1 out of range + cell 3 stuck, but the DFM never writes the cell 3 DTC (needs the DFM fault API) | **FAIL on purpose** (`expected_verdict: FAIL`): the Collector must notice that OpenSOVD shows only half of what the Guardian detected |

**Expected FAIL:** `opensovd_partial_visibility` breaks the evidence chain deliberately. Its record says `FAIL` and carries
`as_expected: true`: that FAIL is the Collector working, not a problem. All other campaigns expect PASS.

Why a campaign "expects" MONITORING: the Guardian must react to the right thing only. A single bad cell or noisy link must be
named without declaring the whole pack faulty.

## 11. Scenarios from the command line

Needs the stack from `make guardian` running. Wait for `MONITORING` first: the UI refuses to start otherwise (`503`), the CLI does
not check, and a campaign whose first fault goes in while the Guardian is not calm is judged INCONCLUSIVE.

```bash
make campaigns                          # list the ids
make campaign C=thermal_runaway         # run one (blocks until it ends, about 30-75 s)
make campaign C=transport_drop
make watch C=thermal_runaway            # same, but live in one terminal (simulator, guardian, DFM, SOVD) + the verdict; needs jq
docker compose -f infra/docker-compose.yml --profile tools run --rm -T fault-injector \
  rom-fault-injector run thermal_runaway --dry-run      # prints the plan, injects nothing
make campaigns-all                      # EVERY campaign one after another, roughly 20-25 minutes, then prints the verdicts
```

**Never run two campaigns at once** (the Collector marks overlapping runs INCONCLUSIVE). Do not run `make campaigns-all`
during a presentation. The UI and the CLI use the same stack, so do not start a CLI campaign while the UI shows `Running`.
`make watch` starts and rebuilds the stack itself if it is not up.

## 12. Evidence Collector and verdicts

The Collector subscribes to every RoM uProtocol topic, opens a "run" at the injector's `campaign_start`, follows the
Guardian's states and fault events, queries OpenSOVD for the expected DTCs, and at `campaign_end` stores one **evidence
record** (JSON) with a verdict and reasons. Rules in full: `services/evidence-collector/README.md`.

| Verdict | Meaning (as implemented) |
|---|---|
| **PASS** | the campaign ran to its end and no rule was violated: expected DTCs raised in time and confirmed in OpenSOVD, expected state reached (or kept), no false alarm |
| **FAIL** | a safety expectation was not met: an expected DTC missing or late (`max_detect_ms`), expected state not reached, a state that had to be kept was left, CRITICAL without cooling request, an unexpected DTC, expected DTC absent from OpenSOVD. FAIL wins over INCONCLUSIVE. A campaign may declare `expected_verdict: FAIL`; the record's `as_expected` says whether the verdict was the one intended |
| **INCONCLUSIVE** | no valid verdict is possible: the campaign was **interrupted** or aborted, had no start / end, injected nothing, the Guardian was not `MONITORING` when the first fault went in, another campaign overlapped, or the campaign is not in the safety case |

Endpoints (`http://localhost:8082`): `/health`, `/evidence?limit=&run_id=` (newest first), `/evidence/summary`,
`/evidence/{record_id}`, `/evidence/consistency`, `/evidence/bundle.zip?run_id=&since=`, `/events?since=&limit=`, `/ui/`
(HTML report). `make evidence` prints the summary and the latest verdicts; `make evidence-bundle [RUN=<run_id>]` downloads a zip.

**The live Collector accumulates everything you did in the current setup**: every test, every rerun, every stopped run.
Its data lives in the Docker volume `evidence-data` and **survives `make down`**. So:
* it can hold more records than there are scenarios (a rerun is a new record; "unique campaigns" and "records" differ);
* it can contain INCONCLUSIVE records from interrupted runs. That is correct and intended;
* never edit or delete evidence to make a report look all-PASS. If you need a report of specific runs, run exactly those
  campaigns, then save the snapshot, or download a scoped bundle (`/evidence/bundle.zip?run_id=<id>` or `?since=<epoch ms>`).

## 13. Evidence snapshots (Safety Evidence)

```bash
make evidence-snapshot       # needs the stack up and at least one finished campaign
```

creates the following. Nothing is generated by us: it fetches the records, summary and bundle from the Collector and extracts the zip.

```
runs/<YYYYMMDD-HHMMSS>/
  evidence.json            all evidence records of the live Collector at that moment
  summary.json             pass rate and coverage per safety goal
  evidence-bundle.zip      the Collector's bundle
  bundle/                  the zip, extracted
    report.html            the report (static, inline CSS, no JavaScript)
    manifest.json          SHA-256 of every file
    events.jsonl           every recorded bus message
    safety_case.yaml       hazards and safety goals
    evidence/<record_id>.json
```

It then verifies the bundle (`bundle verified`) and prints the counts. `runs/` is **gitignored**; do not commit snapshots.
Each snapshot has its own timestamp folder and is never overwritten, so older ones stay as they were.

**Refresh Safety Evidence:** 1) finish your scenarios, 2) `make evidence-snapshot`, 3) press **Rescan** in Safety Evidence (or
reload). The view picks the **newest** `runs/<timestamp>/` that has `evidence.json`, `summary.json` and `evidence-bundle.zip`
(incomplete folders are ignored; a folder with another name is only a fallback). With none it shows "No completed evidence
run available." If it shows an old run you simply have not saved a newer one. `make final-run` writes the same layout.

Verify any bundle offline (inside the project's own container, nothing to install):

```bash
docker compose -f infra/docker-compose.yml run --rm --no-deps -T dev \
  rom-evidence-collector verify /app/runs/<RUN_ID>/evidence-bundle.zip      # last line: "bundle verified"
```

It checks the SHA-256 manifest and judges every record again from its recorded events.

## 14. Demo script (3-5 minutes)

Before: stack healthy (`curl -s localhost:8082/health`), `make dashboard` up, a snapshot saved as backup
(`make evidence-snapshot`), browser on `#/live`.

1. **Live Monitoring.** "Four cells, Pack Max is the hottest *valid* cell, the Guardian state is `MONITORING`." Say honestly
   whether Cell 1 is the board or simulated (see [8](#8-the-dashboard)).
2. **Pick Thermal Runaway, Run Scenario.** The controls lock; telemetry keeps moving. Roughly 25-30 s after the start cell 1 passes
   38 °C: `WARNING`, then at 45 °C `CRITICAL` and the cooling request (`MITIGATING`); the exact back-and-forth depends on the
   run. Show **Recent Events** (real DTC codes in the tooltips). It ends with `Scenario completed`.
3. **A sensor fault instead of a heat event.** Run `sensor_stuck_cell3`: after ~10 s Cell 3 turns `STUCK`, shows `-- °C`, drops out
   of Pack Max, and the Guardian *stays* `MONITORING`. "A bad sensor is not a thermal event."
4. **Optional, Stop.** Start any short scenario (`transport_drop`), click **Stop**: it ends as `stopped`, the stack carries on.
   Say: the evidence will show INCONCLUSIVE ("interrupted"), not PASS, on purpose.
5. **Safety Evidence.** Open `#/evidence` (**Live**): the scenarios you just ran are already there with their verdicts.
   For the checksum badge: `make evidence-snapshot`, then **Saved run** (Rescan): run id, counts, the report with the
   timeline and verdicts per campaign, the checksum badge. The numbers are what the Collector recorded.

**If live scenario control fails:** the monitoring view still works; run `make campaign C=thermal_runaway` in a terminal
(or `make watch C=thermal_runaway`) and watch the dashboard; or show the saved snapshot in Safety Evidence; or open
`http://localhost:8082/ui/`. Last resort: the saved `runs/<id>/bundle/report.html` opens in any browser.

## 15. Simulator-only, hardware, Ankaios

**Simulator-only (no board needed, the normal demo):** `make guardian` + `make dashboard` as in [5](#5-quick-start-fresh-clone).
The simulator writes all four cells (`SIM_CELLS` defaults to `1,2,3,4`), the Guardian requires only the `uprotocol` and
`databroker` heartbeats. All campaigns and the evidence work in this mode. The only dashboard difference: the fixed `HW`
badge / header text (see [8](#8-the-dashboard)) while the AZ3166 data source reads `NO HEARTBEAT`.

**Hybrid / hardware (optional):** cell 1 = the AZ3166, cells 2-4 = simulator.
`AZ3166 -> MQTT (Mosquitto, host port 1883) -> adapter -> KUKSA -> VSS uProtocol client -> uProtocol/Zenoh -> Guardian`, and
`Guardian -> MQTT rom/actuator/display/cmd -> AZ3166 OLED`.

```bash
make hw        # simulator on cells 2-4; the Guardian also requires the adapter and chip heartbeats; follows adapter + guardian logs
```

The board must publish to this machine's port 1883 and be flashed with the firmware; Wi-Fi settings, broker setup and flashing
are in the root `README.md` ("AZ3166 hardware node") and `MXChip/AZ3166/README.md`. With `make hw` and no board the Guardian
reports the missing chip / adapter heartbeats as a fault by design. The recorded evidence is **not** a hardware measurement.

**Ankaios (`make final-run`):** the repo also contains an orchestration path under Eclipse Ankaios with Podman
(`scripts/final_run.sh`, `infra/ankaios/`, its own `README.md`). It needs a compatible Podman / Ankaios environment and is **not**
part of the normal laptop demo; use Docker Compose as described here.

## 16. Logs and inspection

Service names: `databroker`, `mosquitto`, `simulator`, `vss-uprotocol-client`, `guardian`, `dfm`, `opensovd`,
`evidence-collector` (and `adapter` for `make hw`). Set once: `DC="docker compose -f infra/docker-compose.yml --profile tools"`.

```bash
$DC ps                                   # what runs
$DC logs -f guardian                     # state transitions, fault events  (what the Guardian decided)
$DC logs -f simulator                    # temperatures, injected faults    (what the fault injector did)
$DC logs -f vss-uprotocol-client         # publishing, transport faults, heartbeats
$DC logs -f evidence-collector           # runs opened / closed, verdicts
$DC logs -f dfm opensovd                 # diagnostic fault records
make logs                                # several of these at once
docker ps --filter label=rom.dashboard.campaign        # campaign containers started from the UI (normally none)
curl -s localhost:8082/health            # collector + Guardian state + open run
curl -s localhost:5173/api/scenarios/status
make dfm-faults    /   make sovd-faults  # fault records via the DFM / via OpenSOVD
docker logs --tail 50 rom-dashboard-dev  # dashboard dev server (also: scripts/dashboard-dev.sh logs)
```

## 17. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `make dashboard`: port 5173 in use | an old dashboard or another Vite | `make dashboard-stop`; else find it: `ss -ltnp \| grep 5173` |
| `make dashboard`: cannot talk to Docker / permission denied | user not in the `docker` group | `sudo usermod -aG docker $USER`, log in again, check `docker ps` |
| Dropdown visible but Run fails / "scenario control unavailable" / `could not start` | dashboard not started with `make dashboard` (no Docker CLI / socket / `ROM_RUNTIME_REPO`) | stop it, run `make dashboard` from the clone that runs the stack |
| Run: `503 Runtime stack is not healthy` | collector down, Guardian not `MONITORING` yet, or a campaign still open | read the message; `curl -s localhost:8082/health`; wait ~10 s after a scenario; `make guardian` if the stack is down |
| Run / Stop: `409` | a scenario is running or stopping (maybe from another browser tab or the CLI) | wait for it, or press Stop |
| red "Evidence Collector unreachable"; `curl localhost:8082/health` fails | stack not running or still building | `make guardian`; `$DC ps` |
| `localhost:7690/sovd/...` not answering | `opensovd` / `dfm` not up yet (the Rust images are slow to build) | `make sovd`, `$DC logs opensovd` |
| Run fails at once with `Get "http://localhost/v2/"` | the fault-injector image is missing and Docker tries to pull `localhost/rom/...` | `make images` |
| New scenarios missing in the dropdown / old behaviour after `git pull` | images and containers are from before the pull | `make images`, then `make guardian` (and `make dashboard`) |
| "No completed evidence run available." | no `runs/<id>/` with the three files | `make evidence-snapshot` |
| Safety Evidence shows an old run | you are on **Saved run**, the newest saved snapshot | switch to **Live**, or `make evidence-snapshot`, then Rescan |
| A stopped scenario shows INCONCLUSIVE | intended: an interrupted campaign cannot be PASS | nothing to fix; do not delete it |
| Live Collector has more records / INCONCLUSIVE ones | it keeps all earlier tests in volume `evidence-data` | nothing to fix; use snapshots, see [12](#12-evidence-collector-and-verdicts) |
| `EACCES` in `node_modules` or `dist` | a container that ran as root created files in the clone | `sudo chown -R $USER services/dashboard/node_modules services/dashboard/dist` |
| `make` stops: port 1883 in use | a host Mosquitto holds it | `sudo systemctl stop mosquitto`, or `MQTT_HOST_PORT=1884 make guardian` (simulator only) |
| build: "no space left on device" | disk full (the Rust builds are large) | `df -h /`; free space; `docker builder prune` only if you know what else is cached |
| `ghcr.io/eclipse-kuksa/kuksa-databroker` pull denied | registry access on that machine | `docker login ghcr.io` with an account that has access; or `docker pull` on a machine that can and `docker save \| docker load` |
| `make hw`: Guardian shows chip / adapter missing | no board publishing on port 1883 | power the board / check Wi-Fi, or use `make guardian` |

## 18. Stop and clean up

```bash
make dashboard-stop      # stops and removes only the dashboard container rom-dashboard-dev
make down                # stops and removes the whole compose stack; volumes (evidence-data, ...) are kept
docker ps                # check what is left
docker ps -a --filter label=rom.dashboard.campaign      # leftover campaign containers: normally none
```

Do not `docker kill` / `docker rm` containers you did not start (other teams use the same machine); remove a stuck campaign
container only by its exact name from the command above.

## 19. Command cheat sheet

| Command | Purpose | Blocks the terminal | Needs the board |
|---|---|---|---|
| `make help` | list all targets | no | no |
| `make images` | build the service images | until built | no |
| `make guardian` | start the stack, follow the guardian log | **yes** (use a 2nd terminal) | no |
| `make hw` | stack in hybrid mode, follow adapter + guardian logs | **yes** | **yes** |
| `make dashboard` | dashboard on :5173 (Docker) | no (returns when up) | no |
| `make dashboard-stop` | stop the dashboard | no | no |
| `make campaigns` | list campaign ids | no | no |
| `make campaign C=<id>` | run one campaign from the CLI | until it ends | no |
| `make watch C=<id>` | one campaign, live view + verdict | until it ends | no |
| `make campaigns-all` | all campaigns (20+ min) | **yes** | no |
| `make evidence` | print verdict summary | no | no |
| `make evidence-bundle` | download `bundle.zip` into the current folder | no | no |
| `make evidence-snapshot` | save `runs/<timestamp>/` | no | no |
| `make sovd-faults` / `make dfm-faults` | fault records via SOVD / DFM | no | no |
| `make logs` | follow several service logs | **yes** | no |
| `make down` | stop the stack | no | no |
| `make final-run` | Ankaios + Podman orchestrated run | until done | no |
| `make test` | project tests (Python, in the dev image) | until done | no |

## 20. Emergency checklist

1. `docker ps` (works?) and `df -h /` (disk?)
2. `make guardian` in terminal 1; wait until `curl -s localhost:8082/health` says `"guardian_state":"MONITORING"`
3. `make dashboard` in terminal 2
4. open `http://localhost:5173/#/live`
5. run one scenario from the dropdown (**Run Scenario**)
6. if the scenario UI fails: `make campaign C=thermal_runaway`
7. open `http://localhost:5173/#/evidence`
8. if the report is stale: `make evidence-snapshot`, then Rescan
9. when done: `make dashboard-stop && make down`
10. anything odd: section [17](#17-troubleshooting); the Guardian/collector logs ([16](#16-logs-and-inspection)) tell what happened

---

# Developer reference (mock mode, live data model)

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

Run it: `make guardian` (or `make hw`) and then `make dashboard`, see [Quick start](#5-quick-start-fresh-clone). Without
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
