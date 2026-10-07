# Made with Claude (Claude Code, Anthropic)
"""judge(Observed) -> Judgement: what the system did in one campaign run, and whether that proves the safety goal.

Pure: no network, no clock, no files. Everything the rules need is in Observed (built by the correlator).

    no campaign_start / no campaign_end / aborted / nothing injected    INCONCLUSIVE (nothing else is judged)
    guardian not MONITORING when the first fault went in                 INCONCLUSIVE (the run proves nothing)
    expected fault never raised, or later than max_detect_ms             FAIL
    expected state never reached in time (WARNING / CRITICAL /           FAIL
      SENSOR_FAULT / MITIGATING), or left (MONITORING / CLEAR)
    CRITICAL expected but cooling never requested (no MITIGATING)        FAIL
    a fault raised that the campaign does not expect (false alarm)       FAIL
    expected fault not in OpenSOVD, not confirmed, or from another run   FAIL
    campaign not in the safety case, or its hazard / goal do not match   INCONCLUSIVE ("proves no requirement")
    another campaign ran at the same time                                INCONCLUSIVE, even over a FAIL (the
                                                                         evidence is contaminated either way)

Any FAIL wins over INCONCLUSIVE (except interference); no reasons at all is PASS.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

PASS, FAIL, INCONCLUSIVE = "PASS", "FAIL", "INCONCLUSIVE"
REACHED_STATES = ("WARNING", "CRITICAL", "SENSOR_FAULT", "MITIGATING")   # must be reached after the fault
HELD_STATES = ("CLEAR", "MONITORING")                                   # must be kept despite the fault
HEALTHY_AT_INJECTION = ("MONITORING",)


@dataclass
class Observed:
    """One campaign run as the collector saw it. Times are epoch ms; faults / states are contract dicts."""
    run_id: str
    start: Optional[dict] = None             # campaign_start data (expected_state, expected_faults, max_detect_ms, ...)
    start_ts: Optional[int] = None
    injected: List[dict] = field(default_factory=list)     # {"ts_ms", **fault_injected data}
    end: Optional[dict] = None               # campaign_end data (status, error)
    faults: List[dict] = field(default_factory=list)       # FaultEvent dicts (FAILED / PASSED edges) in the window
    states: List[dict] = field(default_factory=list)       # StateEvent dicts where the state or the reason changed
    state_at_injection: Optional[str] = None
    diagnostics: Dict[str, dict] = field(default_factory=dict)   # code -> sovd.check() result (+ latency_ms)
    trace: List[dict] = field(default_factory=list)        # safety case requirements this run proves
    trace_errors: List[str] = field(default_factory=list)
    interference: List[str] = field(default_factory=list)  # other campaigns (run_id) seen while this one ran


@dataclass
class Judgement:
    verdict: str
    reasons: List[dict]                      # {"verdict": FAIL | INCONCLUSIVE, "text": ...}
    detection: dict = field(default_factory=dict)
    mitigation: dict = field(default_factory=dict)
    unexpected_faults: List[dict] = field(default_factory=list)


class _Reasons(list):
    def fail(self, text: str) -> None:
        self.append({"verdict": FAIL, "text": text})

    def inconclusive(self, text: str) -> None:
        self.append({"verdict": INCONCLUSIVE, "text": text})

    def verdict(self, contaminated: bool = False) -> str:
        kinds = {r["verdict"] for r in self}
        return INCONCLUSIVE if contaminated else FAIL if FAIL in kinds else INCONCLUSIVE if kinds else PASS


def _first(items, after_ts: int, **match) -> Optional[dict]:
    return next((i for i in items if i["ts_ms"] >= after_ts and all(i.get(k) == v for k, v in match.items())), None)


def judge(obs: Observed) -> Judgement:
    reasons = _Reasons()
    for other in obs.interference:
        reasons.inconclusive(f"campaign {other} ran at the same time: its faults are mixed into this run")
    contaminated = bool(obs.interference)
    if obs.start is None:
        reasons.inconclusive("no campaign_start: the collector did not see the campaign begin")
        return Judgement(reasons.verdict(contaminated), reasons)
    if obs.end is None:
        reasons.inconclusive("campaign_end never arrived")
    elif obs.end.get("status") != "completed":
        error = f": {obs.end['error']}" if obs.end.get("error") else ""
        reasons.inconclusive(f"campaign {obs.end.get('status')}{error}")
    if not obs.injected:
        reasons.inconclusive("no fault was injected")
    if len(reasons) > len(obs.interference):
        return Judgement(reasons.verdict(), reasons)

    t0 = min(i["ts_ms"] for i in obs.injected)
    limit = int(obs.start.get("max_detect_ms") or 0)
    expected_faults = list(obs.start.get("expected_faults") or [])
    expected_state = obs.start.get("expected_state")
    if obs.state_at_injection not in HEALTHY_AT_INJECTION:
        reasons.inconclusive(f"guardian was {obs.state_at_injection or 'unknown'} when the first fault was injected, "
                             f"not {' / '.join(HEALTHY_AT_INJECTION)}")

    detection = {"t0": t0, "max_detect_ms": limit, "faults": [], "state": None}
    for code in expected_faults:
        failed = _first(obs.faults, t0, code=code, stage="FAILED")
        entry = {"code": code, "raised": failed is not None}
        if failed is None:
            reasons.fail(f"expected fault {code} was never raised")
        else:
            latency = failed["ts_ms"] - t0
            healed = _first(obs.faults, failed["ts_ms"], code=code, stage="PASSED")
            entry.update(at=failed["ts_ms"], latency_ms=latency, msg_id=failed.get("msg_id"), seq=failed.get("seq"),
                         run_id=failed.get("run_id"), cleared_at=healed["ts_ms"] if healed else None)
            if latency > limit:
                reasons.fail(f"{code} raised after {latency} ms, limit {limit} ms")
        detection["faults"].append(entry)

    after = [s for s in obs.states if s["ts_ms"] >= t0]
    if expected_state in REACHED_STATES:
        reached = _first(after, t0, state=expected_state)
        detection["state"] = {"expected": expected_state, "reached": reached is not None}
        if reached is None:
            reasons.fail(f"guardian never reached {expected_state}")
        else:
            latency = reached["ts_ms"] - t0
            detection["state"].update(at=reached["ts_ms"], latency_ms=latency, reason=reached.get("reason"),
                                      msg_id=reached.get("msg_id"), seq=reached.get("seq"))
            if latency > limit:
                reasons.fail(f"guardian reached {expected_state} after {latency} ms, limit {limit} ms")
    elif expected_state in HELD_STATES:
        left = next((s for s in after if s["state"] != expected_state), None)
        detection["state"] = {"expected": expected_state, "held": left is None}
        if left is not None:
            detection["state"].update(left_for=left["state"], at=left["ts_ms"], reason=left.get("reason"))
            reasons.fail(f"guardian left {expected_state} for {left['state']} ({left.get('reason')}) "
                         f"{left['ts_ms'] - t0} ms after the fault")

    mitigation = {}
    if expected_state in ("CRITICAL", "MITIGATING"):
        critical = _first(after, t0, state="CRITICAL")
        cooling = _first(after, critical["ts_ms"], state="MITIGATING") if critical else None
        mitigation = {"critical_at": critical and critical["ts_ms"], "mitigating_at": cooling and cooling["ts_ms"],
                      "latency_ms": cooling["ts_ms"] - critical["ts_ms"] if critical and cooling else None}
        if critical is not None and cooling is None:
            reasons.fail("CRITICAL without MITIGATING: cooling was never requested")

    unexpected, seen = [], set()
    for f in obs.faults:
        if f["stage"] == "FAILED" and f["code"] not in expected_faults and f["code"] not in seen:
            seen.add(f["code"])
            unexpected.append({"code": f["code"], "at": f["ts_ms"], "reason": f.get("reason"), "msg_id": f.get("msg_id")})
            reasons.fail(f"unexpected fault {f['code']} ({f.get('reason')}): false alarm or missing from expected_faults")

    for code in expected_faults:
        diag = obs.diagnostics.get(code)
        if diag is None:
            reasons.fail(f"{code} was not checked in OpenSOVD")
        elif not diag.get("visible"):
            reasons.fail(f"{code} not visible in OpenSOVD ({diag.get('error') or 'no record'})")
        elif diag.get("run_id") != obs.run_id:
            reasons.fail(f"{code} in OpenSOVD belongs to run {diag.get('run_id')!r}, not {obs.run_id!r}")
        elif not diag.get("confirmed"):
            reasons.fail(f"{code} in OpenSOVD is not a confirmed DTC")

    if not obs.trace:
        reasons.inconclusive("campaign is not in the safety case: it proves no requirement")
    for error in obs.trace_errors:
        reasons.inconclusive(error)

    return Judgement(reasons.verdict(contaminated), reasons, detection, mitigation, unexpected)
