<!-- Made with Claude (Claude Code, Anthropic) -->
# adapter — MQTT → KUKSA

Subscribes to `rom/sensor/battery/temp`, validates each payload against the contract
(`rom_common/contracts.py` in `libs/rom-common`) and writes `temp_c` to `Vehicle.Powertrain.TractionBattery.Temperature.Max`
in the KUKSA Databroker.

```
MCU sensor --MQTT--> adapter --gRPC set--> KUKSA Databroker
```

## Run

From the repo root:

```bash
make up                                              # mosquitto + databroker
make venv                                            # or: make shell (dev image)
.venv/bin/rom-adapter
```

Inside the dev container (`make shell`) `MQTT_HOST`/`KUKSA_HOST` already point to the compose services.

> If port 1883 is already taken by a system `mosquitto` service (`systemctl is-active mosquitto`),
> `make up` fails with "address already in use". Either stop it (`sudo systemctl stop mosquitto`) or use it. Note that the default system config
> listens only on `127.0.0.1`, so the MCUs cannot reach it — use the compose broker for hardware runs.

## Env variables

| Variable | Default |
|---|---|
| `MQTT_HOST` / `MQTT_PORT` | `localhost` / `1883` |
| `KUKSA_HOST` / `KUKSA_PORT` | `127.0.0.1` / `55555` |

## Mapping

`MAPPING` at the top of `adapter/mqtt_kuksa_adapter.py`: `topic -> (VSS path, scale, offset)`.
Add a new signal there, nowhere else.

## Log events (JSON lines on stdout)

| `event` | Meaning |
|---|---|
| `started`, `mqtt_connected`, `kuksa_connected`, `stopped` | lifecycle |
| `forwarded` | value written to KUKSA (`seq`, `temp_c`, `value`, counters; `latency_ms` only if the device sends epoch `ts_ms`) |
| `rejected` | payload violates the contract — **not** written |
| `seq_gap` / `seq_duplicate` / `seq_backwards` | lost / duplicated / reordered (or device reboot) messages — value is still forwarded |
| `kuksa_write_failed` | databroker unreachable; connection is reopened on the next message |

## Test standalone (no MCU)

```bash
pytest services/adapter                              # unit tests, no broker needed

mosquitto_pub -h localhost -t rom/sensor/battery/temp \
  -m '{"device_id":"fake","seq":1,"ts_ms":0,"temp_c":50.0}'
kuksa-client grpc://127.0.0.1:55555                  # then: getValue Vehicle.Powertrain.TractionBattery.Temperature.Max
```

## Verified

- manual `mosquitto_pub` → value readable from KUKSA
- malformed JSON → `rejected`, adapter keeps running
- databroker stopped and restarted → `kuksa_write_failed`, then `kuksa_connected` and forwarding resumes
- MQTT broker stopped and restarted → `mqtt_connected` again and forwarding resumes (no messages lost after reconnect)

## Next steps (branch `feature/mqtt-kuksa-adapter`)

Definition of Done from `PLAN.md` is met; what is left before and after the merge:

**Before the PR**
- [ ] `make test` runs only `common/` → change it to `pytest -q` so adapter tests run too
- [ ] Log `mqtt_disconnected` (paho `on_disconnect`): today a broker outage is invisible in the log, only the reconnect shows up
- [ ] Commit `adapter/`, push the branch, open a PR to `main` with one reviewer

**Phase 0 leftovers (infra is ours)**
- [ ] `contracts/README.md` — referenced by `common/` but missing; copy the contract tables from `PLAN.md` §0.1
- [ ] Hardware run: stop the system mosquitto (`sudo systemctl stop mosquitto`), `make up`,
      open the firewall (`sudo firewall-cmd --add-port=1883/tcp`), write the laptop IP down for the MCU config

**Integration (T+2:15 → T+3:30)**
- [ ] Integration #1: manual `mosquitto_pub` → value in `kuksa-client` on `main` after merge
- [ ] Integration #2: real MCU sensor → adapter → guardian; watch for `seq_gap` and `latency_ms`
      (latency only appears if the MCU sends epoch `ts_ms`, i.e. has NTP)
- [ ] `scripts/run_mvp.sh` (together with Person C): `make up` → adapter or simulator → guardian, logs into `logs/`
- [ ] Root `README.md`: how to run the whole MVP

**After the MVP**
- [ ] Container for the adapter (service in `infra/docker-compose.yml`, built from `infra/Dockerfile`)
- [ ] Optional: forward `rom/sensor/battery/status` (`online`/`offline`) so the guardian can tell
      "sensor offline" apart from a stale value
