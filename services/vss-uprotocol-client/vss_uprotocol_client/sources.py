# Made with Claude (Claude Code, Anthropic)
"""Where VSS values come from. The client publishes whatever a SignalSource yields, so a new
source (CAN replay, another databroker, a recorded log) is a new class here, not a client change."""
import threading
from typing import Iterator, Protocol, Tuple

from rom_common import kuksa

Update = Tuple[str, float, int]  # (vss_path, value, source_ts_ms)

RETRY_S = (1, 2, 5)  # KUKSA reconnect backoff, last value repeats


class SignalSource(Protocol):
    def updates(self, stop: threading.Event) -> Iterator[Update]:
        """Yield updates until stop is set. May block while waiting for the next value."""
        ...


class KuksaSource:
    """Subscribes to one VSS path in the KUKSA Databroker; reconnects with backoff when it goes away."""

    def __init__(self, vss_path: str, log, retry_s: Tuple[float, ...] = RETRY_S):
        self.vss_path = vss_path
        self._log = log
        self._retry_s = retry_s

    def updates(self, stop: threading.Event) -> Iterator[Update]:
        attempt = 0
        while not stop.is_set():
            client = None
            try:
                client = kuksa.open_client()
                self._log.log("kuksa_connected", vss_path=self.vss_path)
                attempt = 0
                for value, rx_ms in kuksa.subscribe_temp(client, self.vss_path):
                    yield self.vss_path, value, rx_ms
                    if stop.is_set():
                        return
            except Exception as e:
                self._log.log("kuksa_disconnected", error=str(e))
            finally:
                if client is not None:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
            stop.wait(self._retry_s[min(attempt, len(self._retry_s) - 1)])
            attempt += 1
