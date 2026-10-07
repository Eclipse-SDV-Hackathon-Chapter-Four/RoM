# Made with Claude (Claude Code, Anthropic)
"""VSS uProtocol Client: KUKSA Databroker -> uProtocol.

Subscribes to the four battery cells and to Max in the databroker and publishes every update:

    Cells.Cell1..4.Temperature   -> up://<UP_AUTHORITY>/1001/1/8002  one message per update, the guardian's input
    VSS_SOURCE_PATH (Max)        -> up://<UP_AUTHORITY>/1001/1/8001  one value, kept for monitors and older consumers

This is the only component that talks to KUKSA on the guardian's side: the guardian reads
uProtocol, never the databroker (challenge architecture rule).

Heartbeats go out on up://<UP_AUTHORITY>/1001/1/8004: the client's own ("uprotocol", "databroker" ok / down from a probe
of KUKSA, see heartbeat.py) and the producers' (Vehicle.RoM.Heartbeat.Chip / Adapter / Simulator, written into KUKSA by
the adapter or simulator and forwarded here as component "chip" / "adapter" / "simulator"; a counter of 0 means down).

Run:  vss-uprotocol-client   (or  python -m vss_uprotocol_client)

Fault injection (off by default): with FAULT_API_PORT set, an interceptor is installed on the cell topic (what the
guardian reads) and on the heartbeat topic, and an HTTP API steers it (drop, delay, duplicate, reorder, databroker_down;
see fault_api.py). FAULT_API_HOST defaults to 127.0.0.1. POST /run also sets the run_id that goes into every cell message.
"""
import os
import signal
import threading
from typing import Callable, Optional

from uprotocol.uri.serializer.uriserializer import UriSerializer

from rom_common import config, contracts, jsonlog
from rom_common.contracts import HB_DOWN, HB_OK
from rom_uprotocol import config as up_config, uris
from rom_uprotocol.faults import TransportFaults
from rom_uprotocol.publisher import HeartbeatPublisher, SignalPublisher
from rom_uprotocol.transport import make_transport

from . import heartbeat
from .fault_api import build_api
from .sources import KuksaSource, SignalSource, coalesce


def vss_source_path() -> str:
    """VSS path the client forwards on the Max topic (source selection); the cells always come from the overlay."""
    return os.environ.get("VSS_SOURCE_PATH", contracts.VSS_BATTERY_TEMP)


def coalesce_s() -> float:
    """COALESCE_MS (default 50): notifications closer than this belong to one source write."""
    return float(os.environ.get("COALESCE_MS", "50")) / 1000


def fault_api_port() -> int:
    """FAULT_API_PORT, 0 when unset: no fault interceptor and no HTTP server."""
    return int(os.environ.get("FAULT_API_PORT", "0"))


def forward(source: SignalSource, max_publisher: SignalPublisher, cells_publisher: SignalPublisher,
            stop: threading.Event, max_path: str = contracts.VSS_BATTERY_TEMP,
            run_id: Callable[[], Optional[str]] = lambda: None, window_s: float = 0.05,
            beats_publisher: Optional[HeartbeatPublisher] = None) -> None:
    """Split every source write: the cells go out as one cell message, Max as one value, the producers' heartbeat
    counters (Vehicle.RoM.Heartbeat.*) as heartbeat messages (counter 0 = that component reports itself down)."""
    cell_of = {path: i for i, path in enumerate(contracts.VSS_CELL_TEMPS, 1)}
    for values, source_ts_ms in coalesce(source, stop, window_s):
        cells = {cell_of[p]: v for p, v in values.items() if p in cell_of}
        if cells:
            cells_publisher.publish_cells(cells, source_ts_ms, run_id())
        if max_path in values:
            max_publisher.publish(max_path, values[max_path], source_ts_ms)
        if beats_publisher is not None:
            for path, component in contracts.VSS_HEARTBEAT_COMPONENTS.items():
                if path in values:
                    beats_publisher.publish(component, HB_OK if values[path] > 0 else HB_DOWN)
        if stop.is_set():
            break


def main():
    log = jsonlog.get_logger("vss_publisher")
    cfg = up_config.uprotocol()
    max_path = vss_source_path()
    ttl_ms = config.thresholds().stale_ms
    transport = make_transport(uris.publisher_uri())
    faults = TransportFaults(log=log) if fault_api_port() > 0 else None
    cells_publisher = SignalPublisher(transport.send_sync, uris.battery_cells_topic(), ttl_ms, log=log,
                                      interceptors=[faults] if faults else [])
    max_publisher = SignalPublisher(transport.send_sync, uris.battery_temp_topic(), ttl_ms, log=log)
    hb_cfg = config.heartbeat()
    beats = HeartbeatPublisher(transport.send_sync, uris.heartbeat_topic(), hb_cfg.stale_ms, log=log,
                               interceptors=[faults] if faults else [])
    api = None
    if faults:
        host = os.environ.get("FAULT_API_HOST", "127.0.0.1")
        api = build_api(faults, log, host, fault_api_port()).start()
        log.log("fault_api_started", host=host, port=api.port)
    log.log("started", cells_topic="up:" + UriSerializer.serialize(uris.battery_cells_topic()),
            max_topic="up:" + UriSerializer.serialize(uris.battery_temp_topic()),
            heartbeat_topic="up:" + UriSerializer.serialize(uris.heartbeat_topic()), vss_path=max_path,
            cells=list(contracts.VSS_CELL_TEMPS), transport=cfg.transport, zenoh_mode=cfg.zenoh_mode,
            zenoh_connect=list(cfg.zenoh_connect))

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    # The KUKSA subscription blocks until the next update, so it runs in a daemon thread
    # and the main thread exits as soon as stop is set.
    source = KuksaSource([*contracts.VSS_CELL_TEMPS, max_path, *contracts.VSS_HEARTBEAT_COMPONENTS], log)
    threading.Thread(target=forward, args=(source, max_publisher, cells_publisher, stop, max_path,
                                           lambda: log.run_id, coalesce_s(), beats), daemon=True).start()
    heartbeat.start(beats, heartbeat.DatabrokerProbe(faults), hb_cfg.period_ms / 1000, stop, log)
    stop.wait()

    if api is not None:
        api.close()
    transport.close_sync()
    log.log("stopped", published=cells_publisher.published + max_publisher.published,
            failed=cells_publisher.failed + max_publisher.failed)


if __name__ == "__main__":
    main()
