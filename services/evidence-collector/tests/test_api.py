# Made with Claude (Claude Code, Anthropic)
import hashlib
import io
import json
import zipfile

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from evidence_collector import safety_case  # noqa: E402
from evidence_collector.api import create_app  # noqa: E402
from evidence_collector.sovd import SovdClient, interpret  # noqa: E402
from evidence_collector.store import Store  # noqa: E402


def record(rid, run_id="r1", verdict="PASS", lines=(1, 2), started_at=1000):
    return {"record_id": rid, "run_id": run_id, "started_at": started_at, "verdict": verdict, "reasons": [],
            "trace": [{"requirement": {"id": "SR-01", "description": "d"},
                       "safety_goal": {"id": "SG1", "description": "d"}, "hazards": [{"id": "H1", "description": "d"}]}],
            "campaign": {"hazard": "H1", "safety_goal": "SG1"}, "detection": {"faults": [{"code": "c", "latency_ms": 7}]},
            "lines": list(lines), "raw_events": f"events.jsonl#L{lines[0]}-L{lines[1]}"}


@pytest.fixture
def client(tmp_path):
    store = Store(tmp_path / "e.db", tmp_path / "ev")
    for line in range(1, 6):
        store.add_event(line, line, "state", None, json.dumps({"line": line, "topic": "state"}))
    store.save(record("r1@1", lines=(1, 2)))
    store.save(record("r2@2", run_id="r2", verdict="FAIL", lines=(4, 5), started_at=2000))
    return TestClient(create_app(store, safety_case.DEFAULT_PATH.read_text(), lambda: {"ok": False}))


def test_records_summary_and_events(client):
    assert [r["record_id"] for r in client.get("/evidence").json()] == ["r2@2", "r1@1"]
    assert [r["record_id"] for r in client.get("/evidence?run_id=r1").json()] == ["r1@1"]
    assert client.get("/evidence/r2@2").json()["verdict"] == "FAIL"
    assert client.get("/evidence/nope").status_code == 404
    s = client.get("/evidence/summary").json()
    assert s["pass_rate"] == 0.5 and s["coverage"] == {"SG1": {"PASS": 1, "FAIL": 1}}
    assert [e["line"] for e in client.get("/events?since=3").json()] == [4, 5]
    assert client.get("/health").status_code == 503


def test_bundle_has_only_the_referenced_lines_and_valid_checksums(client):
    resp = client.get("/evidence/bundle.zip")
    assert resp.status_code == 200 and 'filename="evidence-all.zip"' in resp.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    manifest = json.loads(z.read("manifest.json"))
    assert set(manifest["files"]) == {"evidence/r1@1.json", "evidence/r2@2.json", "events.jsonl", "safety_case.yaml",
                                      "report.html"}
    for name, digest in manifest["files"].items():
        assert hashlib.sha256(z.read(name)).hexdigest() == digest
    assert [json.loads(l)["line"] for l in z.read("events.jsonl").decode().splitlines()] == [1, 2, 4, 5]
    one = zipfile.ZipFile(io.BytesIO(client.get("/evidence/bundle.zip?run_id=r1").content))
    assert "evidence/r2@2.json" not in one.namelist()
    assert client.get("/evidence/bundle.zip?run_id=../x").status_code == 400
    assert client.get("/evidence/bundle.zip?run_id=none").status_code == 404
    late = zipfile.ZipFile(io.BytesIO(client.get("/evidence/bundle.zip?since=1500").content))
    assert [n for n in late.namelist() if n.startswith("evidence/")] == ["evidence/r2@2.json"]


def test_html_pages(client):
    page = client.get("/ui/")
    assert page.status_code == 200 and 'href="r1@1"' in page.text and "Coverage by safety goal" in page.text
    assert "r2@2" in client.get("/ui/r2@2").text and client.get("/ui/nope").status_code == 404


def test_sovd_answer_is_interpreted_and_an_unreachable_server_is_a_result():
    body = {"item": {"code": "c", "status": {"confirmed_dtc": True}}, "environment_data": {"run_id": "r1"}}
    r = interpret(body, {})
    assert (r["visible"], r["confirmed"], r["run_id"]) == (True, True, "r1")
    assert interpret({"items": []}, {})["error"] == "answer without item"
    down = SovdClient("http://127.0.0.1:9/sovd", "battery_guardian", timeout_s=0.5).check("battery_guardian.x")
    assert down["visible"] is False and down["error"].startswith("OpenSOVD unreachable")
    assert down["url"] == "http://127.0.0.1:9/sovd/v1/apps/battery_guardian/faults/battery_guardian.x"


def test_rerun_consistency(client):
    from evidence_collector.report import consistency

    rs = [record("a@1", "a", "PASS"), record("a@2", "a", "PASS"), record("a@3", "a", "INCONCLUSIVE"),
          record("b@1", "b", "PASS"), record("b@2", "b", "FAIL")]
    rs[1]["detection"]["faults"][0]["latency_ms"] = 12
    c = consistency(rs)
    assert c["a"]["consistent"] and c["a"]["executions"] == 3 and c["a"]["latency_ms"] == {"c": {"min": 7, "max": 12}}
    assert not c["b"]["consistent"] and c["b"]["verdicts"] == {"PASS": 1, "FAIL": 1}
    assert client.get("/evidence/consistency").json()["r1"]["executions"] == 1
