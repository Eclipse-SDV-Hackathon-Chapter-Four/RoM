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
| `UP_AUTHORITY`, `UP_TRANSPORT`, `ZENOH_*` | see rom-uprotocol | transport |

## Log events

`started`, `kuksa_connected`, `kuksa_disconnected`, `published` (`seq`, `value`, counters), `publish_failed`, `stopped`.

## Test

```bash
pytest services/vss-uprotocol-client     # no databroker needed (fake KUKSA client)
```
