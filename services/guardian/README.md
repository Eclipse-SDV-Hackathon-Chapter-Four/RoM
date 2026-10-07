<!-- Made with Claude (Claude Code, Anthropic) -->
# guardian — Battery Thermal Guardian

Thermal-runaway early-warning state machine over the **4 battery cells**. Input comes **only over uProtocol**
(`rom_uprotocol.UpCellsSource`, `up://<UP_AUTHORITY>/1001/1/8002`), never from the KUKSA Databroker.

`CLEAR` → `MONITORING` → `WARNING` (≥ `WARN_C`) → `CRITICAL` (≥ `CRIT_C`) → `MITIGATING`
(→ `CRITICAL` "mitigation failed" if still hot after 5 s), plus `SENSOR_FAULT`.

## Per-cell monitoring

Each cell is checked on its own: **stale** (missing 2 s while others arrive), **out of range** (outside −40…150 °C),
**stuck** (unchanged 10 s). A bad cell raises its own DFM code and is left out; the thermal states run on the
**hottest valid cell**, so one broken sensor never disarms the warning. `SENSOR_FAULT` only when nothing can be
trusted: no cell message at all for 2 s ("stale signal"), or every cell faulty.

## Fault events (DFM input)

Every fault edge goes out on `up://<UP_AUTHORITY>/1002/1/8003` (`FAILED` / `PASSED`, JSON, no TTL) and is logged as
`fault_event`. Codes, payload and environment data: [`services/dfm/README.md`](../dfm/README.md).
While the input cannot be judged (stream stale), earlier codes keep their state: no data is not "repaired".
The guardian listens on `ZENOH_LISTEN` (compose: `tcp/0.0.0.0:7447`) so the DFM reporter can connect to it.
Watch: `rom-up-monitor --faults`.

## Display output

The guardian also publishes its state for the device display on `rom/actuator/display/cmd`
(`rom_common.contracts.build_display_cmd`, QoS 1, retained): on every state change and once per second as a
heartbeat. `MITIGATING` is not a contract state, so it is sent as `CRITICAL` with the reason
("cooling requested" / "cooling in progress"). The AZ3166 board shows it on its OLED
(see `MXChip/AZ3166`). Needs a broker: `MQTT_HOST` / `MQTT_PORT`.

## Run

```bash
rom-guardian                 # offline test scenario, no broker needed
rom-guardian --uprotocol     # live, reads up://<UP_AUTHORITY>/1001/1/8002, publishes faults on .../1002/1/8003
make guardian                # whole chain in containers
```

Image: `services/guardian/Dockerfile` → `localhost/rom/guardian:dev` (env-only config, stops on SIGTERM).

| Variable | Default |
|---|---|
| `WARN_C`, `CRIT_C` | `38`, `45` |
| `STALE_MS`, `STUCK_S`, `MIN_PLAUSIBLE_C`, `MAX_PLAUSIBLE_C` | `2000`, `10`, `-40`, `150` |
| `IMBALANCE_C`, `IMBALANCE_S` | `10`, `2` (cell spread → `cell_imbalance`) |
| `MQTT_HOST`, `MQTT_PORT` | `localhost`, `1883` |
| `UP_AUTHORITY`, `UP_TRANSPORT`, `ZENOH_*` | see `libs/rom-uprotocol` |

Test: `pytest services/guardian`
