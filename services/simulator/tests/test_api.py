# Made with Claude (Claude Code, Anthropic)
import io
import json
import urllib.error
import urllib.request

import pytest

from rom_common.jsonlog import JsonLogger
from simulator.api import build_api
from simulator.faults import FaultState
from simulator.simulator import Session


def call(server, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def env():
    out = io.StringIO()
    log, faults, session = JsonLogger("simulator", "r0", out), FaultState(), Session(seed=3, run_id="r0")
    server = build_api(session, faults, log, "127.0.0.1", 0).start()
    yield server, faults, session, out
    server.close()


def events(out):
    return [json.loads(l) for l in out.getvalue().splitlines()]


def test_inject_list_and_clear_a_fault(env):
    server, faults, _, out = env
    status, fault = call(server, "POST", "/faults",
                         {"type": "drift", "cell": 1, "params": {"rate_c_per_s": 2}, "duration_s": 30})
    assert status == 201 and fault["cells"] == [1] and fault["duration_s"] == 30.0
    assert call(server, "GET", "/faults") == (200, [fault])
    assert call(server, "DELETE", f"/faults/{fault['id']}") == (200, {"cleared": fault["id"]})
    assert faults.active() == []
    assert [(e["event"], e.get("reason")) for e in events(out)] == [("fault_injected", None), ("fault_cleared", "api")]


def test_cells_list_and_all_cells_default(env):
    server, _, _, _ = env
    assert call(server, "POST", "/faults", {"type": "dropout", "cells": [2, 4]})[1]["cells"] == [2, 4]
    assert call(server, "POST", "/faults", {"type": "stuck"})[1]["cells"] == []


def test_invalid_fault_is_422_and_not_added(env):
    server, faults, _, _ = env
    for body in ({"type": "nope"}, {"type": "stuck", "cell": 9}, {"type": "drift", "cell": 1}, {}):
        assert call(server, "POST", "/faults", body)[0] == 422
    assert call(server, "POST", "/faults")[0] == 400
    assert faults.active() == []


def test_clear_unknown_fault_is_404(env):
    server, _, _, _ = env
    assert call(server, "DELETE", "/faults/42")[0] == 404
    assert call(server, "DELETE", "/faults/abc")[0] == 404


def test_clear_all(env):
    server, faults, _, _ = env
    a, b = faults.add("dropout"), faults.add("stuck")
    assert call(server, "DELETE", "/faults") == (200, {"cleared": [a.id, b.id]})
    assert faults.active() == []


def test_run_sets_run_id_seed_clears_faults_and_restarts(env):
    server, faults, session, out = env
    faults.add("dropout")
    assert call(server, "POST", "/run", {"run_id": "camp-1", "seed": 42}) == (200, {"run_id": "camp-1", "seed": 42})
    assert faults.active() == [] and session.seed == 42 and session.take_restart() == {}
    assert events(out)[-1]["run_id"] == "camp-1"


def test_run_validates_input(env):
    server, _, _, _ = env
    assert call(server, "POST", "/run", {"seed": "x"})[0] == 422
    assert call(server, "POST", "/run", {"run_id": 5})[0] == 422


def test_state_reports_what_the_loop_published(env):
    server, _, session, _ = env
    session.publish(cells={1: 40.0}, max_c=40.0, stalled=False, source_time_s=1.0, faults=[])
    status, state = call(server, "GET", "/state")
    assert status == 200 and state["run_id"] == "r0" and state["seed"] == 3 and state["max_c"] == 40.0


def test_run_passes_wave_settings_to_the_loop(env):
    server, _, session, _ = env
    body = {"run_id": "r", "seed": 1, "min_c": 25, "max_c": 32, "period_s": 60}
    assert call(server, "POST", "/run", body) == (200, {"run_id": "r", "seed": 1, "min_c": 25.0, "max_c": 32.0, "period_s": 60.0})
    assert session.take_restart() == {"min_c": 25.0, "max_c": 32.0, "period_s": 60.0}
    assert session.take_restart() is None


@pytest.mark.parametrize("bad", [{"min_c": 30, "max_c": 20}, {"min_c": 30}, {"period_s": 0}, {"max_c": "hot", "min_c": 1}])
def test_run_rejects_bad_wave_settings(env, bad):
    server, _, session, _ = env
    assert call(server, "POST", "/run", bad)[0] == 422 and session.take_restart() is None


def test_heartbeat_loss_over_the_api(env):
    server, faults, _, _ = env
    status, fault = call(server, "POST", "/faults", {"type": "heartbeat_loss", "params": {"component": "chip"}})
    assert status == 201 and faults.heartbeat_lost("chip")
    assert call(server, "POST", "/faults", {"type": "heartbeat_loss", "params": {"component": "x"}})[0] == 422
