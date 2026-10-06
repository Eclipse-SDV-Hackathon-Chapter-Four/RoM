# Made with Claude (Claude Code, Anthropic) — shared RoM "common" module, used by all components.
"""Shared building blocks for every RoM component (adapter, simulator, guardian).

Usage (run from the repo root, or put the repo root on PYTHONPATH):

    from common import config, contracts, jsonlog, clock
"""
from . import clock, config, contracts, jsonlog  # noqa: F401

__all__ = ["clock", "config", "contracts", "jsonlog"]
