# Made with Claude (Claude Code, Anthropic) — RoM "rom_uprotocol" library.
"""uProtocol settings from env. Never hardcode endpoints."""
import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _list(name: str) -> tuple:
    return tuple(s.strip() for s in _env(name, "").split(",") if s.strip())


@dataclass(frozen=True)
class UProtocolConfig:
    authority: str          # uProtocol authority name of this vehicle/host
    transport: str          # transport registered in rom_uprotocol.transport ("zenoh")
    zenoh_mode: str         # "peer" (default, finds others via multicast) or "client" (needs a router)
    zenoh_connect: tuple    # e.g. ("tcp/zenoh:7447",) — empty = rely on multicast scouting
    zenoh_listen: tuple


def uprotocol() -> UProtocolConfig:
    return UProtocolConfig(
        authority=_env("UP_AUTHORITY", "rom-vehicle"),
        transport=_env("UP_TRANSPORT", "zenoh"),
        zenoh_mode=_env("ZENOH_MODE", "peer"),
        zenoh_connect=_list("ZENOH_CONNECT"),
        zenoh_listen=_list("ZENOH_LISTEN"),
    )
