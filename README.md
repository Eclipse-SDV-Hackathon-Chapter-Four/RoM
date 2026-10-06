<!-- Made with Claude (Claude Code, Anthropic) -->
# RoM — Battery Thermal Guardian

Sensor / simulator → KUKSA Databroker → VSS uProtocol Client → (uProtocol over Zenoh) → Guardian → display.
The guardian never reads the databroker directly. Everything runs in Docker; you only need `docker compose` and `make`.

## Repository layout

Every component is its own pip package; services that run under Ankaios have their own image
(`services/<name>/Dockerfile` → `localhost/rom/<name>:dev`, no bind mounts, env-only config).

| Path | Package | Image | What |
|---|---|---|---|
| `libs/rom-common` | `rom_common` | – | contracts, config, JSON logging, KUKSA / MQTT helpers |
| `libs/rom-uprotocol` | `rom_uprotocol` | – | uProtocol library: Zenoh transport, URIs, publisher, subscriber |
| `services/vss-uprotocol-client` | `vss_uprotocol_client` | ✅ | KUKSA Databroker → uProtocol |
| `services/guardian` | `guardian` | ✅ | Battery Thermal Guardian (uProtocol input only) |
| `services/simulator` | `simulator` | dev image | sine-wave temperature into KUKSA |
| `services/adapter` | `adapter` | dev image | MQTT → KUKSA |
| `services/fault-injector` | `fault_injector` | ✅ TODO | Fault Campaign Runner |
| `services/dfm` | `dfm` | ✅ TODO | Diagnostic Fault Manager |
| `services/opensovd` | – | ✅ TODO | Eclipse OpenSOVD server |
| `services/evidence-collector` | `evidence_collector` | ✅ TODO | Evidence Collector → verdicts |

## Quick start

```bash
make guardian                    # databroker + simulator + vss-uprotocol-client + guardian, shows guardian logs
SIM_PERIOD_S=30 make guardian    # faster wave (30 s instead of 120 s)
make down                        # stop everything
```

`Ctrl+C` only stops following the logs; the stack keeps running until `make down`.

## All commands

| Command | What it does |
|---|---|
| `make help` | list all commands |
| `make up` | start databroker + mosquitto in the background |
| `make guardian` | databroker + simulator + vss-uprotocol-client + guardian, follow guardian logs |
| `make images` | build all service images `localhost/rom/<service>:dev` |
| `make sim` | sine-wave simulator into KUKSA (foreground) |
| `make sim-up` | databroker + simulator in the background |
| `make kuksa` | interactive kuksa-client shell (`getValue Vehicle.Powertrain.TractionBattery.Temperature.Max`) |
| `make logs` | follow databroker, mosquitto and simulator logs |
| `make test` | run all tests (`libs/`, `services/`) in the dev image |
| `make shell` | bash inside the Python image |
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
| `SIM_HZ`, `SIM_PERIOD_S`, `SIM_MIN_C`, `SIM_MAX_C` | `2`, `120`, `30`, `69` | simulator |
| `WARN_C`, `CRIT_C` | `38`, `45` | guardian |
| `VSS_SOURCE_PATH` | `Vehicle.Powertrain.TractionBattery.Temperature.Max` | vss-uprotocol-client |
| `UP_AUTHORITY`, `UP_TRANSPORT`, `ZENOH_MODE`, `ZENOH_CONNECT`, `ZENOH_LISTEN` | `rom-vehicle`, `zenoh`, `peer`, –, – | vss-uprotocol-client, guardian |

## Guardian states

`CLEAR` (no data yet) → `MONITORING` → `WARNING` (≥ `WARN_C`) → `CRITICAL` (≥ `CRIT_C`) → `MITIGATING`
(→ `CRITICAL` "mitigation failed" if still hot after 5 s). `SENSOR_FAULT` if the signal is stale (2 s),
stuck (10 s) or out of range (−40…100 °C).
