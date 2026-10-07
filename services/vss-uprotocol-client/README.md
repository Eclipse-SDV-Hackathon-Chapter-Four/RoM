<!-- Made with Claude (Claude Code, Anthropic) -->
# vss-uprotocol-client — KUKSA Databroker → uProtocol

The guardian never reads the KUKSA Databroker. This service is the uProtocol service interface
between them, as the challenge architecture requires:

```
simulator / adapter --gRPC set--> KUKSA Databroker --gRPC subscribe--> vss-uprotocol-client
        --uProtocol publish (rom_uprotocol, Zenoh)--> up://rom-vehicle/1001/1/8002  4 cells, one message per write --> guardian
                                                     up://rom-vehicle/1001/1/8001  Max (monitors)
```

The databroker notifies every path on its own (a simulator write of 4 cells + Max arrives as 5 updates about
1 ms apart). `coalesce()` merges the updates of one write into one batch (until `COALESCE_MS` passes without an
update, or a path comes again), so one cell message carries every cell of that write and a cell that was **not**
written is absent from it. That is how the guardian sees a single-cell dropout.
Transport faults (fault API) apply to the cell topic, the one the guardian reads.

| File | What it is |
|---|---|
| `vss_uprotocol_client/sources.py` | `SignalSource` protocol, `KuksaSource` (subscribe, reconnect with backoff), `coalesce()` |
| `vss_uprotocol_client/__main__.py` | wires `KuksaSource` → `rom_uprotocol.SignalPublisher`; SIGTERM-safe |
| `vss_uprotocol_client/heartbeat.py` | `DatabrokerProbe` + the `uprotocol` / `databroker` heartbeat threads |
| `vss_uprotocol_client/fault_api.py` | optional HTTP API for transport faults (below) |

A new source (CAN replay, another databroker, a recorded log) is a new `SignalSource` class;
the publishing side and the guardian do not change. All uProtocol details live in
[`libs/rom-uprotocol`](../../libs/rom-uprotocol/README.md).

## Run

```bash
make guardian                                   # whole chain in containers, follows guardian logs
docker build -f services/vss-uprotocol-client/Dockerfile -t localhost/rom/vss-uprotocol-client:dev .
docker run --rm --network host localhost/rom/vss-uprotocol-client:dev    # databroker on localhost
vss-uprotocol-client                            # from the dev venv (make venv)
```

## Env variables

| Variable | Default | |
|---|---|---|
| `KUKSA_HOST` / `KUKSA_PORT` | `127.0.0.1` / `55555` | databroker |
| `VSS_SOURCE_PATH` | `Vehicle.Powertrain.TractionBattery.Temperature.Max` | VSS signal forwarded on the Max topic (cells: `rom_common.contracts.VSS_CELL_TEMPS`) |
| `COALESCE_MS` | `50` | notifications closer than this belong to one source write |
| `STALE_MS` | `2000` | uProtocol message TTL |
| `HEARTBEAT_PERIOD_MS` / `HEARTBEAT_STALE_MS` | `500` / `1500` | own heartbeat period; the TTL of a heartbeat |
| `FAULT_API_PORT` / `FAULT_API_HOST` | unset (off) / `127.0.0.1` | transport-fault API; unset = no interceptor installed, behaviour unchanged |
| `UP_AUTHORITY`, `UP_TRANSPORT`, `ZENOH_*` | see rom-uprotocol | transport |

## Heartbeats

On `up://<UP_AUTHORITY>/1001/1/8004`:

| `component` | `status` | From |
|---|---|---|
| `uprotocol` | `ok` | this process, every `HEARTBEAT_PERIOD_MS`, for as long as it runs. If it stops, the client or Zenoh is dead. |
| `databroker` | `ok` / `down` | a probe of KUKSA (`get_server_info()`) in its own thread. A dead databroker is reported as `down` (the client keeps beating); a hanging probe goes silent, which the guardian treats the same. |
| `chip` / `adapter` / `simulator` | `ok` / `down` | the producers' KUKSA counters `Vehicle.RoM.Heartbeat.Chip / .Adapter / .Simulator`, forwarded as they are written; a counter of `0` is `down` (the adapter writes it for a board that stopped sending telemetry). |

## Transport faults (fault injection)

With `FAULT_API_PORT` set (compose: 8081, published on `127.0.0.1` only) a `rom_uprotocol.faults.TransportFaults`
interceptor sits between the publisher and Zenoh, and an HTTP API steers it. The [fault-injector](../fault-injector/README.md)
uses it; you can also use `curl`. JSON, **no authentication**: keep it off shared networks.

| Request | |
|---|---|
| `POST /run` `{"run_id":"r1","seed":7}` | new run: faults cleared, RNG reseeded, counters zeroed, logs tagged |
| `POST /faults` `{"type":"delay","params":{"ms":2500},"duration_s":10}` | inject; 201 + fault with `id`, 422 on a bad request |
| `GET /faults`, `DELETE /faults/{id}`, `DELETE /faults` | list, clear one, clear all |
| `GET /state` | run id, active faults, counters (`seen`, `dropped`, `reordered`, `duplicated`, `delayed`) |

| Type | Effect | `params` |
|---|---|---|
| `drop` | loses the message | `probability` (default 1.0) |
| `reorder` | holds one message and sends it after the next (pairs swap) | – |
| `duplicate` | sends extra copies | `copies` (default 1) |
| `delay` | sends later, from a timer thread; beyond the TTL it arrives expired | `ms` (required) |
| `databroker_down` | not a message fault: the databroker probe reports `down` while it is active (simulated outage) | – |

Every transport fault takes `params.topic`: `all` (default: cells and heartbeats), `signal` (cells only) or `heartbeat`
(heartbeats only), to lose or delay just the data or just the heartbeats.

The publisher numbers every message before the interceptor, so a drop shows up downstream as a `seq` gap.

## Log events

`started`, `kuksa_connected`, `kuksa_disconnected`, `published` (`seq`, `value`, counters), `publish_failed`, `heartbeat_failed`, `databroker_up` / `databroker_down` (changes only), `stopped`;
with the fault API: `fault_api_started`, `run_started`, `fault_injected`, `fault_cleared`.

## Test

```bash
pytest services/vss-uprotocol-client     # no databroker needed (fake KUKSA client)
```
