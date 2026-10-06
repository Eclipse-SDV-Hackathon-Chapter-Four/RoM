<!-- Made with Claude (Claude Code, Anthropic) -->
# guardian — Battery Thermal Guardian

Thermal-runaway early-warning state machine. Input comes **only over uProtocol**
(`rom_uprotocol.UpSignalSource`), never from the KUKSA Databroker.

`CLEAR` → `MONITORING` → `WARNING` (≥ `WARN_C`) → `CRITICAL` (≥ `CRIT_C`) → `MITIGATING`
(→ `CRITICAL` "mitigation failed" if still hot after 5 s), plus `SENSOR_FAULT` when the signal is
stale (2 s), stuck (10 s) or out of range (−40…100 °C).

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
| `UP_AUTHORITY`, `UP_TRANSPORT`, `ZENOH_*` | see `libs/rom-uprotocol` |

Test: `pytest services/guardian`
