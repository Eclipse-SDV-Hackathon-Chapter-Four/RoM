# Made with Claude (Claude Code, Anthropic)
"""Cooling: the simulated pack reacts to the guardian's mitigation, so a campaign can show that cooling works.

The simulator plays the cooling actuator. It listens to the guardian state (up://<UP_AUTHORITY>/1002/1/8006) and,
while the guardian is MITIGATING, removes heat from every simulated cell at SIM_COOLING_C_PER_S (default 3 °C/s).
The removed heat is an offset on the wave, applied before the faults: a stuck or out-of-range sensor does not see the
cooling, and a drift keeps heating on top of it. Without cooling the offset relaxes back to 0 at
SIM_COOLING_RELAX_C_PER_S (default 0.2 °C/s, the pack warming up to ambient again). A new run (POST /run) resets it.

The guardian gives cooling MITIGATION_TIMEOUT_S (5 s) to bring the hottest cell below WARN_C (38 °C), from
CRIT_C (45 °C) and against the drift of a thermal-runaway campaign (0.7 °C/s): 3 °C/s makes it in about 3 s.
A command older than COMMAND_TTL_S counts as gone (guardian silent = no cooling request).
"""
import threading
import time
from typing import Callable, Optional

COOLING_STATE = "MITIGATING"
COMMAND_TTL_S = 2.5        # the guardian repeats its state every second


class Cooling:
    def __init__(self, rate_c_per_s: float = 3.0, relax_c_per_s: float = 0.2,
                 clock: Callable[[], float] = time.monotonic):
        self.rate, self.relax, self._clock = rate_c_per_s, relax_c_per_s, clock
        self._lock = threading.Lock()
        self._requested_at: Optional[float] = None
        self._offset = 0.0           # °C, <= 0
        self._last: Optional[float] = None

    def on_state(self, state: str) -> None:
        """Guardian state update (from the uProtocol thread)."""
        with self._lock:
            self._requested_at = self._clock() if state == COOLING_STATE else None

    def active(self) -> bool:
        with self._lock:
            return self._active(self._clock())

    def _active(self, now: float) -> bool:
        return self._requested_at is not None and now - self._requested_at <= COMMAND_TTL_S

    def step(self) -> float:
        """Advance to now and return the offset (°C, <= 0) to add to every simulated cell. Call once per sample."""
        with self._lock:
            now = self._clock()
            dt = 0.0 if self._last is None else max(0.0, now - self._last)
            self._last = now
            if self._active(now):
                self._offset -= self.rate * dt
            else:
                self._offset = min(0.0, self._offset + self.relax * dt)
            return round(self._offset, 2)

    def reset(self) -> None:
        with self._lock:
            self._requested_at, self._offset, self._last = None, 0.0, None


def subscribe(cooling: Cooling, log):
    """Feed the guardian state into `cooling`. Returns the transport (keep it, or the Zenoh session closes)."""
    from rom_uprotocol import uris
    from rom_uprotocol.subscriber import UpStateSource
    from rom_uprotocol.transport import make_transport

    transport = make_transport(uris.simulator_uri())
    status = UpStateSource(transport, lambda e: cooling.on_state(e.state),
                           lambda reason: log.log("rejected", reason=reason)).start()
    log.log("cooling_subscribed", zenoh_key=status.message, rate_c_per_s=cooling.rate, relax_c_per_s=cooling.relax)
    return transport
