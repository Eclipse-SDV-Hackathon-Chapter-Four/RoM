# Made with Claude (Claude Code, Anthropic) — shared RoM "rom_common" library, used by all components.
"""Time helpers. All timestamps in RoM are integer milliseconds since the Unix epoch."""
import time


def now_ms() -> int:
    return int(time.time() * 1000)


def monotonic_ms() -> int:
    """Use for measuring durations (STALE / STUCK) — immune to wall-clock jumps."""
    return int(time.monotonic() * 1000)
