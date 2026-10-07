<!-- Made with Claude (Claude Code, Anthropic) -->
# guardian — Battery Thermal Guardian

Thermal-runaway early-warning state machine over the **4 battery cells**. Input comes **only over uProtocol**
(`rom_uprotocol.UpCellsSource`, `up://<UP_AUTHORITY>/1001/1/8002`; heartbeats: `UpHeartbeatSource`), never from the KUKSA Databroker.

`CLEAR` → `MONITORING` → `WARNING` (≥ `WARN_C`) → `CRITICAL` (≥ `CRIT_C`) → `MITIGATING`
(→ `CRITICAL` "mitigation failed" if still hot after 5 s), plus `SENSOR_FAULT`.

## Per-cell monitoring

Each cell is checked on its own: **stale** (missing 2 s while others arrive), **out of range** (outside −40…150 °C),
**stuck** (unchanged 10 s). A bad cell raises its own DFM code and is left out; the thermal states run on the
**hottest valid cell**, so one broken sensor never disarms the warning. `SENSOR_FAULT` only when nothing can be
trusted: no cell message at all for 2 s ("stale signal"), or every cell faulty.

## Heartbeats: which part of the chain broke

Besides the cells the guardian listens to heartbeats on `up://<UP_AUTHORITY>/1001/1/8004`:

| Component | Beats | Gone means | Display reason | DFM code |
|---|---|---|---|---|
| `uprotocol` | vss-uprotocol-client, own beat | client or Zenoh dead | `uP link lost` | `uprotocol_lost` |
| `databroker` | the client's probe of KUKSA, status `ok` / `down` | KUKSA unreachable | `KUKSA down` | `databroker_down` |
| `adapter` / `simulator` | the producer, via a KUKSA signal | producer process dead | `adapter down` / `sim down` | `adapter_down` / `simulator_down` |
| `chip` | the adapter: a counter while the board's telemetry arrives, `0` when it stops (or the simulator) | physical board silent | `chip silent` | `chip_silent` |

`REQUIRED_HEARTBEATS` (default `uprotocol,databroker`; `make hw` adds `adapter,chip`) are expected from the start
(5 s grace); every other component is tracked from its first beat. A beat older than `HEARTBEAT_STALE_MS` (1.5 s, below
the 2 s data limit so the root cause shows up first) or status `down` means lost.

A lost heartbeat makes all readings suspect: `SENSOR_FAULT` with the reason above, no per-cell judgement, earlier
thermal and cell codes keep their state. When several are gone the one **closest to the guardian** is blamed and gets
the only new DFM code (uprotocol > databroker > adapter / simulator > chip; its symptoms are not raised, not even
`signal_stale`). `state_change` / `reason_change` logs carry `lost` and `heartbeats` (`ok` / `down` / `lost` /
`waiting`).

## Fault events (DFM input)

Every fault edge goes out on `up://<UP_AUTHORITY>/1002/1/8003` (`FAILED` / `PASSED`, JSON, no TTL) and is logged as
`fault_event`. Codes, payload and environment data: [`services/dfm/README.md`](../dfm/README.md).
While the input cannot be judged (stream stale), earlier codes keep their state: no data is not "repaired".
The guardian listens on `ZENOH_LISTEN` (compose: `tcp/0.0.0.0:7447`) so the DFM reporter can connect to it.
Watch: `rom-up-monitor --faults`.

## State events (evidence collector input)

The state goes out on `up://<UP_AUTHORITY>/1002/1/8006` (`StateEvent`: `state`, `previous`, `reason`, `temp_c`, `cell`,
`cells`, `seq`, `msg_id`, `run_id`; JSON, no TTL) on every state or reason change and every second (`previous ==
state`), `MITIGATING` included. The [evidence collector](../evidence-collector/README.md) judges each campaign run
from it. Watch: `rom-up-monitor --state`.

## Display output

The guardian also publishes its state for the device display on `rom/actuator/display/cmd`
(`rom_common.contracts.build_display_cmd`, QoS 1, retained): on every state change and once per second as a
heartbeat. `MITIGATING` is not a contract state, so it is sent as `CRITICAL` with the reason
("cooling requested" / "cooling in progress"). The AZ3166 board shows it on its OLED
(see `MXChip/AZ3166`). Needs a broker: `MQTT_HOST` / `MQTT_PORT`.

## Run

```bash
rom-guardian                 # offline test scenario, no broker needed
rom-guardian --uprotocol     # live, reads cells (.../1001/1/8002) and heartbeats (.../8004), publishes faults on .../1002/1/8003 and its state on .../8006
make guardian                # whole chain in containers
```

Image: `services/guardian/Dockerfile` → `localhost/rom/guardian:dev` (env-only config, stops on SIGTERM).

| Variable | Default |
|---|---|
| `WARN_C`, `CRIT_C` | `38`, `45` |
| `STALE_MS`, `STUCK_S`, `MIN_PLAUSIBLE_C`, `MAX_PLAUSIBLE_C` | `2000`, `10`, `-40`, `150` |
| `IMBALANCE_C`, `IMBALANCE_S` | `10`, `2` (cell spread → `cell_imbalance`) |
| `HEARTBEAT_STALE_MS`, `REQUIRED_HEARTBEATS` | `1500`, `uprotocol,databroker` |
| `MQTT_HOST`, `MQTT_PORT` | `localhost`, `1883` |
| `UP_AUTHORITY`, `UP_TRANSPORT`, `ZENOH_*` | see `libs/rom-uprotocol` |

Test: `pytest services/guardian`
