# Made with Claude Code (Anthropic, model Claude Opus 5.5) for the Eclipse SDV Hackathon
# Chapter Four (team RoM, "Doctor Whodunit" challenge), for competition purposes.
"""Battery Thermal Guardian - thermal-runaway early-warning state machine.

States: CLEAR -> MONITORING -> WARNING -> CRITICAL -> MITIGATING (-> CRITICAL if
mitigation fails), plus SENSOR_FAULT when the temperature signal is stale, stuck or out of range.

Run (from the repo root):
  python -m guardian.guardian            test scenario, offline, instant
  python -m guardian.guardian --kuksa    live: subscribe to battery temp on KUKSA
  make guardian                          databroker + sine-wave simulator + guardian in compose
"""
import os
import queue
import sys
import threading
import time

from common import jsonlog, kuksa
from common.contracts import CLEAR, CRITICAL, MONITORING, SENSOR_FAULT, VSS_BATTERY_TEMP, WARNING

MITIGATING = "MITIGATING"
TICK_S = 0.5

WARN_C = float(os.getenv("WARN_C", 38.0))
CRIT_C = float(os.getenv("CRIT_C", 45.0))
MIN_C, MAX_C = -40, 100
STALE_S = 2
STUCK_S = 10
MITIGATION_TIMEOUT_S = 5


class Guardian:
    def __init__(self):
        self.state = CLEAR
        self.temp = None
        self.last_rx = 0
        self.last_change = 0
        self.mitigation_since = 0
        self.mitigation_failed = False

    def update(self, now, temp):
        """Feed one tick (temp=None means no sample arrived). Returns (state, reason)."""
        if temp is not None:
            if temp != self.temp:
                self.last_change = now
            self.temp, self.last_rx = temp, now

        state, reason = self.next_state(now)
        if state == MITIGATING and self.state != MITIGATING:
            self.mitigation_since = now
        self.state = state
        return state, reason

    def next_state(self, now):
        if self.temp is None:
            return CLEAR, "no data yet"
        if now - self.last_rx > STALE_S:
            return SENSOR_FAULT, "stale signal"
        if now - self.last_change > STUCK_S:
            return SENSOR_FAULT, "stuck signal"
        if not MIN_C <= self.temp <= MAX_C:
            return SENSOR_FAULT, "out of range"
        if self.temp < WARN_C:
            self.mitigation_failed = False
            return MONITORING, "temp ok"
        if self.state == MITIGATING:
            if now - self.mitigation_since > MITIGATION_TIMEOUT_S:
                self.mitigation_failed = True
                return CRITICAL, "mitigation failed"
            return MITIGATING, "cooling in progress"
        if self.state == CRITICAL:
            if self.mitigation_failed:
                return CRITICAL, "mitigation failed"
            return MITIGATING, "cooling requested"
        if self.temp >= CRIT_C:
            return CRITICAL, "too hot"
        return WARNING, "getting hot"


# One temperature per second. None = sensor sent nothing. Small +-0.1 wiggle so it doesn't look stuck.
SCENARIO = (
    [25, 25.1] * 3                    # normal
    + [30, 35, 40, 43, 46, 48]        # heating up -> WARNING -> CRITICAL -> MITIGATING
    + [44, 40, 36, 30]                # cooled down -> MONITORING
    + [None] * 4                      # sensor dropout -> SENSOR_FAULT
    + [30, 30.1]                      # back to normal
    + [150]                           # implausible value -> SENSOR_FAULT
    + [30, 30.1]                      # back to normal
    + [42] * 12                       # stuck value -> SENSOR_FAULT
    + [30, 30.1]                      # back to normal
    + [46, 48, 50, 50.1] * 3          # stays hot -> mitigation fails -> CRITICAL
)


def show(g, t, temp):
    before = g.state
    state, reason = g.update(t, temp)
    mark = f"  <- {reason}" if state != before else ""
    print(f"{t:>6.1f}  {str(temp):>6}  {state}{mark}", flush=True)


def subscribe_temp(samples, log):
    """Push every temperature update into `samples`, reconnecting forever (stale while down)."""
    while True:
        try:
            client = kuksa.open_client()
            log.log("kuksa_connected", path=VSS_BATTERY_TEMP)
            for temp, _ in kuksa.subscribe_temp(client):
                samples.put(temp)
        except Exception as e:
            log.log("kuksa_error", error=repr(e))
        time.sleep(1)


def run_kuksa():
    log = jsonlog.get_logger("guardian")
    samples = queue.Queue()
    threading.Thread(target=subscribe_temp, args=(samples, log), daemon=True).start()
    g, start = Guardian(), time.monotonic()
    # Tick even without samples, otherwise a dead sensor would never be detected as stale.
    while True:
        try:
            temp = samples.get(timeout=TICK_S)
        except queue.Empty:
            temp = None
        before = g.state
        state, reason = g.update(time.monotonic() - start, temp)
        if state != before:
            log.log("state_change", **{"from": before}, to=state, reason=reason, temp_c=round(g.temp, 2))


if __name__ == "__main__":
    try:
        if "--kuksa" in sys.argv:
            run_kuksa()
        else:
            g = Guardian()
            print(f"{'time':>6}  {'temp':>6}  state")
            for t, temp in enumerate(SCENARIO):
                show(g, t, temp)
    except KeyboardInterrupt:
        pass
