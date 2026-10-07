# Made with Claude (Claude Code, Anthropic)
"""Which components of the chain are gone? Fed with heartbeats, answers with the root cause first.

Required components (REQUIRED_HEARTBEATS, default uprotocol + databroker) count as lost if they never beat after a
start-up grace period; any other component (chip, adapter, simulator) is tracked from its first beat on.
A component that reports status "down" is lost at once (the client keeps beating for a dead databroker).

When the uProtocol link comes back after an outage, the other components' beats come through it too and need up to one
period to arrive: they are not blamed for HEARTBEAT_STALE_MS after the link returned (no flicker of root causes).

The same holds when the link goes: every beat stops at once, but the one that happened to arrive first goes stale
first (e.g. the databroker's, a fraction of a period before the link's own). So a silent component behind the link is
only blamed once the link has beaten after that component's deadline, i.e. the link is proven alive; until then the
link itself is the suspect. Costs at most one heartbeat period on a real silent component.
(Found by the evidence collector: uprotocol_heartbeat_loss raised databroker_down for 500 ms before uprotocol_lost.)
"""
from typing import Dict, Iterable, List, Tuple

from rom_common.contracts import COMPONENT_UPROTOCOL, HB_DOWN, HB_OK, HEARTBEAT_DIAGNOSIS_ORDER

STARTUP_GRACE_S = 5.0   # Zenoh may need a few seconds to connect the guardian to the client


class HeartbeatMonitor:
    def __init__(self, required: Iterable[str], stale_s: float, start: float = 0.0, grace_s: float = STARTUP_GRACE_S):
        self._required = tuple(required)
        self._stale_s = stale_s
        self._start = start
        self._grace_s = grace_s
        self._last: Dict[str, Tuple[float, str]] = {}   # component -> (time of last beat, status)
        self._link_back_at = None   # when the uProtocol link last came back (or first appeared)

    def beat(self, now: float, component: str, status: str = HB_OK) -> None:
        if component == COMPONENT_UPROTOCOL:
            prev = self._last.get(component)
            if prev is None or prev[1] == HB_DOWN or now - prev[0] > self._stale_s:
                self._link_back_at = now
        self._last[component] = (now, status)

    def lost(self, now: float) -> List[str]:
        """Lost components, closest to the guardian first (uprotocol, databroker, adapter, simulator, chip)."""
        gone = set()
        settling = self._link_back_at is not None and now - self._link_back_at <= self._stale_s
        link = self._last.get(COMPONENT_UPROTOCOL)
        for component in set(self._required) | set(self._last):
            seen = self._last.get(component)
            if settling and component != COMPONENT_UPROTOCOL and seen is not None and seen[1] != HB_DOWN:
                continue   # the link just came back: this component's beat is on its way
            if seen is None:
                if now - self._start > max(self._grace_s, self._stale_s):
                    gone.add(component)
            elif seen[1] == HB_DOWN:
                gone.add(component)
            elif now - seen[0] > self._stale_s:
                link_unproven = (component != COMPONENT_UPROTOCOL and link is not None and link[1] != HB_DOWN
                                 and now - link[0] <= self._stale_s and link[0] <= seen[0] + self._stale_s)
                if not link_unproven:   # silent, and the link has carried beats since its deadline: its own fault
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
