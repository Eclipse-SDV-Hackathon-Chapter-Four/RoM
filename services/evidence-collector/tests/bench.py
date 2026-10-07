# Made with Claude (Claude Code, Anthropic)
"""Test bench shared by test_correlator.py and test_replay.py: recorder + correlator on a fake clock and a fake
OpenSOVD, and the bus messages of a thermal-runaway run. Load it with load_bench() (pytest runs in importlib mode)."""
import json

from evidence_collector import safety_case
from evidence_collector.correlator import Correlator, record_id
from evidence_collector.recorder import Recorder
from evidence_collector.store import Store

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
        self.correlator = Correlator(self.store.save,
                                     lambda code: self.recorder.record_sovd(code, self.sovd.check(code)),
                                     safety_case.load(), now=self.clock, grace_ms=5000, diag_timeout_ms=5000)
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


