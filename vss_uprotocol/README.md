<!-- Made with Claude (Claude Code, Anthropic) -->
# vss_uprotocol — VSS uProtocol Publisher (Zenoh)

The guardian never reads the KUKSA Databroker. This folder puts a uProtocol service interface
between them, as the challenge architecture requires:

```
simulator / adapter --gRPC set--> KUKSA Databroker --gRPC subscribe--> vss_uprotocol.publisher
        --uProtocol publish over Zenoh: up://rom-vehicle/1001/1/8001--> guardian (UpSignalSource)
```

| File | What it is |
|---|---|
| `zenoh_transport.py` | `ZenohTransport`: uProtocol `UTransport` over Zenoh 1.x (publish/notification) |
| `topics.py` | uProtocol URIs: publisher entity, guardian entity, battery temperature topic |
| `publisher.py` | KUKSA → uProtocol bridge, `python -m vss_uprotocol.publisher` |
| `subscriber.py` | `UpSignalSource` (guardian input) + `python -m vss_uprotocol.subscriber` (topic monitor) |

## Run

From the repo root:

```bash
make guardian          # databroker + simulator + vss-publisher + guardian in Docker, follows guardian logs
```

Locally (databroker from `make up` or `make sim-up`), each in its own terminal:

```bash
python -m vss_uprotocol.publisher      # KUKSA -> uProtocol
python -m vss_uprotocol.subscriber     # prints every message: seq, value, latency_ms, msg_id
python -m guardian.guardian --uprotocol
python -m simulator.simulator          # something has to write the VSS path
```

Locally all processes find each other via Zenoh multicast scouting (peer mode), no router needed.
In Docker the publisher listens on `tcp/0.0.0.0:7447` and the guardian connects to it.

## uProtocol contract

| | Value |
|---|---|
| Topic | `up://<UP_AUTHORITY>/1001/1/8001` (`ue_id` 0x1001 = VSS publisher, resource 0x8001 = battery temp) |
| Zenoh key | `up/rom-vehicle/1001/0/1/8001/{}/{}/{}/{}/{}` |
| Payload format | `UPAYLOAD_FORMAT_JSON` |
| Payload | `{"vss_path":"Vehicle.Powertrain.TractionBattery.Temperature.Max","value":47.2,"seq":7,"ts_ms":...,"source_ts_ms":...}` |
| TTL | `STALE_MS` (2000 ms) |

Numbers live in `common/contracts.py` (`UP_*`, `build_/parse_signal_msg`).
`seq` lets a consumer detect dropped / duplicated / reordered messages; the uProtocol message id
(`msg_id`, a UUIDv7) is the correlation ID the guardian logs with every `state_change`.

## Env variables

| Variable | Default | |
|---|---|---|
| `VSS_SOURCE_PATH` | `Vehicle.Powertrain.TractionBattery.Temperature.Max` | which VSS signal the publisher forwards (source selection) |
| `UP_AUTHORITY` | `rom-vehicle` | uProtocol authority name |
| `ZENOH_MODE` | `peer` | `client` if you run a Zenoh router |
| `ZENOH_CONNECT` / `ZENOH_LISTEN` | empty | comma-separated Zenoh endpoints, e.g. `tcp/10.0.0.5:7447` |
| `KUKSA_HOST` / `KUKSA_PORT` | `127.0.0.1` / `55555` | publisher only |

## Why our own transport

- `up-python` (official uProtocol types, builders, validators) is used as is.
- The official `up-transport-zenoh-python` is pinned to `eclipse-zenoh==1.0.0a6` (an alpha),
  uses `ZBytes.deserialize`, which zenoh 1.0 removed, and builds the old 4-segment key.
  It does not follow the current up-spec, so it would not interoperate with a Rust guardian.
- `zenoh_transport.py` follows up-spec `up-l1/zenoh.adoc` and the reference
  `up-transport-zenoh-rust`: 10-segment key, attachment = `0x01` + protobuf `UAttributes`,
  priority mapping CS0..CS6. The tests check the key against every example in the spec.
- `up-python` pins `protobuf==4.24.2`, `kuksa-client` needs protobuf 7; up-python works with 7,
  so it is installed with `pip install --no-deps up-python==0.2.0.dev0` (Dockerfile and `make venv` do this).

Updating `up-transport-zenoh-python` to zenoh 1.x and the current spec would be a useful upstream PR.

## Test

```bash
pytest vss_uprotocol/     # no broker needed; one test runs a real Zenoh pub/sub on localhost
```

## Verified

- simulator → KUKSA → publisher → Zenoh → guardian, in Docker and locally: every message arrives, ~1 ms latency
- simulator stopped → guardian `SENSOR_FAULT / stale signal` after 2 s, back to `MONITORING` when it restarts
- publisher restarted → guardian reconnects on its own and keeps receiving

## Next

- Fault campaign runner: inject delay / duplicate / drop / stuck / spike in the publisher, before `send`
- Second source on its own VSS path (adapter → `Temperature.Average`), selected with `VSS_SOURCE_PATH`
