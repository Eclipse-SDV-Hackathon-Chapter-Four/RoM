# Made with Claude (Claude Code, Anthropic)
from evidence_collector.verdict import FAIL, INCONCLUSIVE, PASS, Observed, judge

T0 = 10_000
WARN, CRIT = "battery_guardian.over_temp_warning", "battery_guardian.over_temp_critical"
TRACE = [{"requirement": {"id": "SR-01"}, "safety_goal": {"id": "SG1"}, "hazards": [{"id": "H1"}]}]


def diag(code, run_id="r1", **kw):
    return {"visible": True, "confirmed": True, "run_id": run_id, **kw}


def fault(code, at, stage="FAILED"):
    return {"code": code, "stage": stage, "ts_ms": at, "reason": "x", "msg_id": f"m{at}"}


def state(to, at, previous="MONITORING"):
    return {"state": to, "previous": previous, "reason": to.lower(), "ts_ms": at}


def observed(**kw):
    base = dict(
        run_id="r1",
        start={"expected_state": "CRITICAL", "expected_faults": [WARN, CRIT], "max_detect_ms": 30_000},
        start_ts=0, injected=[{"ts_ms": T0, "target": "simulator", "type": "drift"}], end={"status": "completed"},
        faults=[fault(WARN, T0 + 8_000), fault(CRIT, T0 + 20_000)],
        states=[state("WARNING", T0 + 8_000), state("CRITICAL", T0 + 20_000, "WARNING"),
                state("MITIGATING", T0 + 20_500, "CRITICAL")],
        state_at_injection="MONITORING", diagnostics={WARN: diag(WARN), CRIT: diag(CRIT)}, trace=TRACE)
    base.update(kw)
    return Observed(**base)


def texts(j):
    return [r["text"] for r in j.reasons]


def test_pass_with_latencies_and_mitigation_timing():
    j = judge(observed())
    assert j.verdict == PASS and j.reasons == []
    assert [f["latency_ms"] for f in j.detection["faults"]] == [8_000, 20_000]
    assert j.detection["state"]["latency_ms"] == 20_000 and j.mitigation["latency_ms"] == 500


def test_late_detection_fails():
    j = judge(observed(start={"expected_state": "CRITICAL", "expected_faults": [WARN, CRIT], "max_detect_ms": 15_000}))
    assert j.verdict == FAIL
    assert f"{CRIT} raised after 20000 ms, limit 15000 ms" in texts(j)
    assert "guardian reached CRITICAL after 20000 ms, limit 15000 ms" in texts(j)


def test_missing_detection_and_state_fail():
    j = judge(observed(faults=[fault(WARN, T0 + 8_000)], states=[state("WARNING", T0 + 8_000)]))
    assert j.verdict == FAIL
    assert f"expected fault {CRIT} was never raised" in texts(j) and "guardian never reached CRITICAL" in texts(j)


def test_a_fault_raised_before_the_injection_does_not_count_as_detection():
    j = judge(observed(faults=[fault(WARN, T0 - 1), fault(CRIT, T0 + 20_000)]))
    assert f"expected fault {WARN} was never raised" in texts(j)


def test_false_alarm_fails_once_per_code():
    stale = "battery_guardian.signal_stale"
    j = judge(observed(faults=observed().faults + [fault(stale, T0 + 1), fault(stale, T0 + 2)]))
    assert j.verdict == FAIL and [u["code"] for u in j.unexpected_faults] == [stale]
    assert sum("unexpected fault" in t for t in texts(j)) == 1



def test_tolerated_fault_is_no_false_alarm_and_needs_no_timing():
    integrity = "battery_guardian.link_integrity"
    start = {**observed().start, "tolerated_faults": [integrity]}
    j = judge(observed(start=start, faults=observed().faults + [fault(integrity, T0 + 60_000)]))
    assert j.verdict == PASS and j.unexpected_faults == []


def test_critical_without_cooling_fails():
    j = judge(observed(states=observed().states[:2]))
    assert j.verdict == FAIL and "CRITICAL without MITIGATING: cooling was never requested" in texts(j)


def test_held_state_must_not_be_left():
    stuck = "battery_guardian.cell3.signal_stuck"
    start = {"expected_state": "MONITORING", "expected_faults": [stuck], "max_detect_ms": 12_000}
    ok = observed(start=start, faults=[fault(stuck, T0 + 10_000)], states=[], diagnostics={stuck: diag(stuck)})
    assert judge(ok).verdict == PASS and judge(ok).detection["state"] == {"expected": "MONITORING", "held": True}
    left = observed(start=start, faults=[fault(stuck, T0 + 10_000)], diagnostics={stuck: diag(stuck)},
                    states=[state("SENSOR_FAULT", T0 + 10_000)])
    assert judge(left).verdict == FAIL and "guardian left MONITORING for SENSOR_FAULT" in texts(judge(left))[0]


def test_diagnostic_truth_from_opensovd():
    cases = {
        "not visible": {"visible": False, "error": "HTTP 404"},
        "belongs to run 'old'": diag(CRIT, run_id="old"),
        "not a confirmed DTC": diag(CRIT, confirmed=False),
    }
    for words, d in cases.items():
        j = judge(observed(diagnostics={WARN: diag(WARN), CRIT: d}))
        assert j.verdict == FAIL and any(words in t for t in texts(j)), words
    assert "was not checked in OpenSOVD" in texts(judge(observed(diagnostics={WARN: diag(WARN)})))[0]


def test_inconclusive_runs():
    assert judge(observed(start=None)).verdict == INCONCLUSIVE
    assert texts(judge(observed(end=None))) == ["campaign_end never arrived"]
    assert texts(judge(observed(end={"status": "aborted", "error": "sim down"}))) == ["campaign aborted: sim down"]
    assert texts(judge(observed(injected=[]))) == ["no fault was injected"]
    j = judge(observed(state_at_injection="SENSOR_FAULT"))
    assert j.verdict == INCONCLUSIVE and "guardian was SENSOR_FAULT" in texts(j)[0]


def test_not_traced_never_passes_but_a_fail_still_wins():
    assert judge(observed(trace=[])).verdict == INCONCLUSIVE
    assert judge(observed(trace=[], faults=[])).verdict == FAIL
    assert judge(observed(trace_errors=["hazard mismatch"])).verdict == INCONCLUSIVE


def test_another_campaign_at_the_same_time_makes_even_a_fail_inconclusive():
    j = judge(observed(interference=["sensor-stuck-cell3-01"], faults=[]))
    assert j.verdict == INCONCLUSIVE
    assert texts(j)[0] == "campaign sensor-stuck-cell3-01 ran at the same time: its faults are mixed into this run"
    assert any("never raised" in t for t in texts(j))      # the rest is still judged and reported
    assert judge(observed(interference=["x"], end=None)).verdict == INCONCLUSIVE
