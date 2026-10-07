# Made with Claude Code (Anthropic, model Claude Opus 5.5) for the Eclipse SDV Hackathon
# Chapter Four (team RoM, "Doctor Whodunit" challenge), for competition purposes.
"""Battery Thermal Guardian - thermal-runaway early-warning state machine.

States: CLEAR -> MONITORING -> WARNING -> CRITICAL -> MITIGATING (-> CRITICAL if
mitigation fails), plus SENSOR_FAULT when the temperature signal is stale, stuck or out of range.

Input comes over uProtocol (rom_uprotocol, Zenoh) from the VSS uProtocol Client, never from the
KUKSA Databroker directly (challenge architecture rule): KUKSA -> vss-uprotocol-client -> guardian.

Run:
  rom-guardian              test scenario, offline, instant   (or: python -m guardian.guardian)
  rom-guardian --uprotocol  live: battery temp from up://<UP_AUTHORITY>/1001/1/8001
  rom-guardian --fault-events  test scenario as DFM fault events (JSON lines, services/dfm/fixtures)
  make guardian             databroker + simulator + vss-uprotocol-client + guardian in compose
"""
import os
import queue
import signal
import sys
import threading
import time

from rom_common import clock, config, jsonlog
from rom_common.contracts import (CLEAR, CRITICAL, FAILED, FAULT_MITIGATION_FAILED, FAULT_OUT_OF_RANGE,
                                  FAULT_OVER_TEMP_CRITICAL, FAULT_OVER_TEMP_WARNING, FAULT_SIGNAL_STALE,
                                  FAULT_SIGNAL_STUCK, MONITORING, PASSED, QOS_DISPLAY_CMD, QOS_GUARDIAN_FAULT,
                                  SENSOR_FAULT, TOPIC_DISPLAY_CMD, TOPIC_GUARDIAN_FAULT, WARNING, build_display_cmd,
                                  build_fault_event)

MITIGATING = "MITIGATING"
DISPLAY_PERIOD_S = 1.0  # re-publish the display command this often: fresh temp_c, and proof the guardian is alive
TICK_S = 0.5

# Thresholds come from rom_common.config (env: WARN_C, CRIT_C, STALE_MS, STUCK_S, MIN/MAX_PLAUSIBLE_C),
# the same values the vss-uprotocol-client uses for the message TTL.
_T = config.thresholds()
WARN_C, CRIT_C = _T.warn_c, _T.crit_c
MIN_C, MAX_C = _T.min_plausible_c, _T.max_plausible_c
STALE_S = _T.stale_ms / 1000
STUCK_S = _T.stuck_s
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
    + [200]                           # implausible value -> SENSOR_FAULT
    + [30, 30.1]                      # back to normal
    + [42] * 12                       # stuck value -> SENSOR_FAULT
    + [30, 30.1]                      # back to normal
    + [46, 48, 50, 50.1] * 3          # stays hot -> mitigation fails -> CRITICAL
)


SENSOR_FAULTS = {"stale signal": FAULT_SIGNAL_STALE, "stuck signal": FAULT_SIGNAL_STUCK,
                 "out of range": FAULT_OUT_OF_RANGE}


def active_faults(state, reason):
    """DFM faults that are Failed while the guardian is in (state, reason)."""
    if state == WARNING:
        return frozenset({FAULT_OVER_TEMP_WARNING})
    if state in (CRITICAL, MITIGATING):
        failed = {FAULT_MITIGATION_FAILED} if reason == "mitigation failed" else set()
        return frozenset({FAULT_OVER_TEMP_CRITICAL} | failed)
    if state == SENSOR_FAULT:
        return frozenset({SENSOR_FAULTS[reason]})
    return frozenset()


def fault_changes(old, new):
    """[(fault, stage)]: Passed for the faults that cleared, then Failed for the new ones."""
    return [(f, PASSED) for f in sorted(old - new)] + [(f, FAILED) for f in sorted(new - old)]


def scenario_fault_events():
    """SCENARIO as fault event payloads, scenario time as ts_ms and seq (deterministic: DFM test fixture)."""
    g, active = Guardian(), frozenset()
    for t, temp in enumerate(SCENARIO):
        state, reason = g.update(t, temp)
        new = active_faults(state, reason)
        for fault, stage in fault_changes(active, new):
            yield build_fault_event(fault, stage, t * 1000, g.temp, reason, t, None)
        active = new


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
    from rom_uprotocol import uris
    from rom_uprotocol.subscriber import UpSignalSource
    from rom_uprotocol.transport import make_transport

    transport = make_transport(uris.guardian_uri())
    status = UpSignalSource(transport, samples.put, lambda reason: log.log("rejected", reason=reason)).start()
    log.log("subscribed", zenoh_key=status.message)
    return transport


def run_uprotocol():
    log = jsonlog.get_logger("guardian")
    samples = queue.Queue()
    transport = subscribe_temp(samples, log)  # keep a reference, or the Zenoh session is closed
    from rom_common import mqtt  # only the live mode needs paho
    display = mqtt.MqttClient(f"rom-guardian-{os.getpid()}").connect()  # display commands for the device OLED
    try:
        loop(samples, log, display)
    finally:
        display.close()
        transport.close_sync()  # an open Zenoh session keeps the process alive after SIGTERM
        log.log("stopped")


def loop(samples, log, display=None):
    g, start = Guardian(), time.monotonic()
    last = None  # last uProtocol sample: its msg_id/seq link a state change to the message that caused it
    display_seq, last_display = 0, 0.0
    active = frozenset()  # faults currently Failed in the DFM
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
        new = active_faults(state, reason)
        for fault, stage in fault_changes(active, new):
            temp_c = round(g.temp, 2)
            seq, msg_id = (last.seq, last.msg_id) if last else (None, None)
            log.log("fault", fault=fault, stage=stage, reason=reason, temp_c=temp_c, seq=seq, msg_id=msg_id)
            if display is not None:  # same MQTT client as the display command
                display.publish(TOPIC_GUARDIAN_FAULT,
                                build_fault_event(fault, stage, clock.now_ms(), temp_c, reason, seq, msg_id),
                                qos=QOS_GUARDIAN_FAULT)
        active = new
        # State shown on the device display (QoS 1, retained): on every change and as a heartbeat.
        now = time.monotonic()
        if display is not None and (state != before or now - last_display >= DISPLAY_PERIOD_S):
            display_seq, last_display = display_seq + 1, now
            display.publish(TOPIC_DISPLAY_CMD, display_cmd(state, g.temp, reason, display_seq, clock.now_ms()),
                            qos=QOS_DISPLAY_CMD, retain=True)


def _interrupt(*_):
    raise KeyboardInterrupt  # podman / Ankaios stop the workload with SIGTERM


def main():
    signal.signal(signal.SIGTERM, _interrupt)
    try:
        if "--uprotocol" in sys.argv:
            run_uprotocol()
        elif "--fault-events" in sys.argv:
            for event in scenario_fault_events():
                print(event)
        else:
            g = Guardian()
            print(f"{'time':>6}  {'temp':>6}  state")
            for t, temp in enumerate(SCENARIO):
                show(g, t, temp)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
