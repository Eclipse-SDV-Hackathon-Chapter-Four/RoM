# Made with Claude (Claude Code, Anthropic)
"""Where VSS values come from. The client publishes whatever a SignalSource yields, so a new
source (CAN replay, another databroker, a recorded log) is a new class here, not a client change."""
import queue
import threading
from typing import Dict, Iterator, Optional, Protocol, Sequence, Tuple

from rom_common import kuksa

Update = Tuple[Dict[str, float], int]  # ({vss_path: value} of one source update, source_ts_ms)

RETRY_S = (1, 2, 5)  # KUKSA reconnect backoff, last value repeats


class SignalSource(Protocol):
    def updates(self, stop: threading.Event) -> Iterator[Update]:
        """Yield updates until stop is set. May block while waiting for the next value."""
        ...


class KuksaSource:
    """Subscribes to VSS paths in the KUKSA Databroker; reconnects with backoff when it goes away.

    Yields what the databroker notifies: in practice one path per update, see coalesce().
    """

    def __init__(self, vss_paths: Sequence[str], log, retry_s: Tuple[float, ...] = RETRY_S):
        self.vss_paths = list(vss_paths)
        self._log = log
        self._retry_s = retry_s

    def updates(self, stop: threading.Event) -> Iterator[Update]:
        attempt = 0
        while not stop.is_set():
            client = None
            try:
                client = kuksa.open_client()
                self._log.log("kuksa_connected", vss_paths=self.vss_paths)
                attempt = 0
                for values, rx_ms in kuksa.subscribe_values(client, self.vss_paths):
                    yield values, rx_ms
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


def coalesce(source: SignalSource, stop: threading.Event, window_s: float) -> Iterator[Update]:
    """Merge the updates of one source write into one batch.

    The databroker notifies every path on its own (a write of four cells + Max arrives as five updates about 1 ms
    apart), so updates are merged until `window_s` passes without a new one, or a path comes again (next write).
    """
    pending: "queue.Queue[Optional[Update]]" = queue.Queue()

    def pump():
        try:
            for update in source.updates(stop):
                pending.put(update)
        finally:
            pending.put(None)

    threading.Thread(target=pump, daemon=True).start()
    merged: Dict[str, float] = {}
    ts = 0
    while True:
        try:
            item = pending.get(timeout=window_s if merged else 0.5)
        except queue.Empty:
            if merged:
                yield merged, ts
                merged = {}
            if stop.is_set():
                return
            continue
        if item is None:
            if merged:
                yield merged, ts
            return
        values, item_ts = item
        if merged and set(values) & set(merged):
            yield merged, ts
            merged = {}
        if not merged:
            ts = item_ts
        merged.update(values)
