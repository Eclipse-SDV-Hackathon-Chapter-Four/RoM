# Made with Claude (Claude Code, Anthropic)
"""Correlator: groups the bus messages of one campaign run, checks OpenSOVD, judges and saves the evidence record.

    campaign_start      open a Window (a still-open one is closed first: its END never came, and both runs are
                        marked as interfering with each other)
    fault_injected      t0 of the run; the guardian state at that moment is the run's precondition
    guardian fault      FAILED of an expected code -> poll OpenSOVD until the DTC shows up for this run
    guardian state      kept when the state or the reason changes; the latest one is always known
    campaign_end        wait GRACE_MS for late messages and the OpenSOVD checks, then close
    tick()              drives the OpenSOVD polls and the closing (call it every few hundred ms)

One campaign runs at a time (the fault-injector runs them one after another), so one window is enough. Messages of
another campaign seen while a window is open mark it as contaminated (INCONCLUSIVE, see verdict.py). Time limits
use the collector's clock (`now`), latencies the timestamps in the messages.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from rom_common import clock

from .verdict import Observed, judge

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")   # run_id becomes part of file names


def record_id(run_id: str, start_ts_ms: int) -> str:
    """One record per execution: thermal-runaway-01@20261007T120501.123Z (reruns keep their run_id)."""
    at = datetime.fromtimestamp(start_ts_ms / 1000, timezone.utc)
    return f"{run_id}@{at:%Y%m%dT%H%M%S}.{start_ts_ms % 1000:03d}Z"


@dataclass
class Window:
    run_id: str
    start: dict
    start_ts: int
    first_line: int
    last_line: int
    opened_at: int                                   # collector clock
    injected: List[dict] = field(default_factory=list)
    end: Optional[dict] = None
    end_seen_at: Optional[int] = None                # collector clock
    faults: List[dict] = field(default_factory=list)
    states: List[dict] = field(default_factory=list)
    state_at_injection: Optional[str] = None
    pending: Dict[str, int] = field(default_factory=dict)       # code -> FAILED seen at (collector clock)
    diagnostics: Dict[str, dict] = field(default_factory=dict)
    interference: List[str] = field(default_factory=list)      # other run_ids seen while this window was open
    context_lines: List[int] = field(default_factory=list)     # lines before first_line the verdict needs (state)


class Correlator:
    def __init__(self, save: Callable[[dict], None], sovd_check: Callable[[str], dict], safety_case, log=None,
                 now: Callable[[], int] = clock.now_ms, grace_ms: int = 5000, diag_timeout_ms: int = 5000,
                 end_timeout_ms: int = 30000):
        self._save, self._sovd, self._case, self._log, self._now = save, sovd_check, safety_case, log, now
        self.grace_ms, self.diag_timeout_ms, self.end_timeout_ms = grace_ms, diag_timeout_ms, end_timeout_ms
        self.window: Optional[Window] = None
        self.state: Optional[dict] = None            # latest guardian state, also between campaigns
        self.state_line: Optional[int] = None        # ... and its line in events.jsonl

    # --- input ---------------------------------------------------------------------------------------------
    def on_campaign(self, event: dict, line: int) -> None:
        """event: CampaignEvent as a dict (event, run_id, ts_ms, seq, data)."""
        name, run_id, data = event["event"], event["run_id"], event.get("data") or {}
        if name == "campaign_start":
            previous = None
            if self.window is not None:
                previous = self.window.run_id
                self._interfere(self.window, run_id)
                self._close()
            if not SAFE_ID.match(run_id):
                self._emit("rejected_run_id", run_id=run_id)
                return
            self.window = Window(run_id, data, event["ts_ms"], line, line, self._now(),
                                 context_lines=[self.state_line] if self.state_line is not None else [])
            if previous is not None:
                self._interfere(self.window, previous)
            self._emit("window_opened", run_id=run_id)
            return
        w = self.window
        if w is None or w.run_id != run_id:
            if w is not None:
                w.last_line = line
                self._interfere(w, run_id)
            self._emit("campaign_event_outside_window", campaign_event=name, run_id=run_id)
            return
        w.last_line = line
        if name == "fault_injected":
            if not w.injected:
                w.state_at_injection = self.state["state"] if self.state else None
            w.injected.append({"ts_ms": event["ts_ms"], **data})
        elif name == "fault_failed":
            w.injected.append({"ts_ms": event["ts_ms"], "failed": True, **data})
        elif name == "campaign_end":
            w.end, w.end_seen_at = dict(data), self._now()

    @staticmethod
    def _interfere(w: Window, other: str) -> None:
        if other != w.run_id and other not in w.interference:
            w.interference.append(other)

    def on_fault(self, fault: dict, line: int) -> None:
        """fault: FaultEvent as a dict."""
        w = self.window
        if w is None:
            return
        w.last_line = line
        w.faults.append(fault)
        expected = w.start.get("expected_faults") or []
        if fault["stage"] == "FAILED" and fault["code"] in expected and fault["code"] not in w.diagnostics:
            w.pending.setdefault(fault["code"], self._now())

    def on_state(self, state: dict, line: int) -> None:
        """state: StateEvent as a dict. Periodic repeats only refresh self.state."""
        changed = self.state is None or (state["state"], state["reason"]) != (self.state["state"], self.state["reason"])
        self.state, self.state_line = state, line
        w = self.window
        if w is not None and (changed or state["previous"] != state["state"]):
            w.last_line = line
            w.states.append(state)

    def on_other(self, line: int) -> None:
        if self.window is not None:
            self.window.last_line = line

    # --- time ----------------------------------------------------------------------------------------------
    def tick(self) -> None:
        w = self.window
        if w is None:
            return
        now = self._now()
        for code, seen_at in list(w.pending.items()):
            result = self._sovd(code)
            if result.get("visible") and result.get("confirmed") and result.get("run_id") == w.run_id:
                w.diagnostics[code] = {**result, "latency_ms": now - seen_at}
                del w.pending[code]
            elif now - seen_at >= self.diag_timeout_ms:
                w.diagnostics[code] = {**result, "latency_ms": None,
                                       "note": f"not confirmed for this run within {self.diag_timeout_ms} ms"}
                del w.pending[code]
        if w.end_seen_at is not None:
            if now - w.end_seen_at >= self.grace_ms and not w.pending:
                self._close()
        elif now - w.opened_at >= float(w.start.get("duration_s") or 0) * 1000 + self.end_timeout_ms:
            self._close()

    def flush(self) -> None:
        """Close an open window now (shutdown)."""
        if self.window is not None:
            self._close()

    # --- output --------------------------------------------------------------------------------------------
    def _close(self) -> None:
        w = self.window
        assert w is not None
        for code in w.start.get("expected_faults") or []:
            if code not in w.diagnostics:    # never raised, or still pending: record what OpenSOVD shows now
                w.diagnostics[code] = {**self._sovd(code), "latency_ms": None}   # (still inside the window's lines)
        self.window = None
        trace, trace_errors = self._case.trace(w.run_id, w.start.get("hazard", ""), w.start.get("safety_goal", ""))
        obs = Observed(w.run_id, w.start, w.start_ts, w.injected, w.end, w.faults, w.states, w.state_at_injection,
                       w.diagnostics, trace, trace_errors, w.interference)
        j = judge(obs)
        record = build_record(obs, j, w)
        self._emit("verdict", run_id=w.run_id, record_id=record["record_id"], verdict=j.verdict,
                   reasons=[r["text"] for r in j.reasons])
        self._save(record)

    def _emit(self, event: str, **fields) -> None:
        if self._log is not None:
            self._log.log(event, **fields)


def build_record(obs: Observed, j, w: Window) -> dict:
    start = obs.start or {}
    return {
        "record_id": record_id(obs.run_id, obs.start_ts),
        "run_id": obs.run_id,
        "started_at": obs.start_ts,
        "ended_at": (w.end_seen_at if w.end is not None else None),
        "trace": obs.trace,
        "campaign": {k: start.get(k) for k in ("hazard", "safety_goal", "expected_state", "expected_faults",
                                               "tolerated_faults", "expected_verdict", "max_detect_ms", "seed",
                                               "duration_s", "baseline")}
                    | {"status": (obs.end or {}).get("status"), "error": (obs.end or {}).get("error")},
        "injected": obs.injected,
        "state_at_injection": obs.state_at_injection,
        "detection": j.detection,
        "mitigation": j.mitigation,
        "diagnostics": [{"code": c, **d} for c, d in obs.diagnostics.items()],
        "unexpected_faults": j.unexpected_faults,
        "interference": obs.interference,
        "fault_events": obs.faults,
        "state_changes": [{k: s.get(k) for k in ("ts_ms", "previous", "state", "reason", "msg_id", "seq")}
                          for s in obs.states],
        "verdict": j.verdict,
        # a campaign may break the evidence chain on purpose (e.g. a hidden DTC): its FAIL is the expected outcome
        "as_expected": j.verdict == (start.get("expected_verdict") or "PASS"),
        "reasons": j.reasons,
        "raw_events": f"events.jsonl#L{w.first_line}-L{w.last_line}",
        "lines": [w.first_line, w.last_line],
        "context_lines": w.context_lines,   # e.g. the guardian state before campaign_start (precondition)
    }
