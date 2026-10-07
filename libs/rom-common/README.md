<!-- Made with Claude (Claude Code, Anthropic) -->
# rom-common — shared library for all RoM components

```bash
pip install ./libs/rom-common                 # core: contracts, config, jsonlog, clock
pip install "./libs/rom-common[kuksa,mqtt]"   # + kuksa-client / paho-mqtt helpers
```

```python
from rom_common import config, contracts, jsonlog, clock
from rom_common import mqtt, kuksa      # need the [mqtt] / [kuksa] extras
```

| Module | What it gives you |
|---|---|
| `contracts` | VSS paths (`VSS_BATTERY_TEMP`, `VSS_CELL_TEMPS` = the 4-cell overlay, `VSS_HEARTBEAT_*`), heartbeat components, their short guardian reasons and DFM codes (`HEARTBEAT_*`), MQTT topics + QoS, guardian states/reasons, `build_/parse_sensor_msg`, `build_/parse_display_cmd`, `ContractError` (log as `event: rejected`) |
| `config` | `endpoints()` (MQTT_HOST/PORT, KUKSA_HOST/PORT), `thresholds()` (WARN_C, CRIT_C, HYST_C, STALE_MS, STUCK_S, plausible range, imbalance) and `heartbeat()` (HEARTBEAT_PERIOD_MS, HEARTBEAT_STALE_MS, CHIP_TIMEOUT_MS, REQUIRED_HEARTBEATS) from env |
| `jsonlog` | `get_logger("guardian", run_id=...).log("state_change", ...)` → JSON line on stdout |
| `clock` | `now_ms()` (epoch ms), `monotonic_ms()` (durations) |
| `mqtt` | `MqttClient(client_id, will_...)` with `.connect()`, `.publish(topic, payload, qos, retain)`, `.subscribe(topic, handler(topic, payload))`, `.close()`; auto-reconnect and re-subscribe; LWT support |
| `kuksa` | persistent `VSSClient`, `set_temp`, `set_values` (several paths in one write), `subscribe_temp` |
| `control` | `ControlServer`: tiny stdlib JSON-over-HTTP server (`route`, `start`, `close`) used for the fault APIs; no authentication |

The uProtocol contract (entity IDs, topic resources, signal payload) lives in
[`rom-uprotocol`](../rom-uprotocol/README.md), not here.

Tests: `pytest libs/rom-common` (no broker or hardware needed).
