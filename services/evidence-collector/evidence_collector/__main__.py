# Made with Claude (Claude Code, Anthropic)
"""RoM Evidence Collector: records every RoM uProtocol message, correlates each fault campaign run, checks OpenSOVD,
and stores a PASS / FAIL / INCONCLUSIVE evidence record per run (hazard -> safety goal -> requirement -> injected
fault -> detection -> diagnostics -> mitigation -> verdict). See README.md.

    rom-evidence-collector             subscribe and serve http://EVIDENCE_HTTP_HOST:EVIDENCE_HTTP_PORT (8082)
    rom-evidence-collector --check     validate the safety case and exit
    rom-evidence-collector replay events.jsonl       judge a recording again, offline (prints one line per run)
    rom-evidence-collector verify evidence-all.zip   bundle checksums + every record judged again; exit 0 = all match
"""
import argparse
import sys
import threading
from typing import Optional

from rom_common import jsonlog

from . import safety_case
from .config import settings

TICK_S = 0.5


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="rom-evidence-collector", description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true", help="validate the safety case and exit")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("replay", help="judge a recorded events.jsonl again, offline").add_argument("events")
    sub.add_parser("verify", help="check an evidence bundle and judge its records again").add_argument("bundle")
    a = p.parse_args(argv)
    if a.command == "verify":
        from .replay import verify
        ok, lines = verify(a.bundle)
        print("\n".join(lines))
        print("bundle verified" if ok else "bundle NOT verified")
        return 0 if ok else 1
    cfg, log = settings(), jsonlog.get_logger("evidence-collector")
    try:
        case = safety_case.load(cfg.safety_case)   # refuse to start on a broken hazard -> goal -> requirement chain
    except safety_case.SafetyCaseError as e:
        log.log("safety_case_invalid", error=str(e))
        return 2
    log.log("safety_case_loaded", path=str(cfg.safety_case), hazards=len(case.hazards), goals=len(case.goals),
            requirements=len(case.requirements))
    if a.check:
        return 0
    if a.command == "replay":
        from .replay import replay, read_jsonl
        from pathlib import Path
        for r in replay(read_jsonl(Path(a.events).read_text()), case):
            print(f"{r['verdict']:13} {r['record_id']}  " + "; ".join(x["text"] for x in r["reasons"]))
        return 0

    import uvicorn

    from rom_uprotocol import uris
    from rom_uprotocol.transport import make_transport

    from .api import create_app
    from .correlator import Correlator
    from .recorder import Recorder, subscribe
    from .sovd import SovdClient
    from .store import Store

    store = Store(cfg.db_path, cfg.evidence_dir)
    sovd = SovdClient(cfg.sovd_url, cfg.sovd_app)
    # every OpenSOVD answer is recorded in events.jsonl (topic "sovd"), so a run can be judged again offline
    correlator = Correlator(store.save, lambda code: recorder.record_sovd(code, sovd.check(code)), case, log,
                            grace_ms=cfg.grace_ms,
                            diag_timeout_ms=cfg.diag_timeout_ms, end_timeout_ms=cfg.end_timeout_ms)
    recorder = Recorder(cfg.events_path, store, correlator, log)
    transport = make_transport(uris.evidence_collector_uri())   # keep a reference, or the Zenoh session closes
    keys = subscribe(transport, recorder)
    subscribed = all(not k.startswith("error") for k in keys.values())
    log.log("subscribed", topics=keys, events=str(cfg.events_path), first_line=recorder.line + 1)

    stop = threading.Event()

    def ticker():
        while not stop.wait(TICK_S):
            try:
                recorder.tick()
            except Exception as e:   # keep ticking: one bad OpenSOVD answer must not stop the verdicts
                log.log("tick_error", error=repr(e))

    threading.Thread(target=ticker, name="tick", daemon=True).start()
    app = create_app(store, case.text, lambda: {"ok": subscribed, "topics": keys, "received": recorder.received,
                                                "open_run": correlator.window.run_id if correlator.window else None,
                                                "guardian_state": correlator.state["state"] if correlator.state else None})
    try:
        uvicorn.run(app, host=cfg.http_host, port=cfg.http_port, log_level="warning")   # handles SIGTERM / Ctrl+C
    finally:
        stop.set()
        recorder.flush()
        transport.close_sync()
        store.close()
        log.log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
