# Made with Claude (Claude Code, Anthropic) — shared RoM "rom_common" library, used by all components.
"""Thin kuksa-client helper (imported lazily). One persistent connection per process."""
from typing import Dict, Iterator, Tuple

from . import config
from .contracts import VSS_BATTERY_TEMP


def open_client():
    """Return a connected VSSClient (caller keeps it open; call .disconnect() on exit)."""
    from kuksa_client.grpc import VSSClient

    ep = config.endpoints()
    client = VSSClient(ep.kuksa_host, ep.kuksa_port)
    client.connect()
    return client


def set_temp(client, temp_c: float, path: str = VSS_BATTERY_TEMP) -> None:
    from kuksa_client.grpc import Datapoint

    client.set_current_values({path: Datapoint(float(temp_c))})


def set_values(client, values: Dict[str, float]) -> None:
    """Write several VSS paths in one call, so a reader never sees half an update."""
    from kuksa_client.grpc import Datapoint

    client.set_current_values({path: Datapoint(float(v)) for path, v in values.items()})


def subscribe_temp(client, path: str = VSS_BATTERY_TEMP) -> Iterator[Tuple[float, int]]:
    """Yield (value, rx_ts_ms) for every update. Blocks; run it in its own thread."""
    from .clock import now_ms

    for updates in client.subscribe_current_values([path]):
        dp = updates.get(path)
        if dp is not None and dp.value is not None:
            yield float(dp.value), now_ms()
