# RoM — Battery Thermal Guardian

Sensor → KUKSA Databroker → Guardian → display. Everything runs in Docker; you only need `docker compose` and `make`.

## Quick start

```bash
make guardian                    # databroker + sine-wave simulator + guardian, shows guardian logs
SIM_PERIOD_S=30 make guardian    # faster wave (30 s instead of 120 s)
make down                        # stop everything
```

`Ctrl+C` only stops following the logs; the stack keeps running until `make down`.

## All commands

| Command | What it does |
|---|---|
| `make help` | list all commands |
| `make up` | start databroker + mosquitto in the background |
| `make guardian` | databroker + simulator + guardian, follow guardian logs |
| `make sim` | sine-wave simulator into KUKSA (foreground) |
| `make sim-up` | databroker + simulator in the background |
| `make kuksa` | interactive kuksa-client shell (`getValue Vehicle.Powertrain.TractionBattery.Temperature.Max`) |
| `make logs` | follow databroker, mosquitto and simulator logs |
| `make test` | run all tests (`common/`, `simulator/`, `guardian/`) |
| `make shell` | bash inside the Python image |
| `make down` | stop everything |

## Without Docker (local Python)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python -m guardian.guardian            # offline test scenario, no broker needed
python -m guardian.guardian --kuksa    # live, needs the databroker (make up)
python -m simulator.simulator          # sine wave into KUKSA
pytest -q
```

## Settings (env variables)

| Variable | Default | Used by |
|---|---|---|
| `KUKSA_HOST` / `KUKSA_PORT` | `127.0.0.1` / `55555` | all |
| `MQTT_HOST` / `MQTT_PORT` | `localhost` / `1883` | all |
| `SIM_HZ`, `SIM_PERIOD_S`, `SIM_MIN_C`, `SIM_MAX_C` | `2`, `120`, `30`, `69` | simulator |
| `WARN_C`, `CRIT_C` | `38`, `45` | guardian |

## Guardian states

`CLEAR` (no data yet) → `MONITORING` → `WARNING` (≥ `WARN_C`) → `CRITICAL` (≥ `CRIT_C`) → `MITIGATING`
(→ `CRITICAL` "mitigation failed" if still hot after 5 s). `SENSOR_FAULT` if the signal is stale (2 s),
stuck (10 s) or out of range (−40…100 °C).
