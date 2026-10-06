<!-- Made with Claude (Claude Code, Anthropic) -->
# common — shared module for all RoM components

Import from the repo root (or set `PYTHONPATH=<repo root>`):

```python
from common import config, contracts, jsonlog, clock
from common import mqtt, kuksa      # need paho-mqtt / kuksa-client installed
```

| Module | What it gives you |
|---|---|
| `contracts` | VSS path, MQTT topics + QoS, guardian states/reasons, `build_/parse_sensor_msg`, `build_/parse_display_cmd`, `ContractError` (log as `event: rejected`) |
| `config` | `endpoints()` (MQTT_HOST/PORT, KUKSA_HOST/PORT) and `thresholds()` (WARN_C, CRIT_C, HYST_C, STALE_MS, STUCK_S, plausible range) from env |
| `jsonlog` | `get_logger("guardian", run_id=...).log("state_change", ...)` → JSON line on stdout |
| `clock` | `now_ms()` (epoch ms), `monotonic_ms()` (durations) |
| `mqtt` | paho client factory (LWT, auto-reconnect, re-subscribe on reconnect) |
| `kuksa` | persistent `VSSClient`, `set_temp`, `subscribe_temp` |

If the contract changes, change `contracts/README.md` **and** `common/contracts.py` in the same PR.

Tests: `pytest common/` (no broker or hardware needed).
