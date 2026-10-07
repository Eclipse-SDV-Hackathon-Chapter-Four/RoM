# Made with Claude (Claude Code, Anthropic)
import io
import json

import pytest

from rom_common.jsonlog import JsonLogger
from fault_injector import campaign
from fault_injector.__main__ import main
from fault_injector.runner import Runner, RunnerError, timeline

URLS = {"simulator": "http://sim", "publisher": "http://pub"}


def make(faults, **kw):
    data = {"run_id": "r1", "seed": 3, "hazard": "H", "safety_goal": "SG", "expected_state": "CRITICAL",
            "max_detect_ms": 5000, "faults": faults, "baseline": {"min_c": 25, "max_c": 32}, **kw}
    return campaign.parse(data)


class Fake:
    """Fake services plus a fake clock: sleeping advances time, and every call is recorded with its time."""

    def __init__(self, fail_on=None):
        self.t, self.calls, self.fail_on, self._ids = 0.0, [], fail_on, {}

    def sleep(self, s):
        self.t += s

    def http(self, method, url, body):
        self.calls.append((self.t, method, url, body))
        if self.fail_on and self.fail_on(method, url):
            return 422, {"error": "refused"}
        if method == "POST" and url.endswith("/faults"):
            host = url.split("/faults")[0]
            self._ids[host] = self._ids.get(host, 0) + 1
            return 201, {"id": self._ids[host]}
        return 200, {}


def run(c, fake=None, urls=URLS):
    fake, out = fake or Fake(), io.StringIO()
    runner = Runner(c, urls, JsonLogger("fault-injector", None, out), fake.http, fake.sleep, lambda: fake.t)
    status = runner.run()
    return status, fake, [json.loads(l) for l in out.getvalue().splitlines()]


TWO = [
    {"at_s": 10, "duration_s": 20, "target": "simulator", "type": "drift", "cell": 1, "params": {"rate_c_per_s": 1}},
    {"at_s": 15, "duration_s": 5, "target": "publisher", "type": "delay", "params": {"ms": 600}},
]


def test_runs_faults_on_schedule_against_the_right_service():
    status, fake, _ = run(make(TWO))
    assert status == "completed"
    assert fake.calls == [
        (0.0, "POST", "http://sim/run", {"run_id": "r1", "seed": 3, "min_c": 25.0, "max_c": 32.0}),
        (0.0, "POST", "http://pub/run", {"run_id": "r1", "seed": 3}),
        (10.0, "POST", "http://sim/faults", {"type": "drift", "params": {"rate_c_per_s": 1}, "cells": [1]}),
        (15.0, "POST", "http://pub/faults", {"type": "delay", "params": {"ms": 600}}),
        (20.0, "DELETE", "http://pub/faults/1", None),
        (30.0, "DELETE", "http://sim/faults/1", None),
    ]
    assert fake.t == 40.0    # waits out the settle time before ending


def test_log_trail_carries_the_run_id_and_the_campaign_facts():
    _, _, logs = run(make(TWO))
    assert [e["event"] for e in logs] == ["campaign_start", "fault_injected", "fault_injected", "fault_cleared",
                                          "fault_cleared", "campaign_end"]
    assert all(e["run_id"] == "r1" for e in logs)
    start, injected, end = logs[0], logs[1], logs[-1]
    assert (start["hazard"], start["safety_goal"], start["expected_state"], start["max_detect_ms"]) == \
        ("H", "SG", "CRITICAL", 5000)
    assert injected["fault_id"] == 1 and injected["type"] == "drift" and injected["target"] == "simulator"
    assert [e["reason"] for e in logs if e["event"] == "fault_cleared"] == ["scheduled", "scheduled"]
    assert end["status"] == "completed"


def test_fault_without_duration_is_cleared_when_the_campaign_ends():
    c = make([{"at_s": 5, "target": "simulator", "type": "stuck"}], duration_s=20)
    status, fake, logs = run(c)
    assert status == "completed" and fake.calls[-1] == (20.0, "DELETE", "http://sim/faults/1", None)
    assert [e["reason"] for e in logs if e["event"] == "fault_cleared"] == ["campaign_end"]


def test_clear_happens_before_an_inject_at_the_same_instant():
    c = make([{"at_s": 0, "duration_s": 5, "target": "simulator", "type": "stuck"},
              {"at_s": 5, "duration_s": 5, "target": "simulator", "type": "dropout"}])
    assert [(t, a, s.type) for t, _, a, s in timeline(c)] == [
        (0.0, "inject", "stuck"), (5.0, "clear", "stuck"), (5.0, "inject", "dropout"), (10.0, "clear", "dropout")]


def test_refused_fault_aborts_and_clears_what_is_active():
    fake = Fake(fail_on=lambda m, u: m == "POST" and u == "http://pub/faults")
    status, fake, logs = run(make(TWO), fake)
    assert status == "aborted"
    assert fake.calls[-1] == (15.0, "DELETE", "http://sim/faults/1", None)    # the simulator fault is cleaned up
    assert [e["event"] for e in logs][-3:] == ["fault_failed", "fault_cleared", "campaign_end"]
    assert logs[-1]["status"] == "aborted" and "422" in logs[-1]["error"]


def test_failed_cleanup_does_not_stop_the_other_services_and_marks_the_run_aborted():
    class Down(Fake):
        def http(self, method, url, body):
            if url.startswith("http://sim") and method == "DELETE":
                self.calls.append((self.t, method, url, body))
                raise RunnerError("sim is down")
            return super().http(method, url, body)

    c = make([{"at_s": 1, "target": "simulator", "type": "stuck"}, {"at_s": 1, "target": "publisher", "type": "drop"}],
             duration_s=10)
    status, fake, logs = run(c, Down())
    deletes = [u for _, m, u, _ in fake.calls if m == "DELETE"]
    assert deletes == ["http://sim/faults/1", "http://pub/faults/1"]    # the publisher is still cleared
    assert status == "aborted" and logs[-1]["error"] == "could not clear simulator stuck"
    assert [e["event"] for e in logs].count("fault_cleared") == 1


def test_ctrl_c_is_interrupted_and_still_cleans_up():
    class Interrupt(Fake):
        def sleep(self, s):
            if self.t >= 10:
                raise KeyboardInterrupt
            super().sleep(s)

    status, fake, logs = run(make(TWO), Interrupt())
    assert status == "interrupted"
    assert ("DELETE", "http://sim/faults/1") in [(m, u) for _, m, u, _ in fake.calls]
    assert logs[-1] == {**logs[-1], "event": "campaign_end", "status": "interrupted"}


def test_run_refused_at_start_injects_nothing():
    fake = Fake(fail_on=lambda m, u: u == "http://sim/run")
    status, fake, logs = run(make(TWO), fake)
    assert status == "aborted" and not any(u.endswith("/faults") for _, _, u, _ in fake.calls)


def test_publisher_faults_need_a_publisher_url():
    with pytest.raises(RunnerError, match="publisher"):
        Runner(make(TWO), {"simulator": "http://sim"}, JsonLogger("x", None, io.StringIO())).check_urls()


def test_simulator_only_campaign_needs_no_publisher_url():
    c = make([{"at_s": 1, "duration_s": 2, "target": "simulator", "type": "dropout"}])
    status, fake, _ = run(c, urls={"simulator": "http://sim"})
    assert status == "completed" and all(u.startswith("http://sim") for _, _, u, _ in fake.calls)


def test_cli_list_and_dry_run(capsys):
    assert main(["list"]) == 0
    assert "thermal_runaway" in capsys.readouterr().out
    assert main(["run", "thermal_runaway", "--dry-run"]) == 0
    events = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    assert events[0]["event"] == "campaign_plan" and [e["action"] for e in events[1:]] == ["inject", "clear"]


def test_cli_errors_exit_2(capsys):
    assert main(["run", "no_such_campaign"]) == 2
    assert main(["run", "transport_drop"]) == 2      # needs a publisher URL
    err = capsys.readouterr().err
    assert "no campaign file" in err and "publisher" in err


def test_campaign_log_publishes_campaign_events_only_with_the_run_id():
    pytest.importorskip("uprotocol")
    from fault_injector.bus import CampaignLog

    fake, out, published = Fake(), io.StringIO(), []
    log = CampaignLog(JsonLogger("fault-injector", None, out), published.append)
    status = Runner(make(TWO), URLS, log, fake.http, fake.sleep, lambda: fake.t).run()
    logged = [json.loads(l)["event"] for l in out.getvalue().splitlines()]
    assert status == "completed" and [e.event for e in published] == logged
    assert {e.run_id for e in published} == {"r1"} and [e.seq for e in published] == list(range(1, len(logged) + 1))
    start, end = published[0], published[-1]
    assert start.data["expected_state"] == "CRITICAL" and start.data["max_detect_ms"] == 5000
    assert end.event == "campaign_end" and end.data == {"status": "completed"}
    log.log("plan_step", at_s=1)   # not a campaign event: logged, not published
    assert len(published) == len(logged)
