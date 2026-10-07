# Made with Claude Code (Anthropic, model Claude Opus 5.5) for the Eclipse SDV Hackathon
# Chapter Four (team RoM, "Doctor Whodunit" challenge), for competition purposes.
"""Battery Thermal Guardian - thermal-runaway early-warning state machine over 4 battery cells.

States: CLEAR -> MONITORING -> WARNING -> CRITICAL -> MITIGATING (-> CRITICAL if mitigation fails),
plus SENSOR_FAULT when no cell can be trusted (whole stream stale, or every cell stale / stuck / out of range).

Every cell is monitored on its own. A bad cell sensor raises its own DFM fault and is left out; the
thermal state machine keeps running on the max of the healthy cells, so one bad sensor never disarms
the warning. Faults go out as FAILED / PASSED edges on up://<UP_AUTHORITY>/1002/1/8003 (DFM reporter input).

Input comes over uProtocol (rom_uprotocol, Zenoh) from the VSS uProtocol Client, never from the
KUKSA Databroker directly (challenge architecture rule): KUKSA -> vss-uprotocol-client -> guardian.

Run:
  rom-guardian              test scenario, offline, instant   (or: python -m guardian.guardian)
  rom-guardian --fault-events  test scenario as fault events (services/dfm/fixtures/guardian_events.jsonl)
  rom-guardian --uprotocol  live: cells from up://<UP_AUTHORITY>/1001/1/8002, faults to .../1002/1/8003
  make guardian             databroker + simulator + vss-uprotocol-client + guardian in compose
"""
import os
import queue
import signal
import sys
import threading
import time
from dataclasses import asdict
from types import SimpleNamespace

from typing import Dict, List, Mapping, Optional, Tuple, Union

from rom_common import clock, config, contracts, jsonlog
from rom_common.contracts import (CLEAR, CRITICAL, MONITORING, N_CELLS, QOS_DISPLAY_CMD, SENSOR_FAULT, TOPIC_DISPLAY_CMD,
                                  WARNING, build_display_cmd)

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
IMBALANCE_C, IMBALANCE_S = _T.imbalance_c, _T.imbalance_s
MITIGATION_TIMEOUT_S = 5

# Human-readable reason per cell fault kind (also the SENSOR_FAULT reason when every cell has that fault).
CELL_REASONS = {"signal_stale": "stale signal", "signal_stuck": "stuck signal", "out_of_range": "out of range"}
PACK_REASONS = {
    contracts.FAULT_OVER_TEMP_WARNING: "getting hot",
    contracts.FAULT_OVER_TEMP_CRITICAL: "too hot",
    contracts.FAULT_MITIGATION_FAILED: "mitigation failed",
    contracts.FAULT_SIGNAL_STALE: "stale signal",
    contracts.FAULT_CELL_IMBALANCE: "cell imbalance",
}
THERMAL_FAULTS = (contracts.FAULT_OVER_TEMP_WARNING, contracts.FAULT_OVER_TEMP_CRITICAL,
                  contracts.FAULT_MITIGATION_FAILED)


class CellMonitor:
    """One cell sensor: last value, when it last arrived and when it last changed."""

    def __init__(self):
        self.value: Optional[float] = None
        self.last_rx = 0.0
        self.last_change = 0.0

    def feed(self, now: float, value: float) -> None:
        if value != self.value:
            self.last_change = now
        self.value, self.last_rx = value, now

    def fault(self, now: float, stream_start: float) -> Optional[str]:
        """Fault kind (contracts.CELL_FAULT_KINDS) or None. A cell that never arrived is stale after STALE_S."""
        if self.value is None:
            return "signal_stale" if now - stream_start > STALE_S else None
        if now - self.last_rx > STALE_S:
            return "signal_stale"
        if not MIN_C <= self.value <= MAX_C:
            return "out_of_range"   # before stuck: a pinned 200 °C is out of range, not just stuck
        if now - self.last_change > STUCK_S:
            return "signal_stuck"
        return None


class Guardian:
    def __init__(self, n_cells: int = N_CELLS):
        self.cells = {c: CellMonitor() for c in range(1, n_cells + 1)}
        self.state = CLEAR
        self.temp: Optional[float] = None       # pack temperature: max of the valid cells (last known)
        self.hottest: Optional[int] = None      # cell that set self.temp
        self.first_rx: Optional[float] = None
        self.last_rx = 0.0
        self.mitigation_since = 0
        self.mitigation_failed = False
        self.imbalance_since: Optional[float] = None
        self.cell_faults: Dict[int, Optional[str]] = {}
        self.faults: Dict[str, Optional[int]] = {}   # active DFM fault code -> cell (None for pack faults)

    def update(self, now, cells: Union[Mapping[int, float], float, None]):
        """Feed one tick. cells = {cell: °C} of one message, None = nothing arrived, a number = all cells
        (single-sensor input, e.g. the offline scenario). Returns (state, reason); self.faults is updated."""
        if isinstance(cells, (int, float)):
            cells = dict.fromkeys(self.cells, float(cells))
        if cells:
            for c, value in cells.items():
                if c in self.cells:
                    self.cells[c].feed(now, value)
            self.last_rx = now
            if self.first_rx is None:
                self.first_rx = now

        stale_stream = self.first_rx is not None and now - self.last_rx > STALE_S
        self.cell_faults = {} if stale_stream or self.first_rx is None else {
            c: m.fault(now, self.first_rx) for c, m in self.cells.items()}
        valid = {c: m.value for c, m in self.cells.items()
                 if m.value is not None and not stale_stream and self.cell_faults.get(c) is None}
        if valid:
            self.hottest = max(valid, key=valid.get)
            self.temp = valid[self.hottest]

        state, reason = self.next_state(now, stale_stream, valid)
        if state == MITIGATING and self.state != MITIGATING:
            self.mitigation_since = now
        self.state = state
        self.faults = self.active_faults(now, stale_stream, valid)
        return state, reason

    def next_state(self, now, stale_stream: bool = False, valid: Optional[Dict[int, float]] = None):
        if self.first_rx is None:
            return CLEAR, "no data yet"
        if stale_stream:
            return SENSOR_FAULT, "stale signal"
        if not valid:
            kinds = {k for k in self.cell_faults.values() if k}
            return SENSOR_FAULT, CELL_REASONS[kinds.pop()] if len(kinds) == 1 else "no valid cell"
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

    def active_faults(self, now, stale_stream: bool, valid: Dict[int, float]) -> Dict[str, Optional[int]]:
        """DFM codes that are failing right now. While the input cannot be judged the earlier codes keep their
        state: no data is not the same as "cooled down" or "sensor repaired" (whole stream stale: every code;
        no valid cell: the thermal codes)."""
        if self.first_rx is None:
            return {}
        if stale_stream:
            return {**self.faults, contracts.FAULT_SIGNAL_STALE: None}
        active: Dict[str, Optional[int]] = {
            contracts.cell_fault(c, kind): c for c, kind in self.cell_faults.items() if kind}
        if not valid:
            active.update({c: cell for c, cell in self.faults.items() if c in THERMAL_FAULTS})
            self.imbalance_since = None
            return active
        if self.temp >= WARN_C:
            active[contracts.FAULT_OVER_TEMP_WARNING] = self.hottest
        if self.temp >= CRIT_C:
            active[contracts.FAULT_OVER_TEMP_CRITICAL] = self.hottest
        if self.state == CRITICAL and self.mitigation_failed:
            active[contracts.FAULT_MITIGATION_FAILED] = self.hottest
        if len(valid) >= 2 and max(valid.values()) - min(valid.values()) > IMBALANCE_C:
            self.imbalance_since = now if self.imbalance_since is None else self.imbalance_since
            if now - self.imbalance_since >= IMBALANCE_S:
                active[contracts.FAULT_CELL_IMBALANCE] = self.hottest
        else:
            self.imbalance_since = None
        return active

    def cells_text(self) -> str:
        """All cell values for the DFM environment data: "31.2,30.1,,29.9" (empty = never arrived)."""
        return ",".join("" if m.value is None else f"{m.value:g}" for _, m in sorted(self.cells.items()))


def fault_edges(before: Mapping[str, Optional[int]], after: Mapping[str, Optional[int]]) -> List[Tuple[str, str, Optional[int]]]:
    """(code, FAILED / PASSED, cell) for every fault that started or ended, in a stable order."""
    started = [(code, "FAILED", after[code]) for code in sorted(after) if code not in before]
    ended = [(code, "PASSED", before[code]) for code in sorted(before) if code not in after]
    return ended + started


def fault_reason(code: str) -> str:
    return PACK_REASONS.get(code) or CELL_REASONS[code.rsplit(".", 1)[1]]


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


def subscribe_cells(samples, log):
    """Push every cell message into `samples`. Zenoh reconnects on its own (stale while down)."""
    from rom_uprotocol import uris
    from rom_uprotocol.subscriber import UpCellsSource
    from rom_uprotocol.transport import make_transport

    transport = make_transport(uris.guardian_uri())
    status = UpCellsSource(transport, samples.put, lambda reason: log.log("rejected", reason=reason)).start()
    log.log("subscribed", zenoh_key=status.message)
    return transport


def fault_publisher(transport, log):
    """FAILED / PASSED edges on up://<authority>/1002/1/8003 for the DFM reporter (no TTL: an edge never expires)."""
    from rom_uprotocol import uris
    from rom_uprotocol.publisher import SignalPublisher

    return SignalPublisher(transport.send_sync, uris.guardian_fault_topic(), ttl_ms=0, log=log)


def run_uprotocol():
    log = jsonlog.get_logger("guardian")
    samples = queue.Queue()
    transport = subscribe_cells(samples, log)  # keep a reference, or the Zenoh session is closed
    faults_out = fault_publisher(transport, log)
    from rom_common import mqtt  # only the live mode needs paho
    display = mqtt.MqttClient(f"rom-guardian-{os.getpid()}").connect()  # display commands for the device OLED
    try:
        loop(samples, log, display, faults_out)
    finally:
        display.close()
        transport.close_sync()  # an open Zenoh session keeps the process alive after SIGTERM
        log.log("stopped")


def fault_events(g: Guardian, before: Mapping[str, Optional[int]], last, ts_ms: int):
    """FaultEvent for every fault edge since `before`."""
    from rom_uprotocol.contract import FaultEvent

    return [FaultEvent(code=code, stage=stage, ts_ms=ts_ms, cell=cell,
                       temp_c=None if g.temp is None else round(g.temp, 2), cells=g.cells_text(),
                       reason=fault_reason(code) if stage == "FAILED" else "cleared",
                       seq=last.seq if last else None, msg_id=last.msg_id if last else None,
                       run_id=last.run_id if last else None)
            for code, stage, cell in fault_edges(before, g.faults)]


def scenario_fault_events() -> List[str]:
    """SCENARIO as fault event JSON lines (ts_ms = scenario second * 1000): services/dfm/fixtures input."""
    from rom_uprotocol.contract import build_fault_event

    g, lines = Guardian(), []
    for t, temp in enumerate(SCENARIO):
        before = g.faults
        g.update(t, temp)
        last = SimpleNamespace(seq=t, msg_id=None, run_id=None)
        lines += [build_fault_event(e).decode() for e in fault_events(g, before, last, t * 1000)]
    return lines


def report_faults(g: Guardian, before: Mapping[str, Optional[int]], last, log, publisher=None) -> None:
    """Log every fault edge as fault_event and, live, publish it for the DFM."""
    from rom_uprotocol.contract import build_fault_event

    for event in fault_events(g, before, last, clock.now_ms()):
        code, stage = event.code, event.stage
        log.log("fault_event", **asdict(event))
        if publisher is not None:
            publisher.publish_json(lambda seq, ts, e=event: build_fault_event(e), code=code, stage=stage)


def loop(samples, log, display=None, faults_out=None):
    g, start = Guardian(), time.monotonic()
    last = None  # last cell message: its msg_id/seq/run_id link a state change or fault to the message behind it
    display_seq, last_display = 0, 0.0
    # Tick even without samples, otherwise a dead sensor would never be detected as stale.
    while True:
        try:
            last = samples.get(timeout=TICK_S)
            cells = last.cells
        except queue.Empty:
            cells = None
        before, faults_before = g.state, g.faults
        state, reason = g.update(time.monotonic() - start, cells)
        if state != before:
            log.log("state_change", **{"from": before}, to=state, reason=reason,
                    temp_c=None if g.temp is None else round(g.temp, 2), cell=g.hottest, cells=g.cells_text(),
                    seq=last.seq if last else None, msg_id=last.msg_id if last else None,
                    run_id=last.run_id if last else None)
        if g.faults != faults_before:
            report_faults(g, faults_before, last, log, faults_out)
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
            print("\n".join(scenario_fault_events()))
        else:
            g = Guardian()
            print(f"{'time':>6}  {'temp':>6}  state")
            for t, temp in enumerate(SCENARIO):
                show(g, t, temp)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
