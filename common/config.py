# Made with Claude (Claude Code, Anthropic) — shared RoM "common" module, used by all components.
"""Environment-driven configuration. Never hardcode IPs; see contracts/README.md."""
import os
from dataclasses import dataclass


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
