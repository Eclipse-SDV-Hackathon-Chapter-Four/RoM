# Made with Claude (Claude Code, Anthropic)
"""The recorder + correlator end to end, on a fake clock and a fake OpenSOVD: no bus, no network, no sleeping.

Each scenario is the message sequence the bus would carry for one campaign run (as in events.jsonl)."""
import json

import pytest

pytest.importorskip("uprotocol")

from evidence_collector import safety_case  # noqa: E402
from evidence_collector.correlator import Correlator, record_id  # noqa: E402
from evidence_collector.recorder import Recorder  # noqa: E402
from evidence_collector.store import Store  # noqa: E402

RUN = "thermal-runaway-01"
WARN, CRIT = "battery_guardian.over_temp_warning", "battery_guardian.over_temp_critical"
IMB = "battery_guardian.cell_imbalance"
START = {"hazard": "H1: thermal runaway of a single traction battery cell",
         "safety_goal": "SG1: warn at 38 °C and request cooling at 45 °C pack maximum", "expected_state": "CRITICAL",
         "expected_faults": [WARN, CRIT, IMB], "max_detect_ms": 35000, "seed": 7, "duration_s": 70}


class Clock:
    def __init__(self):
        self.t = 1_791_000_000_000

    def __call__(self):
        return self.t


class FakeSovd:
    """A DTC becomes visible `delay_ms` after the guardian raised it, carrying the run_id of that run."""

    def __init__(self, clock, delay_ms=300, run_id=RUN):
        self.clock, self.delay_ms, self.run_id, self.raised, self.calls = clock, delay_ms, run_id, {}, []

    def check(self, code):
        self.calls.append(code)
        at = self.raised.get(code)
        if at is None or self.clock() < at + self.delay_ms:
            return {"url": code, "visible": False, "confirmed": False, "run_id": None, "error": "HTTP 404"}
        return {"url": code, "visible": True, "confirmed": True, "run_id": self.run_id, "status": {}, "error": None}


class Bench:
    def __init__(self, tmp_path, sovd_delay_ms=300, sovd_run_id=RUN):
        self.clock = Clock()
        self.sovd = FakeSovd(self.clock, sovd_delay_ms, sovd_run_id)
        self.store = Store(tmp_path / "evidence.db", tmp_path / "evidence")
        self.correlator = Correlator(self.store.save, self.sovd.check, safety_case.load(), now=self.clock,
                                     grace_ms=5000, diag_timeout_ms=5000)
        self.recorder = Recorder(tmp_path / "events.jsonl", self.store, self.correlator, now=self.clock)

    def at(self, offset_ms):
        """Advance the clock to start + offset (ticking every 500 ms on the way, like the service)."""
        target = START_T + offset_ms
        while self.clock.t + 500 <= target:
            self.clock.t += 500
            self.recorder.tick()
        self.clock.t = target
        self.recorder.tick()
        return self

    def send(self, topic, payload):
        if topic == "fault" and payload["stage"] == "FAILED":
            self.sovd.raised.setdefault(payload["code"], self.clock())
        return self.recorder.handle(topic, json.dumps(payload).encode(), msg_id=f"m{self.recorder.line + 1}")

    def campaign(self, event, **data):
        return self.send("campaign", {"event": event, "run_id": RUN, "ts_ms": self.clock(), "seq": 0, "data": data})

    def state(self, to, previous, reason):
        return self.send("state", {"state": to, "previous": previous, "reason": reason, "ts_ms": self.clock(),
                                   "cells": "30,29,28,28", "run_id": RUN})

    def fault(self, code, stage="FAILED"):
        return self.send("fault", {"code": code, "stage": stage, "ts_ms": self.clock(), "reason": "x", "run_id": RUN})


START_T = Clock().t


def thermal_runaway(b, warn_at=8_000, crit_at=24_000, end=True, extra=()):
    b.at(0).state("MONITORING", "MONITORING", "temp ok")
    b.campaign("campaign_start", **START)
    b.send("cells", {"cells": {"1": 30.0}, "seq": 1, "ts_ms": b.clock(), "source_ts_ms": b.clock(), "run_id": RUN})
    b.at(10_000).campaign("fault_injected", target="simulator", type="drift", cells=[1])
    b.at(10_000 + warn_at).fault(WARN)
    b.state("WARNING", "MONITORING", "getting hot")
    b.at(10_000 + warn_at + 2_000).fault(IMB)
    b.at(10_000 + crit_at).fault(CRIT)
    b.state("CRITICAL", "WARNING", "too hot")
    b.at(10_000 + crit_at + 500).state("MITIGATING", "CRITICAL", "cooling requested")
    for topic, payload in extra:
        b.send(topic, payload)
    b.at(60_000).campaign("fault_cleared", target="simulator", type="drift", reason="scheduled")
    if end:
        b.at(70_000).campaign("campaign_end", status="completed")


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
