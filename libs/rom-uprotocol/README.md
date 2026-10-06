<!-- Made with Claude (Claude Code, Anthropic) -->
# rom-uprotocol — uProtocol library for RoM

uProtocol building blocks, independent of KUKSA or any other signal source. Used by the
[VSS uProtocol Client](../../services/vss-uprotocol-client/README.md) (publisher side) and the
[Guardian](../../services/guardian/README.md) (subscriber side).

```
any source --> SignalPublisher --[interceptors]--> UTransport (Zenoh) ==> UpSignalSource --> consumer
```

## Install

```bash
pip install ./libs/rom-common ./libs/rom-uprotocol
pip install --no-deps up-python==0.2.0.dev0     # see "Why --no-deps" below
```

## Use

```python
from rom_uprotocol import uris
from rom_uprotocol.publisher import SignalPublisher
from rom_uprotocol.subscriber import UpSignalSource
from rom_uprotocol.transport import make_transport

# publisher side
transport = make_transport(uris.publisher_uri())          # UP_TRANSPORT, default "zenoh"
pub = SignalPublisher(transport.send_sync, uris.battery_temp_topic(), ttl_ms=2000)
pub.publish("Vehicle.Powertrain.TractionBattery.Temperature.Max", 47.2, source_ts_ms)

# subscriber side
transport = make_transport(uris.guardian_uri())
UpSignalSource(transport, on_sample=lambda s: print(s.value, s.seq, s.msg_id)).start()
```

Watch the topic from a terminal: `rom-up-monitor` (or `python -m rom_uprotocol.subscriber`).

| Module | What it is |
|---|---|
| `contract.py` | uEntity IDs, topic resources, signal payload `build_/parse_signal_msg` |
| `config.py` | `uprotocol()`: authority, transport, Zenoh endpoints from env |
| `uris.py` | `publisher_uri`, `battery_temp_topic`, `guardian_uri` |
| `transport/` | `make_transport(source)` + `register_transport(name, factory)`; `zenoh.py` = `ZenohTransport` |
| `publisher.py` | `SignalPublisher` with interceptor chain |
| `subscriber.py` | `UpSignalSource`, `Sample` |

## Extension points (open for extension, closed for modification)

| Need | How |
|---|---|
| Another transport (SOME/IP, MQTT, ...) | implement `UTransport`, `register_transport("name", factory)`, set `UP_TRANSPORT=name` |
| Fault injection on the wire | an interceptor `interceptor(message, forward) -> UStatus` passed to `SignalPublisher(..., interceptors=[...])`: drop (don't call `forward`), duplicate (call it twice), delay, corrupt |
| Another signal source | lives in the client (`SignalSource`), the library does not change |

## uProtocol contract

| | Value |
|---|---|
| Topic | `up://<UP_AUTHORITY>/1001/1/8001` (`ue_id` 0x1001 = VSS uProtocol Client, resource 0x8001 = battery temp) |
| Zenoh key | `up/rom-vehicle/1001/0/1/8001/{}/{}/{}/{}/{}` |
| Payload format | `UPAYLOAD_FORMAT_JSON` |
| Payload | `{"vss_path":"Vehicle.Powertrain.TractionBattery.Temperature.Max","value":47.2,"seq":7,"ts_ms":...,"source_ts_ms":...}` |
| TTL | `STALE_MS` (2000 ms) |

`seq` lets a consumer detect dropped / duplicated / reordered messages; the uProtocol message id
(`msg_id`, a UUIDv7) is the correlation ID the guardian logs with every `state_change`.

## Env variables

| Variable | Default | |
|---|---|---|
| `UP_AUTHORITY` | `rom-vehicle` | uProtocol authority name |
| `UP_TRANSPORT` | `zenoh` | registered transport to use |
| `ZENOH_MODE` | `peer` | `client` if you run a Zenoh router |
| `ZENOH_CONNECT` / `ZENOH_LISTEN` | empty | comma-separated Zenoh endpoints, e.g. `tcp/10.0.0.5:7447` |

Locally all processes find each other via Zenoh multicast scouting (peer mode), no router needed.
Between containers the client listens on `tcp/0.0.0.0:7447` and the guardian connects to it.

## Why our own Zenoh transport

- `up-python` (official uProtocol types, builders, validators) is used as is.
- The official `up-transport-zenoh-python` is pinned to `eclipse-zenoh==1.0.0a6` (an alpha),
  uses `ZBytes.deserialize`, which zenoh 1.0 removed, and builds the old 4-segment key.
  It does not follow the current up-spec, so it would not interoperate with a Rust guardian.
- `transport/zenoh.py` follows up-spec `up-l1/zenoh.adoc` and the reference
  `up-transport-zenoh-rust`: 10-segment key, attachment = `0x01` + protobuf `UAttributes`,
  priority mapping CS0..CS6. The tests check the key against every example in the spec.

Updating `up-transport-zenoh-python` to zenoh 1.x and the current spec would be a useful upstream PR.

## Why `--no-deps`

`up-python` pins `protobuf==4.24.2`, `kuksa-client` needs protobuf 7; up-python works with 7,
so it is installed with `pip install --no-deps up-python==0.2.0.dev0` (all Dockerfiles and `make venv` do this).

## Test

```bash
pytest libs/rom-uprotocol     # no broker needed; one test runs a real Zenoh pub/sub on localhost
```
