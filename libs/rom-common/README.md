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
| `contracts` | VSS path, MQTT topics + QoS, guardian states/reasons, `build_/parse_sensor_msg`, `build_/parse_display_cmd`, `ContractError` (log as `event: rejected`) |
| `config` | `endpoints()` (MQTT_HOST/PORT, KUKSA_HOST/PORT) and `thresholds()` (WARN_C, CRIT_C, HYST_C, STALE_MS, STUCK_S, plausible range) from env (`WARN_C`/`CRIT_C` default to the 38/45 °C demo thresholds, not production limits) |
| `jsonlog` | `get_logger("guardian", run_id=...).log("state_change", ...)` → JSON line on stdout |
| `clock` | `now_ms()` (epoch ms), `monotonic_ms()` (durations) |
| `mqtt` | `MqttClient(client_id, will_...)` with `.connect()`, `.publish(topic, payload, qos, retain)`, `.subscribe(topic, handler(topic, payload))`, `.close()`; auto-reconnect and re-subscribe; LWT support |
| `kuksa` | persistent `VSSClient`, `set_temp`, `subscribe_temp` |

The uProtocol contract (entity IDs, topic resources, signal payload) lives in
[`rom-uprotocol`](../rom-uprotocol/README.md), not here.

Tests: `pytest libs/rom-common` (no broker or hardware needed).
