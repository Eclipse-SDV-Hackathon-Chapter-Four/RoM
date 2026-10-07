# Made with Claude (Claude Code, Anthropic)
"""Heartbeats of the client side of the chain, published on the uProtocol heartbeat topic (up://.../8002):

    uprotocol    "ok" every period for as long as this process runs (it is silent only when the client or Zenoh is dead)
    databroker   "ok" / "down" every period, from a probe of the KUKSA Databroker (get_server_info)

The databroker is probed in its own thread: a hanging databroker must not stop the "uprotocol" beat, and when the
probe hangs the "databroker" beat goes silent, which the guardian treats like "down".
"""
import threading
from typing import Callable, Optional

from rom_common import kuksa
from rom_common.contracts import COMPONENT_DATABROKER, COMPONENT_UPROTOCOL, HB_DOWN, HB_OK


class DatabrokerProbe:
    """check() -> True if the databroker answers. Keeps one connection, drops it on error, reopens on the next check."""

    def __init__(self, faults=None, open_client: Callable = kuksa.open_client):
        self._faults = faults          # rom_uprotocol.faults.TransportFaults: a databroker_down fault forces "down"
        self._open_client = open_client
        self._client = None

    def check(self) -> bool:
        if self._faults is not None and self._faults.is_active("databroker_down"):
            return False
        try:
            if self._client is None:
                self._client = self._open_client()
            self._client.get_server_info()
            return True
        except Exception:
            self.close()
            return False

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass


def _publish(publisher, component: str, status: str, stop: threading.Event) -> None:
    try:
        publisher.publish(component, status)
    except Exception:
        if not stop.is_set():   # a send after shutdown started is expected to fail; anything else is not
            raise


def beat_uprotocol(publisher, period_s: float, stop: threading.Event) -> None:
    while not stop.is_set():
        _publish(publisher, COMPONENT_UPROTOCOL, HB_OK, stop)
        stop.wait(period_s)


def beat_databroker(publisher, probe: DatabrokerProbe, period_s: float, stop: threading.Event, log=None) -> None:
    last: Optional[bool] = None
    while not stop.is_set():
        up = probe.check()
        if log is not None and up != last:
            log.log("databroker_up" if up else "databroker_down")
        last = up
        _publish(publisher, COMPONENT_DATABROKER, HB_OK if up else HB_DOWN, stop)
        stop.wait(period_s)
    probe.close()


def start(publisher, probe: DatabrokerProbe, period_s: float, stop: threading.Event, log=None) -> list:
    threads = [threading.Thread(target=beat_uprotocol, args=(publisher, period_s, stop), daemon=True),
               threading.Thread(target=beat_databroker, args=(publisher, probe, period_s, stop, log), daemon=True)]
    for t in threads:
        t.start()
    return threads
