<!-- Made with Claude (Claude Code, Anthropic) -->
# guardian — Battery Thermal Guardian

Thermal-runaway early-warning state machine. Input comes **only over uProtocol**
(`rom_uprotocol.UpSignalSource`), never from the KUKSA Databroker.

`CLEAR` → `MONITORING` → `WARNING` (≥ `WARN_C`) → `CRITICAL` (≥ `CRIT_C`) → `MITIGATING`
(→ `CRITICAL` "mitigation failed" if still hot after 5 s), plus `SENSOR_FAULT` when the signal is
stale (2 s), stuck (10 s) or out of range (−40…150 °C).

## Display output

The guardian also publishes its state for the device display on `rom/actuator/display/cmd`
(`rom_common.contracts.build_display_cmd`, QoS 1, retained): on every state change and once per second as a
heartbeat. `MITIGATING` is not a contract state, so it is sent as `CRITICAL` with the reason
("cooling requested" / "cooling in progress"). The AZ3166 board shows it on its OLED
(see `MXChip/AZ3166`). Needs a broker: `MQTT_HOST` / `MQTT_PORT`.

## Run

```bash
rom-guardian                 # offline test scenario, no broker needed
rom-guardian --uprotocol     # live, reads up://<UP_AUTHORITY>/1001/1/8001
make guardian                # whole chain in containers
```

Image: `services/guardian/Dockerfile` → `localhost/rom/guardian:dev` (env-only config, stops on SIGTERM).

| Variable | Default |
|---|---|
| `WARN_C`, `CRIT_C` | `38`, `45` |
| `STALE_MS`, `STUCK_S`, `MIN_PLAUSIBLE_C`, `MAX_PLAUSIBLE_C` | `2000`, `10`, `-40`, `150` |
| `MQTT_HOST`, `MQTT_PORT` | `localhost`, `1883` |
| `UP_AUTHORITY`, `UP_TRANSPORT`, `ZENOH_*` | see `libs/rom-uprotocol` |

`WARN_C` / `CRIT_C` are conservative supervisory demo defaults, not regulatory or universal thermal-runaway
thresholds: production values are manufacturer, cell and pack specific. Override them via the environment
(`rom_common.config.thresholds()` uses the same defaults).

Test: `pytest services/guardian`
