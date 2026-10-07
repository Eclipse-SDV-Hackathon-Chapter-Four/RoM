<!-- Made with Claude (Claude Code, Anthropic) -->
# vss-uprotocol-client — KUKSA Databroker → uProtocol

The guardian never reads the KUKSA Databroker. This service is the uProtocol service interface
between them, as the challenge architecture requires:

```
simulator / adapter --gRPC set--> KUKSA Databroker --gRPC subscribe--> vss-uprotocol-client
        --uProtocol publish (rom_uprotocol, Zenoh): up://rom-vehicle/1001/1/8001--> guardian
```

| File | What it is |
|---|---|
| `vss_uprotocol_client/sources.py` | `SignalSource` protocol + `KuksaSource` (subscribe, reconnect with backoff) |
| `vss_uprotocol_client/__main__.py` | wires `KuksaSource` → `rom_uprotocol.SignalPublisher`; SIGTERM-safe |
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
| `VSS_SOURCE_PATH` | `Vehicle.Powertrain.TractionBattery.Temperature.Max` | which VSS signal is forwarded |
| `STALE_MS` | `2000` | uProtocol message TTL |
| `FAULT_API_PORT` / `FAULT_API_HOST` | unset (off) / `127.0.0.1` | transport-fault API; unset = no interceptor installed, behaviour unchanged |
| `UP_AUTHORITY`, `UP_TRANSPORT`, `ZENOH_*` | see rom-uprotocol | transport |

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

The publisher numbers every message before the interceptor, so a drop shows up downstream as a `seq` gap.

## Log events

`started`, `kuksa_connected`, `kuksa_disconnected`, `published` (`seq`, `value`, counters), `publish_failed`, `stopped`;
with the fault API: `fault_api_started`, `run_started`, `fault_injected`, `fault_cleared`.

## Test

```bash
pytest services/vss-uprotocol-client     # no databroker needed (fake KUKSA client)
```
