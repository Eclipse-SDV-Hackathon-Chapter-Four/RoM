# Made with Claude (Claude Code, Anthropic) — shared RoM "rom_common" library, used by all components.
"""Shared building blocks for every RoM component (adapter, simulator, guardian, vss-uprotocol-client).

Install:  pip install ./libs/rom-common            (extras: [kuksa], [mqtt])

    from rom_common import config, contracts, jsonlog, clock
"""
from . import clock, config, contracts, jsonlog  # noqa: F401

__all__ = ["clock", "config", "contracts", "jsonlog"]
