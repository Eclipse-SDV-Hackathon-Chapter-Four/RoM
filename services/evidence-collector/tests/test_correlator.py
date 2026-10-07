# Made with Claude (Claude Code, Anthropic)
"""The recorder + correlator end to end, on a fake clock and a fake OpenSOVD: no bus, no network, no sleeping.

Each scenario is the message sequence the bus would carry for one campaign run (as in events.jsonl), see bench.py."""
import json

import pytest

pytest.importorskip("uprotocol")

import importlib.util
import sys
from pathlib import Path


def _bench():
    """tests/bench.py, imported by path: pytest runs in importlib mode, so the test dir is not on sys.path."""
    if "ec_bench" not in sys.modules:
        spec = importlib.util.spec_from_file_location("ec_bench", Path(__file__).with_name("bench.py"))
        sys.modules["ec_bench"] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules["ec_bench"])
    return sys.modules["ec_bench"]


_b = _bench()
RUN, START, START_T, CRIT, WARN, IMB = _b.RUN, _b.START, _b.START_T, _b.CRIT, _b.WARN, _b.IMB
Bench, thermal_runaway, record_id = _b.Bench, _b.thermal_runaway, _b.record_id


def records(b):
    return b.store.records()


def test_full_run_passes_with_trace_latencies_and_raw_lines(tmp_path):
    b = Bench(tmp_path)
    thermal_runaway(b)
    assert records(b) == []                  # grace period: late messages may still come
    b.at(75_000)
    [r] = records(b)
    assert r["verdict"] == "PASS", r["reasons"]
    assert r["record_id"] == record_id(RUN, START_T) and r["record_id"].startswith(RUN + "@")
    assert [t["requirement"]["id"] for t in r["trace"]] == ["SR-01"]
    assert [(f["code"], f["latency_ms"]) for f in r["detection"]["faults"]] == [(WARN, 8000), (CRIT, 24000), (IMB, 10000)]
    assert r["mitigation"]["latency_ms"] == 500 and r["state_at_injection"] == "MONITORING"
    assert {d["code"]: d["latency_ms"] for d in r["diagnostics"]} == {WARN: 500, IMB: 500, CRIT: 500}
    first, last = r["lines"]
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert r["raw_events"] == f"events.jsonl#L{first}-L{last}" and first == 2 and last == len(lines)
    assert json.loads(lines[first - 1])["payload"]["event"] == "campaign_start"
    assert (tmp_path / "evidence" / f"{r['record_id']}.json").exists()


def test_late_detection_fails(tmp_path):
    b = Bench(tmp_path)
    thermal_runaway(b, crit_at=36_000)
    b.at(80_000)
    [r] = records(b)
    assert r["verdict"] == "FAIL" and f"{CRIT} raised after 36000 ms, limit 35000 ms" in [x["text"] for x in r["reasons"]]


def test_dtc_from_another_run_in_opensovd_fails(tmp_path):
    b = Bench(tmp_path, sovd_run_id="older-run")
    thermal_runaway(b)
    b.at(80_000)
    [r] = records(b)
    assert r["verdict"] == "FAIL"
    assert any("belongs to run 'older-run'" in x["text"] for x in r["reasons"])
    assert all(d["latency_ms"] is None for d in r["diagnostics"])


def test_false_alarm_fails(tmp_path):
    b = Bench(tmp_path)
    stale = {"code": "battery_guardian.signal_stale", "stage": "FAILED", "ts_ms": START_T + 40_000, "reason": "silent"}
    thermal_runaway(b, extra=[("fault", stale)])
    b.at(80_000)
    [r] = records(b)
    assert r["verdict"] == "FAIL" and [u["code"] for u in r["unexpected_faults"]] == ["battery_guardian.signal_stale"]


def test_missing_campaign_end_closes_after_the_timeout(tmp_path):
    b = Bench(tmp_path)
    thermal_runaway(b, end=False)
    b.at(99_000)
    assert records(b) == []                  # duration_s 70 s + 30 s end timeout, counted from campaign_start
    b.at(100_500)
    [r] = records(b)
    assert r["verdict"] == "INCONCLUSIVE" and [x["text"] for x in r["reasons"]] == ["campaign_end never arrived"]


def test_invalid_messages_are_recorded_but_not_judged(tmp_path):
    b = Bench(tmp_path)
    line = b.recorder.handle("state", b"not json")
    entry = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[line - 1])
    assert entry["payload"] == "not json" and entry["rejected"].startswith("invalid_json")
    assert b.correlator.state is None and b.store.events()[0]["line"] == line


def test_line_numbers_continue_after_a_restart(tmp_path):
    b = Bench(tmp_path)
    b.state("MONITORING", "MONITORING", "temp ok")
    b.state("MONITORING", "MONITORING", "temp ok")
    again = Bench(tmp_path)
    assert again.state("MONITORING", "MONITORING", "temp ok") == 3


def test_a_new_campaign_closes_the_one_whose_end_never_came(tmp_path):
    b = Bench(tmp_path)
    thermal_runaway(b, end=False)
    b.at(71_000).campaign("campaign_start", **START)
    [r] = records(b)
    assert r["verdict"] == "INCONCLUSIVE" and b.correlator.window is not None


def test_overlapping_campaigns_contaminate_each_other(tmp_path):
    """As seen live: sensor_stuck_cell3 started 4 s before source_dropout, from another terminal."""
    b = Bench(tmp_path)
    other = {"event": "campaign_start", "run_id": "sensor-stuck-cell3-01", "ts_ms": START_T, "seq": 1, "data": START}
    b.at(0).send("campaign", other)
    thermal_runaway(b)
    b.send("campaign", {**other, "event": "campaign_end", "data": {"status": "completed"}})
    b.at(80_000)
    first, second = sorted(records(b), key=lambda r: r["started_at"] or 0)[-2:]
    assert first["run_id"] == "sensor-stuck-cell3-01" and first["interference"] == [RUN]
    assert second["verdict"] == "INCONCLUSIVE" and second["interference"] == ["sensor-stuck-cell3-01"]


def test_periodic_state_repeats_are_recorded_but_not_kept_as_changes(tmp_path):
    b = Bench(tmp_path)
    thermal_runaway(b)
    b.at(75_000)
    [r] = records(b)
    assert [s["state"] for s in r["state_changes"]] == ["WARNING", "CRITICAL", "MITIGATING"]
