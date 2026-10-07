<!-- Made with Claude (Claude Code, Anthropic) -->
# RoM — Battery Thermal Guardian

[![CI](https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/RoM/actions/workflows/ci.yml/badge.svg)](https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/RoM/actions/workflows/ci.yml)

Sensor / simulator → KUKSA Databroker → VSS uProtocol Client → (uProtocol over Zenoh) → Guardian → display,
and Guardian → (uProtocol) → DFM fault records (Eclipse OpenSOVD fault-lib).
The guardian never reads the databroker directly. Everything runs in Docker; you only need `docker compose` and `make`.

## Repository layout

Every component is its own pip package; services that run under Ankaios have their own image
(`services/<name>/Dockerfile` → `localhost/rom/<name>:dev`, no bind mounts, env-only config).

| Path | Package | Image | What |
|---|---|---|---|
| `libs/rom-common` | `rom_common` | – | contracts, config, JSON logging, KUKSA / MQTT helpers |
| `libs/rom-uprotocol` | `rom_uprotocol` | – | uProtocol library: Zenoh transport, URIs, publisher, subscriber |
| `services/vss-uprotocol-client` | `vss_uprotocol_client` | ✅ | KUKSA Databroker → uProtocol |
| `services/guardian` | `guardian` | ✅ | Battery Thermal Guardian (4 cells over uProtocol in, DFM fault events out over uProtocol; display command over MQTT) |
| `services/simulator` | `simulator` | dev image | 4-cell sine-wave temperature into KUKSA, with HTTP fault injection |
| `services/adapter` | `adapter` | dev image (`make hw`) | MQTT → KUKSA |
| `services/fault-injector` | `fault_injector` | ✅ | Fault Campaign Runner: YAML campaigns → simulator / publisher fault APIs |
| `services/dfm` | `rom_dfm` (Rust) | ✅ | Diagnostic Fault Manager: fault-lib `dfm_bin` + guardian fault events (uProtocol) → fault records |
| `services/opensovd` | `rom-opensovd` (Rust) | ✅ | Eclipse OpenSOVD server: SOVD entities + DFM faults (`/sovd/v1/apps/battery_guardian/faults`) |
| `services/evidence-collector` | `evidence_collector` | ✅ | Evidence Collector: every uProtocol topic + OpenSOVD → PASS / FAIL / INCONCLUSIVE per campaign run, safety case, evidence bundle |
| `MXChip/AZ3166` | – (C firmware) | – | AZ3166 board on Eclipse ThreadX: sensor telemetry over MQTT, guardian state on its OLED |

## Quick start

```bash
make guardian                    # databroker + simulator + vss-uprotocol-client + guardian + dfm + opensovd, shows guardian logs
SIM_PERIOD_S=30 make guardian    # faster wave (30 s instead of 120 s)
make down                        # stop everything
```

`Ctrl+C` only stops following the logs; the stack keeps running until `make down`.

The compose mosquitto needs host port 1883 (the AZ3166 board publishes there). If a host broker already holds it,
`make` stops with a hint: `sudo systemctl stop mosquitto`, or `MQTT_HOST_PORT=1884 make guardian` (simulator only).

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs on every PR: `make test`, the DFM build with
`cargo test` and a fixture check against a real `dfm_bin`, all service images, and the AZ3166 ThreadX firmware.

## Dashboard (gui branch)

`make guardian` in one terminal, `make dashboard` in another, then <http://localhost:5173/#/live> (Live Monitoring with a
**Run Scenario** control that starts a real fault campaign) and <http://localhost:5173/#/evidence> (Safety Evidence: the
Evidence Collector's report of a saved run, `make evidence-snapshot`). No Node.js needed, only Docker. Setup, the list of
scenarios, evidence snapshots and troubleshooting: [`services/dashboard/README.md`](services/dashboard/README.md).

## All commands

| Command | What it does |
|---|---|
| `make help` | list all commands |
| `make mqtt-restart` | recreate mosquitto (fresh broker, host port 1883 re-published). `up`, `guardian`, `adapter` and `hw` do this first, so the broker is always reachable from the board and your laptop; it fails loudly if something else holds port 1883 |
| `make up` | start databroker + mosquitto in the background |
| `make guardian` | databroker + simulator + vss-uprotocol-client + guardian + dfm + opensovd, follow guardian logs |
| `make dfm-faults` | fault records in the running DFM as JSON |
| `make dfm-fixtures` | regenerate the DFM test fixtures for OpenSOVD (`services/dfm/fixtures`) |
| `make images` | build all service images `localhost/rom/<service>:dev` |
| `make hw` | hardware run: AZ3166 (= cell 1) → mosquitto → adapter → databroker → vss-uprotocol-client → guardian; the simulator fills cells 2-4 (`SIM_CELLS=2,3,4`); the guardian also expects the `adapter` and `chip` heartbeats. Follows adapter + guardian logs |
| `make adapter` | MQTT → KUKSA adapter in the foreground |
| `make sovd` | DFM + Eclipse OpenSOVD server in the background (SOVD REST on `localhost:7690/sovd`) |
| `make sovd-faults` | guardian faults from the DFM over SOVD |
| `make sim` | sine-wave simulator into KUKSA (foreground) |
| `make campaigns` | list the bundled fault campaigns |
| `make campaign C=thermal_runaway` | run a fault campaign against the running stack (`make guardian` first) |
| `make sim-up` | databroker + simulator in the background |
| `make kuksa` | interactive kuksa-client shell (`getValue Vehicle.Powertrain.TractionBattery.Temperature.Max`) |
| `make logs` | follow databroker, mosquitto and simulator logs |
| `make test` | run all tests (`libs/`, `services/`) in the dev image |
| `make shell` | bash inside the Python image |
| `make dashboard` / `make dashboard-stop` | dashboard dev server in Docker on `localhost:5173` (needs the stack from `make guardian`); stop it |
| `make evidence-snapshot` | save the collector's evidence as `runs/<timestamp>/` (gitignored) for the dashboard's Safety Evidence view, bundle verified |
| `make down` | stop everything |

## Without Docker (local Python)

```bash
make venv && . .venv/bin/activate     # every package installed editable (requirements.txt)

rom-guardian                 # offline test scenario, no broker needed
rom-simulator                # sine wave into KUKSA (needs the databroker: make up)
vss-uprotocol-client         # KUKSA -> uProtocol over Zenoh
rom-guardian --uprotocol     # live, reads uProtocol
rom-up-monitor               # print every uProtocol message on the battery topic
pytest -q
```

## Settings (env variables)

| Variable | Default | Used by |
|---|---|---|
| `KUKSA_HOST` / `KUKSA_PORT` | `127.0.0.1` / `55555` | all |
| `MQTT_HOST` / `MQTT_PORT` | `localhost` / `1883` | all |
| `MQTT_HOST_PORT` | `1883` | compose mosquitto host port (`make`) |
| `SIM_HZ`, `SIM_PERIOD_S`, `SIM_MIN_C`, `SIM_MAX_C`, `SIM_SEED` | `2`, `120`, `30`, `69`, `0` | simulator |
| `SIM_API_HOST` / `SIM_API_PORT` | `127.0.0.1` / `8080` | simulator fault API (`0` = off) |
| `FAULT_API_HOST` / `FAULT_API_PORT` | `127.0.0.1` / unset (off) | vss-uprotocol-client transport-fault API |
| `SIMULATOR_URL` / `PUBLISHER_URL` | `http://127.0.0.1:8080` / – | fault-injector |
| `UP_CAMPAIGN_EVENTS` | unset | fault-injector: `1` = campaign events over uProtocol for the evidence collector |
| `SOVD_URL`, `EVIDENCE_*` | see [`services/evidence-collector`](services/evidence-collector/README.md) | evidence-collector |
| `WARN_C`, `CRIT_C` | `38`, `45` | guardian |
| `STALE_MS`, `STUCK_S`, `MIN_PLAUSIBLE_C`, `MAX_PLAUSIBLE_C` | `2000`, `10`, `-40`, `150` | guardian (`STALE_MS` is also the uProtocol TTL) |
| `VSS_SOURCE_PATH` | `Vehicle.Powertrain.TractionBattery.Temperature.Max` | vss-uprotocol-client |
| `SIM_CELLS` | `1,2,3,4` | simulator (`2,3,4` when the real board is cell 1) |
| `SIM_COOLING`, `SIM_COOLING_C_PER_S`, `SIM_COOLING_RELAX_C_PER_S` | unset (compose: `1`), `3`, `0.2` | simulator as the cooling actuator: cells cool while the guardian is `MITIGATING` ([simulator](services/simulator/README.md#cooling-the-simulator-as-the-cooling-actuator)) |
| `ADAPTER_CELL` | `1` | adapter: which cell the board is |
| `HEARTBEAT_PERIOD_MS`, `HEARTBEAT_STALE_MS` | `500`, `1500` | client, adapter, simulator / guardian |
| `CHIP_TIMEOUT_MS` | `1500` | adapter: no telemetry for this long reports the chip heartbeat as 0 |
| `REQUIRED_HEARTBEATS` | `uprotocol,databroker` | guardian (`make hw`: `+adapter,chip`) |
| `UP_AUTHORITY`, `UP_TRANSPORT`, `ZENOH_MODE`, `ZENOH_CONNECT`, `ZENOH_LISTEN` | `rom-vehicle`, `zenoh`, `peer`, –, – | vss-uprotocol-client, guardian |

## Fault injection

The simulator writes **four battery cells** (`Vehicle.Powertrain.TractionBattery.Cells.Cell1..4.Temperature`, a custom
overlay in [`infra/vss/rom_overlay.json`](infra/vss/rom_overlay.json) that the databroker loads next to the standard VSS)
and `Temperature.Max` = the hottest cell written. The guardian watches **every cell** (uProtocol `…/1001/1/8002`)
and reports DFM faults per cell on `…/1002/1/8003`; see [`docs/diagnostics-4-cells.md`](docs/diagnostics-4-cells.md).

Faults are injected into the running stack over HTTP, by hand or by the Fault Campaign Runner:

```bash
make guardian                                   # stack up; fault APIs on 127.0.0.1:8080 (simulator) and :8081 (publisher)
make campaigns                                  # bundled campaigns
make campaign C=thermal_runaway                 # run one; watch the guardian state change in the guardian logs
make evidence                                   # verdict per run (report: http://localhost:8082/ui/)
curl -XPOST localhost:8080/faults -d '{"type":"stuck","cell":1}'      # or by hand
curl -XDELETE localhost:8080/faults
```

| Where | Faults | Docs |
|---|---|---|
| simulator | signal: stuck · spike · drift · out_of_range, source: dropout · replay_interruption | [`services/simulator`](services/simulator/README.md) |
| vss-uprotocol-client | transport: drop · reorder · duplicate · delay | [`services/vss-uprotocol-client`](services/vss-uprotocol-client/README.md) |
| fault-injector | YAML campaigns: hazard, safety goal, faults, expected state, `max_detect_ms`, seed | [`services/fault-injector`](services/fault-injector/README.md) |

The control APIs have **no authentication**; compose publishes them on `127.0.0.1` only. Do not expose them on a
shared network.

## Heartbeats: which part of the chain broke

```
board --MQTT--> adapter ----(Cell1 + Max, Heartbeat.Adapter, Heartbeat.Chip)--+
simulator ------(Cells, Max, Heartbeat.Simulator, Heartbeat.Chip)-------------+--> KUKSA
                                                                                  |
  vss-uprotocol-client: cells (8002), Max (8001); heartbeats (8004): the producers' counters, plus its own
  "uprotocol" beat and "databroker" ok/down from a probe of KUKSA               |
                                                                                  v
                                                              guardian (uProtocol only) --> display over MQTT
```

| Heartbeat | From | Guardian says when it is gone | DFM code (`battery_guardian.…`) |
|---|---|---|---|
| `uprotocol` | vss-uprotocol-client | `uP link lost` | `uprotocol_lost` |
| `databroker` | the client's probe of KUKSA | `KUKSA down` | `databroker_down` |
| `adapter` / `simulator` | the producer | `adapter down` / `sim down` | `adapter_down` / `simulator_down` |
| `chip` | the adapter: a counter while the board's telemetry arrives, `0` when it stops (or the simulator) | `chip silent` | `chip_silent` |

All of these are `SENSOR_FAULT` with a short reason (the display contract and the firmware are unchanged). When several are
gone the one closest to the guardian is blamed first (uprotocol > databroker > producer > chip) and gets the only new DFM
code. Details: [`services/guardian`](services/guardian/README.md), [`services/adapter`](services/adapter/README.md).

**Real board:** the AZ3166 is **cell 1** (`ADAPTER_CELL`). `make hw` runs the simulator for cells 2-4, so the pack still
has four cells. No firmware change was needed: the adapter derives the chip heartbeat from the board's telemetry and its
`rom/sensor/battery/status` (Last Will). A heartbeat from the firmware itself is a possible follow-up.

## Guardian states

`CLEAR` (no data yet) → `MONITORING` → `WARNING` (≥ `WARN_C`) → `CRITICAL` (≥ `CRIT_C`) → `MITIGATING`
(→ `CRITICAL` "mitigation failed" if still hot after 5 s). Every cell is checked on its own (stale 2 s, stuck 10 s, out of
range −40…150 °C); a bad cell raises its own DFM code and is left out, so a faulty sensor never disarms the warning.
`SENSOR_FAULT` when no cell can be trusted, or when a heartbeat is lost (see above).

## AZ3166 hardware node: sensor telemetry over MQTT

This section covers the working hardware node built on the **MXChip AZ3166 IoT DevKit**, running **Eclipse ThreadX / NetX Duo**. The board reads its onboard sensors, shows them on its OLED screen, and publishes them to an MQTT broker so any laptop on the hackathon network can pull live readings without touching the hardware.

Code lives under [`MXChip/AZ3166`](MXChip/AZ3166) and is based on [eclipse-threadx/samplex](https://github.com/eclipse-threadx/samplex). See [`MXChip/AZ3166/README.md`](MXChip/AZ3166/README.md) for the original toolchain/cloning instructions (ARM GCC, CMake, Ninja, submodules).

### What's in `MXChip/AZ3166`

- **`starter` app** — connects to Wi-Fi, reads the four onboard sensors (temperature/humidity, pressure, accelerometer, magnetometer) every 2 seconds, prints them over the serial console (115200 baud) and renders them in a small 6x8 font on the OLED screen.
- **`mqtt` app** — same sensors, but it follows the RoM sensor contract (`libs/rom-common/rom_common/contracts.py`): every 500 ms it publishes a JSON message with the temperature on `rom/sensor/battery/temp` (QoS 0), and it keeps `rom/sensor/battery/status` (`online` / `offline`, QoS 1, retained; `offline` is the MQTT Last Will) up to date. Publishing anything to the board's `ThreadXAZ3166/incoming` topic still triggers an immediate extra message. This is the one running for the hackathon demo.
  - **Guardian state on the OLED:** it subscribes to `rom/actuator/display/cmd` (QoS 1, retained; published by `services/guardian`) and shows state, `temp_c` and reason on the lower three lines. Invalid commands are ignored, and with no command for 5 seconds it shows `G:NO LINK`.
  - **Reconnects by itself:** if the broker goes away the board keeps retrying (1, 2, 4, 8, then every 10 s), and on reconnect it restores the Last Will, publishes `online` again and re-subscribes, so telemetry and the display resume without a reset.
- Two small fixes worth knowing about if you touch this code:
  - `ssd1306_conf.h`: enabled the `Font_6x8` tiny font (it ships disabled) so four sensor lines fit on the 128x64 OLED at once.
  - Standard `printf`/`snprintf` on this target are built without float support (newlib-nano). Any `%f` formatting must go through nanoprintf's own `npf_snprintf` (`#include "nanoprintf.h"`) instead — see `app/starter/main.c` and `app/mqtt/telemetry.c`.

### Building and flashing

```bash
cd MXChip/AZ3166
git submodule update --init   # fetches threadx + netxduo if you haven't already
bash scripts/build.sh starter   # or: bash scripts/build.sh mqtt
```

Wi-Fi credentials are never committed. For the `mqtt` app, create a git-ignored `MXChip/AZ3166/app/mqtt/cloud_config_local.h` next to `cloud_config.h` with your own values:

```c
#define WIFI_SSID     "your-ssid"
#define WIFI_PASSWORD "your-password"
```

Also set the IP of your broker (`MQTT_LOCAL_BROKER_IP`) in `cloud_config.h` (use your laptop's LAN IP; do not commit environment-specific values). For the `starter` app, fill in `app/starter/cloud_config.h` locally and do not commit it.

The ThreadX / NetX Duo submodules are pinned to known-working revisions (newer 6.5.x-era revisions fail DHCP with this WICED stack). Do not update them.

Flashing is drag-and-drop: the board mounts as a USB mass storage drive. Copy the built binary onto it:

```bash
cp build/app/mxchip_threadx.bin /media/<you>/AZ3166/
```

The board resets and runs the new firmware automatically. Note: after a flash, the drive sometimes remounts read-only (the host sees the mid-flash USB disconnect as an I/O error). Remount it before copying again:

```bash
udisksctl unmount -b /dev/sda && udisksctl mount -b /dev/sda
```

Serial console (boot log, sensor prints): `/dev/ttyACM0` (or the equivalent serial port on your OS) at 115200 baud, e.g. `screen /dev/ttyACM0 115200`.

### Setting up the MQTT broker

Any Mosquitto broker on the hackathon LAN works. Example on Linux:

```bash
sudo tee /etc/mosquitto/conf.d/hackathon.conf > /dev/null <<'CONF'
listener 1883 0.0.0.0
allow_anonymous true
CONF
sudo systemctl restart mosquitto
```

This opens the broker to every device on the network with no authentication — fine for a short-lived hackathon LAN, not for anything you'd leave running afterwards.

### Pulling sensor data from your own laptop

Once the `mqtt` app is flashed and connected, anyone on the same Wi-Fi can read live sensor data — no cables, no pairing.

**Connection details** (adjust the host to whatever the broker's actual LAN IP is):

| | |
|---|---|
| Broker host | `<broker-lan-ip>` |
| Port | `1883` (no auth) |
| Sensor topic | `rom/sensor/battery/temp` (QoS 0) |
| Status topic | `rom/sensor/battery/status` (QoS 1, retained: `online` / `offline`) |
| Request topic | `ThreadXAZ3166/incoming` (optional, on demand) |

**1. Install an MQTT client**

| OS | Command |
|---|---|
| macOS | `brew install mosquitto` |
| Linux / WSL | `sudo apt install mosquitto-clients` |
| Windows | `winget install EclipseMosquitto` |

**2. Watch the live feed** — prints a new message every 500 ms:

```bash
mosquitto_sub -h <broker-lan-ip> -t "rom/sensor/battery/#" -v
```

Example output:

```
rom/sensor/battery/status online
rom/sensor/battery/temp {"device_id":"az3166-01","seq":64,"ts_ms":1791305613274,"temp_c":28.75}
rom/sensor/battery/temp {"device_id":"az3166-01","seq":65,"ts_ms":1791305613794,"temp_c":28.75}
```

`seq` starts at 1 after every boot; `ts_ms` is epoch milliseconds once the board has synced time over SNTP (uptime milliseconds before that, which the adapter treats as "no latency info"); `temp_c` is the board's onboard temperature sensor, standing in for the battery temperature. If the board drops off the network the broker publishes the retained `offline` status within about 15 seconds.

**3. Ask for an extra message on demand** — publish anything to the request topic and the board sends one more message immediately, instead of waiting for the next 500 ms tick:

```bash
mosquitto_pub -h <broker-lan-ip> -t "ThreadXAZ3166/incoming" -m "get"
```

**4. Prefer a GUI?** Install [MQTT Explorer](https://mqtt-explorer.com), add a connection with the broker host above, port `1883`, no credentials, then expand the `rom/sensor/battery` topic tree. Readings update live as a tree view — no commands needed.

**If nothing comes through:** confirm you're on the same Wi-Fi as the broker (both the 2.4GHz and 5GHz bands of the same AP usually reach it) and that the host IP above is still current — if the broker runs on someone's laptop, a DHCP lease change will move it.

## Roadmap

**Idea:** a portable *Safety Evidence Factory* around the Battery Thermal Guardian. Every injected fault
must leave a traceable trail: **hazard → safety goal → injected fault → detection → mitigation → verdict**.

### Target architecture

```mermaid
flowchart LR
  HW[AZ3166 + Eclipse ThreadX] -->|MQTT| AD[MQTT→KUKSA adapter]
  ASC[CAN .asc replay] --> CANP[KUKSA CAN Provider]
  SIM[Simulator] --> KDB
  AD --> KDB[(KUKSA Databroker)]
  CANP --> KDB
  KDB --> PUB[VSS uProtocol Publisher]
  FI[Fault Campaign Runner] -->|inject| PUB
  FI -->|inject| SIM
  PUB -->|uProtocol / Zenoh| G[Battery Thermal Guardian]
  G -->|state · heartbeat · mitigation over uProtocol| DISP[Display / actuator]
  G --> DFM[DFM fault records]
  DFM --> SOVD[Eclipse OpenSOVD]
  SOVD --> EV[Evidence Collector → verdict report]
  ANK[Eclipse Ankaios on AutoSD] -. orchestrates .-> PUB & G & SOVD & EV
```

### Done

- [x] KUKSA Databroker + simulator as the nominal signal source
- [x] VSS uProtocol Publisher (Zenoh transport following the current up-spec)
- [x] Guardian consumes VSS **only via uProtocol** — never reads the Databroker
- [x] Guardian state machine: CLEAR → MONITORING → WARNING → CRITICAL → MITIGATING, plus SENSOR_FAULT (stale / stuck / out of range)
- [x] MQTT → KUKSA adapter with contract validation and sequence-gap detection
- [x] Eclipse ThreadX firmware on AZ3166 publishing sensor telemetry over MQTT
- [x] Containerized dev stack, `make` shortcuts, unit tests per component
- [x] uProtocol extracted into a reusable library (`libs/rom-uprotocol`); every component is its own pip package, services have their own image (ready for Ankaios)
- [x] Placeholder services with their own images: DFM, OpenSOVD, Evidence Collector (build, start, log `not_implemented`)
- [x] Simulator with 4 battery cells (custom VSS overlay) and runtime fault injection over HTTP
- [x] Fault Campaign Runner: YAML campaigns with a seed, signal / source / transport faults, `run_id` on every log line
- [x] Guardian logs the uProtocol `msg_id` / `seq` that caused each state change
- [x] AZ3166 firmware reconnects to the MQTT broker automatically (Last Will `offline`, retained `online`)

### Next

#### 1. Sources
- [x] Bring the ThreadX firmware into `main` and align it with the sensor contract — real hardware end-to-end
- [ ] KUKSA CAN Provider with `.asc` replay as an additional source
- [x] Guardian state shown on the device display (display command over MQTT, `G:NO LINK` after 5 s)

#### 2. Fault campaigns
- [x] Fault Campaign Runner: campaigns described in YAML with a seed (deterministic, replayable); it drives the simulator and the uProtocol publisher over HTTP
- [x] Transport faults: delay · duplicate · drop · reorder
- [x] Signal faults: stuck · spike · drift · out-of-range
- [x] Source faults: dropout · replay interruption
- [x] Combined multi-fault scenarios (one campaign, more can be added as YAML)
- [x] Campaigns for duplicate / reorder and a sensor spike (`transport_duplicate`, `transport_reorder`, `sensor_spike_cell2`)

#### 3. Guardian
- [x] Publish fault events over uProtocol (`up://rom-vehicle/1002/1/8003` → DFM, Python ↔ Rust `up-transport-zenoh`)
- [x] Heartbeats from the uProtocol link, the KUKSA databroker, the adapter / simulator and the physical chip; the guardian names the failing component (DFM code for the root cause)
- [x] Publish state and mitigation over uProtocol (`up://rom-vehicle/1002/1/8006`, on every change and every second)
- [ ] The guardian's own outgoing heartbeat over uProtocol
- [x] AZ3166 liveness heartbeat without a re-flash: the adapter turns the board's telemetry (1.5 s timeout) and its MQTT Last Will (`offline`) into the `chip` heartbeat; the guardian supervises it (`chip silent` → `SENSOR_FAULT`, DTC `chip_silent`, required in `make hw`), and the board watches the guardian back (`G:NO LINK` after 5 s)
- [x] Detect duplicate / reordered messages (dropped, `link_integrity`) and implausible rate of change (`cellN.rate_implausible`, the reading is kept)
- [x] Correlation IDs (`run_id`, uProtocol `msg_id`) on every event: sender (`published`), transport faults (`transport_fault`), guardian, DFM (`fault_msg_id`), OpenSOVD environment data, evidence record

#### 4. Diagnostics
- [x] DFM fault records for every faulted scenario (fault-lib `dfm_bin`, catalog `battery_guardian`, see `services/dfm`)
- [ ] Expose diagnostics through Eclipse OpenSOVD
- [ ] Diagnostic faults: delayed DFM write · partial OpenSOVD visibility

#### 5. Evidence & verdicts
- [x] Hazard and safety-goal catalog linked to each campaign (`services/evidence-collector/evidence_collector/safety_case.yaml`, checked against every bundled campaign)
- [x] Evidence Collector correlating campaign → events → diagnostics, all over uProtocol (campaign events `…/1003/1/8005`, guardian state `…/1002/1/8006`)
- [x] Verdict per run: PASS / FAIL / INCONCLUSIVE, with detection latency and mitigation timing
- [x] Report covering all campaigns, failed scenarios included (`/ui/`, ZIP bundle with SHA-256 manifest)

#### 6. Orchestration & platform
- [ ] Eclipse Ankaios manages the final orchestrated run
- [ ] Run the stack on Eclipse AutoSD
- [ ] Remote reruns (Eclipse openDUT) with verdict consistency check

#### 7. Blueprint & community
- [ ] Reusable package another team can run with one command
- [x] CI pipeline on every PR: tests, DFM fixture check, service images, ThreadX firmware
- [ ] CI runs the fault campaigns
- [ ] Upstream contribution: update `up-transport-zenoh-python` to zenoh 1.x and the current up-spec
- [ ] SDV Blueprint proposal

### How we work

GitHub Issues per roadmap item · feature branches · PRs with one reviewer · CI on every PR ·
JSON logs with correlation IDs as the raw material for evidence.
