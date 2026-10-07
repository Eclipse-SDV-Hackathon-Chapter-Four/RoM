# Made with Claude (Claude Code, Anthropic)
"""Pure temperature wave, no I/O. Starts at min_c, peaks at max_c half a period later."""
import math
import random


def sine_temp(t_s: float, period_s: float = 120.0, min_c: float = 30.0, max_c: float = 69.0) -> float:
    mid, amp = (max_c + min_c) / 2, (max_c - min_c) / 2
    return round(mid + amp * math.sin(2 * math.pi * t_s / period_s - math.pi / 2), 2)


def cell_offsets(seed: int, n_cells: int = 4) -> list:
    """Fixed °C offset of each cell below the pack wave. Cell 1 is always the hottest (offset 0), the others
    are 1.0-1.5 °C apart; the seed only shuffles the small gaps, so a run is replayable."""
    rng = random.Random(seed)
    return [0.0] + [-(i + rng.uniform(0.0, 0.5)) for i in range(1, n_cells)]


def cell_temps(t_s: float, offsets: list, period_s: float = 120.0, min_c: float = 30.0, max_c: float = 69.0) -> list:
    """Temperature of every cell at time t_s (index 0 = cell 1)."""
    base = sine_temp(t_s, period_s, min_c, max_c)
    return [round(base + off, 2) for off in offsets]
