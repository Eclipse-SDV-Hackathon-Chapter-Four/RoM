# Made with Claude (Claude Code, Anthropic)
"""VSS uProtocol Client: KUKSA Databroker -> uProtocol.

Subscribes to one VSS path in the databroker (VSS_SOURCE_PATH, default the contract path)
and publishes every update on the uProtocol topic up://<UP_AUTHORITY>/1001/1/8001.
This is the only component that talks to KUKSA on the guardian's side: the guardian reads
uProtocol, never the databroker (challenge architecture rule).

Run:  vss-uprotocol-client   (or  python -m vss_uprotocol_client)

Fault injection (off by default): with FAULT_API_PORT set, an interceptor is installed on the publisher and an
HTTP API steers it (drop, delay, duplicate, reorder; see fault_api.py). FAULT_API_HOST defaults to 127.0.0.1.
"""
import os
import signal
import threading

from uprotocol.uri.serializer.uriserializer import UriSerializer

from rom_common import config, contracts, jsonlog
from rom_uprotocol import config as up_config, uris
from rom_uprotocol.faults import TransportFaults
from rom_uprotocol.publisher import SignalPublisher
from rom_uprotocol.transport import make_transport

from .fault_api import build_api
from .sources import KuksaSource, SignalSource


def vss_source_path() -> str:
    """VSS path the client forwards to the guardian topic (source selection)."""
    return os.environ.get("VSS_SOURCE_PATH", contracts.VSS_BATTERY_TEMP)


def fault_api_port() -> int:
    """FAULT_API_PORT, 0 when unset: no fault interceptor and no HTTP server."""
    return int(os.environ.get("FAULT_API_PORT", "0"))


def forward(source: SignalSource, publisher: SignalPublisher, stop: threading.Event) -> None:
    for vss_path, value, source_ts_ms in source.updates(stop):
        publisher.publish(vss_path, value, source_ts_ms)
        if stop.is_set():
            break


def main():
    log = jsonlog.get_logger("vss_publisher")
    cfg = up_config.uprotocol()
    vss_path = vss_source_path()
    transport = make_transport(uris.publisher_uri())
    topic = uris.battery_temp_topic()
    faults = TransportFaults() if fault_api_port() > 0 else None
    publisher = SignalPublisher(transport.send_sync, topic, ttl_ms=config.thresholds().stale_ms, log=log,
                                interceptors=[faults] if faults else [])
    api = None
    if faults:
        host = os.environ.get("FAULT_API_HOST", "127.0.0.1")
        api = build_api(faults, log, host, fault_api_port()).start()
        log.log("fault_api_started", host=host, port=api.port)
    log.log("started", topic="up:" + UriSerializer.serialize(topic), vss_path=vss_path,
            transport=cfg.transport, zenoh_mode=cfg.zenoh_mode, zenoh_connect=list(cfg.zenoh_connect))

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    # The KUKSA subscription blocks until the next update, so it runs in a daemon thread
    # and the main thread exits as soon as stop is set.
    threading.Thread(target=forward, args=(KuksaSource(vss_path, log), publisher, stop), daemon=True).start()
    stop.wait()

    if api is not None:
        api.close()
    transport.close_sync()
    log.log("stopped", published=publisher.published, failed=publisher.failed)


if __name__ == "__main__":
    main()
