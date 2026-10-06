# Made with Claude (Claude Code, Anthropic) — shared RoM "common" module, used by all components.
"""Environment-driven configuration. Never hardcode IPs; see contracts/README.md."""
import os
from dataclasses import dataclass

from .contracts import VSS_BATTERY_TEMP


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Endpoints:
    mqtt_host: str
    mqtt_port: int
    kuksa_host: str
    kuksa_port: int


def endpoints() -> Endpoints:
    return Endpoints(
        mqtt_host=_env("MQTT_HOST", "localhost"),
        mqtt_port=int(_env("MQTT_PORT", "1883")),
        kuksa_host=_env("KUKSA_HOST", "127.0.0.1"),
        kuksa_port=int(_env("KUKSA_PORT", "55555")),
    )


@dataclass(frozen=True)
class UProtocol:
    authority: str          # uProtocol authority name of this vehicle/host
    zenoh_mode: str         # "peer" (default, finds others via multicast) or "client" (needs a router)
    zenoh_connect: tuple    # e.g. ("tcp/zenoh:7447",) — empty = rely on multicast scouting
    zenoh_listen: tuple
    vss_source_path: str    # VSS path the publisher forwards to the guardian topic


def _list(name: str) -> tuple:
    return tuple(s.strip() for s in _env(name, "").split(",") if s.strip())


def uprotocol() -> UProtocol:
    return UProtocol(
        authority=_env("UP_AUTHORITY", "rom-vehicle"),
        zenoh_mode=_env("ZENOH_MODE", "peer"),
        zenoh_connect=_list("ZENOH_CONNECT"),
        zenoh_listen=_list("ZENOH_LISTEN"),
        vss_source_path=_env("VSS_SOURCE_PATH", VSS_BATTERY_TEMP),
    )


@dataclass(frozen=True)
class Thresholds:
    warn_c: float
    crit_c: float
    hyst_c: float
    stale_ms: int
    stuck_s: float
    min_plausible_c: float
    max_plausible_c: float


def thresholds() -> Thresholds:
    """Guardian thresholds; defaults come from the contract, overridable via env."""
    return Thresholds(
        warn_c=float(_env("WARN_C", "45.0")),
        crit_c=float(_env("CRIT_C", "55.0")),
        hyst_c=float(_env("HYST_C", "2.0")),
        stale_ms=int(_env("STALE_MS", "2000")),
        stuck_s=float(_env("STUCK_S", "10")),
        min_plausible_c=float(_env("MIN_PLAUSIBLE_C", "-40")),
        max_plausible_c=float(_env("MAX_PLAUSIBLE_C", "150")),
    )
