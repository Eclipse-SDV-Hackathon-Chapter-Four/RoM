# Made with Claude Code (Anthropic, model Claude Opus 5.5) for the Eclipse SDV Hackathon
# Chapter Four (team RoM, "Doctor Whodunit" challenge), for competition purposes.
"""Battery Thermal Guardian - thermal-runaway early-warning state machine.

States: CLEAR -> MONITORING -> WARNING -> CRITICAL -> MITIGATING (-> CRITICAL if
mitigation fails), plus SENSOR_FAULT when the temperature signal is stale, stuck or out of range.

Input comes over uProtocol (Zenoh) from the VSS uProtocol Publisher, never from the KUKSA
Databroker directly (challenge architecture rule): KUKSA -> vss_uprotocol.publisher -> guardian.

Run (from the repo root):
  python -m guardian.guardian              test scenario, offline, instant
  python -m guardian.guardian --uprotocol  live: battery temp from up://<UP_AUTHORITY>/1001/1/8001
  make guardian                            databroker + simulator + publisher + guardian in compose
"""
import os
import queue
import sys
import threading
import time

from common import clock, jsonlog
from common.contracts import (CLEAR, CRITICAL, MONITORING, QOS_DISPLAY_CMD, SENSOR_FAULT, TOPIC_DISPLAY_CMD, WARNING,
                              build_display_cmd)

MITIGATING = "MITIGATING"
DISPLAY_PERIOD_S = 1.0  # re-publish the display command this often: fresh temp_c, and proof the guardian is alive
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


def display_cmd(state, temp, reason, seq, ts_ms):
    """Payload for TOPIC_DISPLAY_CMD. MITIGATING is not a contract state, so it is shown as CRITICAL;
    the reason ("cooling requested" / "cooling in progress") still says what is going on."""
    shown = CRITICAL if state == MITIGATING else state
    return build_display_cmd(shown, None if temp is None else round(temp, 2), reason, seq, ts_ms)


def subscribe_temp(samples, log):
    """Push every uProtocol sample into `samples`. Zenoh reconnects on its own (stale while down)."""
    from vss_uprotocol import topics
    from vss_uprotocol.subscriber import UpSignalSource
    from vss_uprotocol.zenoh_transport import ZenohTransport

    transport = ZenohTransport(topics.guardian_uri())
    status = UpSignalSource(transport, samples.put, lambda reason: log.log("rejected", reason=reason)).start()
    log.log("subscribed", zenoh_key=status.message)
    return transport


def run_uprotocol():
    log = jsonlog.get_logger("guardian")
    samples = queue.Queue()
    _transport = subscribe_temp(samples, log)  # keep a reference, or the Zenoh session is closed
    g, start = Guardian(), time.monotonic()
    last = None  # last uProtocol sample: its msg_id/seq link a state change to the message that caused it
    from common import mqtt  # only the live mode needs paho
    display = mqtt.MqttClient(f"rom-guardian-{os.getpid()}").connect()
    display_seq, last_display = 0, 0.0
    # Tick even without samples, otherwise a dead sensor would never be detected as stale.
    while True:
        try:
            last = samples.get(timeout=TICK_S)
            temp = last.value
        except queue.Empty:
            temp = None
        before = g.state
        state, reason = g.update(time.monotonic() - start, temp)
        if state != before:
            log.log("state_change", **{"from": before}, to=state, reason=reason, temp_c=round(g.temp, 2),
                    seq=last.seq if last else None, msg_id=last.msg_id if last else None)
        # State shown on the device display (QoS 1, retained): on every change and as a heartbeat.
        now = time.monotonic()
        if state != before or now - last_display >= DISPLAY_PERIOD_S:
            display_seq, last_display = display_seq + 1, now
            display.publish(TOPIC_DISPLAY_CMD, display_cmd(state, g.temp, reason, display_seq, clock.now_ms()),
                            qos=QOS_DISPLAY_CMD, retain=True)


if __name__ == "__main__":
    try:
        if "--uprotocol" in sys.argv:
            run_uprotocol()
        else:
            g = Guardian()
            print(f"{'time':>6}  {'temp':>6}  state")
            for t, temp in enumerate(SCENARIO):
                show(g, t, temp)
    except KeyboardInterrupt:
        pass
