# Made with Claude (Claude Code, Anthropic)
"""Which components of the chain are gone? Fed with heartbeats, answers with the root cause first.

Required components (REQUIRED_HEARTBEATS, default uprotocol + databroker) count as lost if they never beat after a
start-up grace period; any other component (chip, adapter, simulator) is tracked from its first beat on.
A component that reports status "down" is lost at once (the client keeps beating for a dead databroker).
"""
from typing import Dict, Iterable, List, Tuple

from rom_common.contracts import HB_DOWN, HB_OK, HEARTBEAT_DIAGNOSIS_ORDER

STARTUP_GRACE_S = 5.0   # Zenoh may need a few seconds to connect the guardian to the client


class HeartbeatMonitor:
    def __init__(self, required: Iterable[str], stale_s: float, start: float = 0.0, grace_s: float = STARTUP_GRACE_S):
        self._required = tuple(required)
        self._stale_s = stale_s
        self._start = start
        self._grace_s = grace_s
        self._last: Dict[str, Tuple[float, str]] = {}   # component -> (time of last beat, status)

    def beat(self, now: float, component: str, status: str = HB_OK) -> None:
        self._last[component] = (now, status)

    def lost(self, now: float) -> List[str]:
        """Lost components, closest to the guardian first (uprotocol, databroker, adapter, simulator, chip)."""
        gone = set()
        for component in set(self._required) | set(self._last):
            seen = self._last.get(component)
            if seen is None:
                if now - self._start > max(self._grace_s, self._stale_s):
                    gone.add(component)
            elif seen[1] == HB_DOWN or now - seen[0] > self._stale_s:
                gone.add(component)
        order = {c: i for i, c in enumerate(HEARTBEAT_DIAGNOSIS_ORDER)}
        return sorted(gone, key=lambda c: (order.get(c, len(order)), c))

    def status(self, now: float) -> Dict[str, str]:
        """component -> ok | down | lost | waiting (required, not heard from yet, still in the grace period)."""
        gone = set(self.lost(now))
        out = {}
        for c in sorted(set(self._required) | set(self._last)):
            seen = self._last.get(c)
            if c not in gone:
                out[c] = HB_OK if seen is not None else "waiting"
            else:
                out[c] = HB_DOWN if seen is not None and seen[1] == HB_DOWN else "lost"
        return out
