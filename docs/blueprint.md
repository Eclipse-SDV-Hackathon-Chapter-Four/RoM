<!-- Made with Claude (Claude Code, Anthropic) -->
# Blueprint: Safety Evidence Factory

Metadata: [`.sdv-blueprint.json`](../.sdv-blueprint.json) (format of [Eclipse SDV Blueprints](https://sdv-blueprints.eclipse.dev/))

## Use case

An SDV service that guards a safety function (here: battery thermal runaway) has to show that it reacts correctly to
faults it cannot see coming: a stuck sensor, a late message, a dead databroker. Hand-written test reports do not scale and
cannot be rerun. This blueprint turns that into a pipeline:

```
hazard → safety goal → seeded fault campaign → detection → mitigation → DTC in OpenSOVD → verdict → evidence bundle
```

Every arrow is a real message with a correlation id (`run_id`, uProtocol `msg_id`), so a verdict can be traced back to the
exact message that caused it. A safety engineer reads the report; a CI pipeline fails on a broken safety goal.

**Who reuses it:** teams building any SDV safety function (thermal, child presence, brake wear, …) that want automated,
replayable fault evidence, and OpenSOVD / uProtocol users looking for a working end-to-end integration.

## What you get

| Building block | Reusable for | Where |
|---|---|---|
| uProtocol library (Zenoh, current up-spec, Python) | any Python uEntity | [`libs/rom-uprotocol`](../libs/rom-uprotocol) |
| VSS → uProtocol client with heartbeats and a transport fault API (drop, delay, duplicate, reorder) | any VSS signal from KUKSA | [`services/vss-uprotocol-client`](../services/vss-uprotocol-client) |
| Fault Campaign Runner: YAML campaigns with seed, hazard, safety goal, expected state, expected / tolerated DTCs, deadline | any service with an HTTP fault API | [`services/fault-injector`](../services/fault-injector) |
| uProtocol fault events → fault-lib DFM (Rust) | any service that raises DTCs | [`services/dfm`](../services/dfm) |
| SOVD `faults` resource on opensovd-core (list, filter, detail with environment data, clear) | any DFM catalog | [`services/opensovd`](../services/opensovd) |
| Evidence Collector: safety case, PASS / FAIL / INCONCLUSIVE, report, SHA-256 bundle, offline re-verification | any service that publishes its state and faults | [`services/evidence-collector`](../services/evidence-collector) |
| Ankaios manifest + one-command run | the whole stack | [`infra/ankaios`](../infra/ankaios) |
| Example guardian (4 cells, whodunit heartbeats) and a ThreadX node that is sensor and actuator | reference implementation | [`services/guardian`](../services/guardian), [`MXChip/AZ3166`](../MXChip/AZ3166) |

## Run it

Only Docker and `make` (Linux x86_64). Every step is also what CI runs on every PR.

| Level | Command | Result |
|---|---|---|
| 1. Live stack | `make images && make guardian`, then `make dashboard` | dashboard on `localhost:5173`, OpenSOVD on `localhost:7690/sovd` |
| 2. One campaign | `make campaign C=databroker_down`, then `make evidence` | verdict with detection latency and the DTC from OpenSOVD |
| 3. Everything, orchestrated | `make final-run` (podman + Ankaios ≥ 1.0, ~25 min) | `runs/<id>/`: verdicts, summary, evidence bundle, logs |
| CI | `make evidence-ci` | fails unless every campaign in `CI_CAMPAIGNS` PASSes and the bundle verifies offline |

## From simulation to a real device

The same pipeline runs with a real ECU-like device in the loop. The reference is an MXChip AZ3166 on Eclipse ThreadX that
is **both ends of the loop**:

```
AZ3166 sensor ──MQTT──▶ adapter ──▶ KUKSA ──▶ uProtocol ──▶ guardian ──MQTT──▶ AZ3166 OLED (state, temperature, reason)
```

| Pattern | How | Why it matters for reuse |
|---|---|---|
| **Sensor** | the board publishes its temperature every 500 ms on `rom/sensor/battery/temp`; the adapter validates it against the sensor contract and writes it as cell 1 | a real reading enters the same VSS / uProtocol path as the simulated ones |
| **Actuator** | the guardian publishes its state on `rom/actuator/display/cmd` (retained); the board shows state, temperature and reason on its OLED | the reaction is visible on the device, not only in logs |
| **Swap without code change** | `make hw` (board = cell 1, simulator = cells 2-4) or the dashboard's cell 1 switch; exactly one writer per cell | the guardian, DTCs and evidence stay unchanged between simulation and hardware |
| **Device liveness** | MQTT Last Will (`offline`) and a telemetry timeout become the `chip` heartbeat → `SENSOR_FAULT` "chip silent", DTC `chip_silent`; the board shows `G:NO LINK` when the guardian goes quiet | a dead device is named as the root cause, in both directions |

To use another device: publish the sensor contract ([`contracts.py`](../libs/rom-common/rom_common/contracts.py)), subscribe to
the display command, and set `ADAPTER_CELL` to the cell it replaces. Firmware and flashing: [hardware guide](hardware-az3166.md).

## Adapt it to your own safety function

1. **Your service** subscribes to its inputs and publishes two topics: its state (`…/1002/1/8006`) and fault events
   (`…/1002/1/8003`, FAILED / PASSED per DTC). Builders and parsers: [`contract.py`](../libs/rom-uprotocol/rom_uprotocol/contract.py).
2. **Your DTCs:** add them to the fault-lib catalog ([`battery_guardian.json`](../services/dfm/catalog/battery_guardian.json))
   and to `rom_common.contracts.FAULT_CODES`; a test fails if the two drift apart. OpenSOVD serves them with no code change.
3. **Your hazards:** hazards, safety goals and requirements in
   [`safety_case.yaml`](../services/evidence-collector/evidence_collector/safety_case.yaml); the collector refuses to start
   on a broken link, and a campaign not listed there can never PASS.
4. **Your campaigns:** one YAML file per scenario in
   [`campaigns/`](../services/fault-injector/fault_injector/campaigns); point a fault `target` at your service's fault API.

### uProtocol contract

| Topic | Payload | From → to |
|---|---|---|
| `up://<authority>/1001/1/8002` | cell temperatures (VSS) | VSS client → guardian |
| `up://<authority>/1001/1/8004` | heartbeats (link, databroker, producer, chip) | VSS client → guardian |
| `up://<authority>/1002/1/8003` | fault events (DTC, FAILED / PASSED, environment data) | guardian → DFM, collector |
| `up://<authority>/1002/1/8006` | guardian state + mitigation | guardian → collector, cooling actuator |
| `up://<authority>/1003/1/8005` | campaign start / fault injected / cleared / end | fault injector → collector |

## Status and limits

- **Verified:** 22 campaigns under Ankaios (20 PASS, 1 FAIL on purpose, 1 fixed and PASS on rerun); CI on every PR, including
  the ThreadX firmware build. The campaigns ran with the simulator; the AZ3166 loop (sensor in, guardian state on the OLED)
  was verified by hand on the real board.
- **Not yet:** AutoSD as the runtime ([#24](https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/RoM/issues/24)),
  remote reruns with openDUT ([#25](https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/RoM/issues/25)), a CAN trace
  source through the KUKSA CAN Provider ([#22](https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/RoM/issues/22)).
- **Security:** the fault APIs have no authentication and listen on `127.0.0.1` only; test benches, not vehicles.
- **Upstream:** the SOVD `faults` resource is offered to opensovd-core
  ([#156](https://github.com/eclipse-opensovd/opensovd-core/issues/156#issuecomment-6044980574)).

## Maintainers

Team RoM: [@petarlazic04](https://github.com/petarlazic04) · [@djurovic04](https://github.com/djurovic04) ·
[@st4nkich](https://github.com/st4nkich) · [@codermery](https://github.com/codermery). License: Apache-2.0.
