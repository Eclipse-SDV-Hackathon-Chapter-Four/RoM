# Made with Claude (Claude Code, Anthropic)
"""HTTP API and pages (FastAPI). The app only reads the store; recording runs in __main__.

    GET /health                              200 when subscribed to the bus, else 503
    GET /evidence?run_id=&limit=             newest records first
    GET /evidence/summary?run_id=            pass rate, coverage per safety goal, slowest detection
    GET /evidence/consistency?run_id=        reruns of the same campaign: same verdict? latency spread
    GET /evidence/bundle.zip?run_id=&since=  evidence bundle with SHA-256 manifest (all records, one run_id, and/or
                                             runs started at or after `since`, epoch ms)
    GET /evidence/{record_id}                one record
    GET /events?since=&limit=                raw bus messages (events.jsonl lines)
    GET /ui/, /ui/{record_id}                HTML pages
"""
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from . import bundle, report
from .correlator import SAFE_ID


def create_app(store, safety_case_text: str, healthy: Callable[[], dict] = lambda: {"ok": True}) -> FastAPI:
    app = FastAPI(title="RoM Evidence Collector")

    @app.get("/health")
    def health(response: Response):
        status = healthy()
        response.status_code = 200 if status.get("ok") else 503
        return status

    @app.get("/evidence")
    def evidence(run_id: Optional[str] = None, limit: int = Query(100, ge=1, le=1000)):
        return store.records(run_id, limit)

    @app.get("/evidence/summary")
    def evidence_summary(run_id: Optional[str] = None):
        return report.summary(store.records(run_id))

    @app.get("/evidence/consistency")
    def evidence_consistency(run_id: Optional[str] = None):
        return report.consistency(store.records(run_id))

    # declared before /evidence/{record_id}, or "bundle.zip" would be taken for a record id
    @app.get("/evidence/bundle.zip")
    def evidence_bundle(run_id: Optional[str] = None, since: int = Query(0, ge=0)):
        if run_id is not None and not SAFE_ID.match(run_id):
            raise HTTPException(400, "invalid run_id")
        records = [r for r in store.records(run_id) if (r.get("started_at") or 0) >= since]
        if not records:
            raise HTTPException(404, "no evidence records" + (f" for {run_id}" if run_id else ""))
        name = run_id or "all"
        data = bundle.build(name, records, lambda a, b: store.events(a - 1, b - a + 1, b), safety_case_text)
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="evidence-{name}.zip"'})

    @app.get("/evidence/{record_id}")
    def one(record_id: str):
        record = store.record(record_id)
        if record is None:
            raise HTTPException(404, f"no evidence record {record_id}")
        return record

    @app.get("/events")
    def events(since: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=5000)):
        return store.events(since, limit)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/ui/")

    @app.get("/ui/", response_class=HTMLResponse)
    def ui(run_id: Optional[str] = None):
        return report.report_html(store.records(run_id), "RoM evidence", link=lambda rid: rid)   # relative, so it also works behind the dashboard proxy

    @app.get("/ui/{record_id}", response_class=HTMLResponse)
    def ui_record(record_id: str):
        record = store.record(record_id)
        if record is None:
            raise HTTPException(404, f"no evidence record {record_id}")
        return report.record_html(record)

    return app
