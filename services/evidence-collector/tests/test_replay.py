# Made with Claude (Claude Code, Anthropic)
"""A recording judged again offline must give the same verdicts as live; a changed bundle must not verify."""
import io
import json
import zipfile
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

import pytest

pytest.importorskip("uprotocol")

from evidence_collector import bundle, safety_case  # noqa: E402
from evidence_collector.replay import read_jsonl, replay, same, verify  # noqa: E402

_b = _bench()
CRIT, START_T, Bench, thermal_runaway = _b.CRIT, _b.START_T, _b.Bench, _b.thermal_runaway

STALE = {"code": "battery_guardian.signal_stale", "stage": "FAILED", "ts_ms": START_T + 40_000, "reason": "silent"}

SCENARIOS = {
    "pass": dict(),
    "late": dict(crit_at=36_000),
    "false_alarm": dict(extra=[("fault", STALE)]),
    "no_end": dict(end=False),
}


def live(tmp_path, sovd_run_id="thermal-runaway-01", **kw):
    b = Bench(tmp_path, sovd_run_id=sovd_run_id)
    thermal_runaway(b, **kw)
    b.at(110_000)
    return b


@pytest.mark.parametrize("name", list(SCENARIOS) + ["opensovd_other_run"])
def test_replay_gives_the_live_verdict(tmp_path, name):
    b = live(tmp_path, **SCENARIOS.get(name, {})) if name != "opensovd_other_run" else live(tmp_path, "older-run")
    [recorded] = b.store.records()
    [again] = replay(read_jsonl((tmp_path / "events.jsonl").read_text()), safety_case.load())
    assert again["record_id"] == recorded["record_id"]
    assert same(recorded, again), (recorded["reasons"], again["reasons"])
    assert [f.get("latency_ms") for f in again["detection"].get("faults", [])] == \
        [f.get("latency_ms") for f in recorded["detection"].get("faults", [])]


def test_opensovd_answers_are_recorded_inside_the_run(tmp_path):
    b = live(tmp_path)
    [r] = b.store.records()
    first, last = r["lines"]
    sovd = [e for e in b.store.events(first - 1, 10_000, last) if e["topic"] == "sovd"]
    assert {e["payload"]["code"] for e in sovd} >= {CRIT} and all("visible" in e["payload"] for e in sovd)


def _bundle(tmp_path):
    b = live(tmp_path)
    data = bundle.build("t", b.store.records(), lambda a, z: b.store.events(a - 1, z - a + 1, z),
                       safety_case.DEFAULT_PATH.read_text())
    path = tmp_path / "evidence-t.zip"
    path.write_bytes(data)
    return path


def test_bundle_verifies(tmp_path):
    ok, lines = verify(_bundle(tmp_path))
    assert ok, lines
    assert lines[0].startswith("checksums ok") and lines[1].startswith("same") and lines[1].endswith("PASS")


def test_changed_bundle_does_not_verify(tmp_path):
    path = _bundle(tmp_path)
    src = zipfile.ZipFile(path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for name in src.namelist():
            data = src.read(name)
            if name.startswith("evidence/"):
                record = json.loads(data)
                record["verdict"] = "FAIL"            # someone "fixes" a verdict
                data = json.dumps(record).encode()
            out.writestr(name, data)
    path.write_bytes(buf.getvalue())
    ok, lines = verify(path)
    assert not ok and any(l.startswith("CHANGED   evidence/") for l in lines)
    assert any(l.startswith("DIFFERS") for l in lines)
