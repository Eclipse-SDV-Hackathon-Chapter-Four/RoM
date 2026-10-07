# Made with Claude (Claude Code, Anthropic) — shared RoM "rom_common" library, used by all components.
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
    imbalance_c: float      # hottest - coldest valid cell above this ...
    imbalance_s: float      # ... for this long -> cell_imbalance


def thresholds() -> Thresholds:
    """Guardian thresholds; defaults come from the contract, overridable via env."""
    return Thresholds(
        warn_c=float(_env("WARN_C", "38.0")),
        crit_c=float(_env("CRIT_C", "45.0")),
        hyst_c=float(_env("HYST_C", "2.0")),
        stale_ms=int(_env("STALE_MS", "2000")),
        stuck_s=float(_env("STUCK_S", "10")),
        min_plausible_c=float(_env("MIN_PLAUSIBLE_C", "-40")),
        max_plausible_c=float(_env("MAX_PLAUSIBLE_C", "150")),
        imbalance_c=float(_env("IMBALANCE_C", "10")),
        imbalance_s=float(_env("IMBALANCE_S", "2")),
    )


@dataclass(frozen=True)
class HeartbeatConfig:
    period_ms: int             # how often the client / producers beat
    stale_ms: int              # no beat for this long = component lost (below the data STALE_MS: root cause first)
    chip_timeout_ms: int       # adapter: no telemetry for this long = chip heartbeat goes to 0
    required: tuple            # components the guardian expects from the start (others count once first seen)


def heartbeat() -> HeartbeatConfig:
    required = tuple(c.strip() for c in _env("REQUIRED_HEARTBEATS", "uprotocol,databroker").split(",") if c.strip())
    return HeartbeatConfig(
        period_ms=int(_env("HEARTBEAT_PERIOD_MS", "500")),
        stale_ms=int(_env("HEARTBEAT_STALE_MS", "1500")),
        chip_timeout_ms=int(_env("CHIP_TIMEOUT_MS", "1500")),
        required=required,
    )
