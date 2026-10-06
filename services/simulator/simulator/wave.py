# Made with Claude (Claude Code, Anthropic)
"""Pure temperature wave, no I/O. Starts at min_c, peaks at max_c half a period later."""
import math


def sine_temp(t_s: float, period_s: float = 120.0, min_c: float = 30.0, max_c: float = 69.0) -> float:
    mid, amp = (max_c + min_c) / 2, (max_c - min_c) / 2
    return round(mid + amp * math.sin(2 * math.pi * t_s / period_s - math.pi / 2), 2)
