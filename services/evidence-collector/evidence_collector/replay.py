# Made with Claude (Claude Code, Anthropic)
"""Judge recorded runs again, without the stack: events.jsonl (or an evidence bundle) in, evidence records out.

    rom-evidence-collector replay events.jsonl      verdict of every run in the recording
    rom-evidence-collector verify evidence-all.zip  checksums of the bundle + every record judged again from its
                                                    own events.jsonl and safety_case.yaml; exit 0 = all match

The recorded lines go through the same parser, correlator and verdict rules as live. The collector's clock is the
lines' rx_ts_ms, ticks every TICK_MS in between, and OpenSOVD is the recorded answers (topic "sovd"): at a tick the
correlator gets the newest answer recorded up to that moment. A run is "the same" when its verdict and reasons are;
the OpenSOVD visibility time may differ by one tick, the latencies from message timestamps do not.
"""
import hashlib
import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from . import safety_case as safety_case_mod
from .correlator import Correlator
from .recorder import parse, route

TICK_MS = 500
NO_ANSWER = {"visible": False, "confirmed": False, "run_id": None, "status": None,
             "error": "no recorded OpenSOVD answer"}


class _Clock:
    def __init__(self):
        self.t: Optional[int] = None

    def __call__(self):
        return self.t


def replay(entries: Iterable[dict], case, grace_ms: int = 5000, diag_timeout_ms: int = 5000,
           end_timeout_ms: int = 30000) -> List[dict]:
    """Evidence records of every run in `entries` (events.jsonl lines as dicts), in the order they closed."""
    records, clock, answers = [], _Clock(), defaultdict(list)   # code -> [(rx_ts_ms, answer)]

    def sovd(code: str) -> dict:
        found = [a for t, a in answers[code] if t <= clock.t]
        return dict(found[-1]) if found else {"url": None, **NO_ANSWER}

    c = Correlator(records.append, sovd, case, now=clock, grace_ms=grace_ms, diag_timeout_ms=diag_timeout_ms,
                   end_timeout_ms=end_timeout_ms)

    def advance(to: int) -> None:
        if clock.t is None:
            clock.t = to
            return
        while clock.t + TICK_MS <= to:
            clock.t += TICK_MS
            c.tick()
        clock.t = to

    pending_sovd = False
    for e in sorted(entries, key=lambda e: e["line"]):
        if pending_sovd and e["rx_ts_ms"] > clock.t:   # the live tick that asked OpenSOVD: ask again, same moment
            c.tick()
            pending_sovd = False
        advance(e["rx_ts_ms"])
        payload = e["payload"] if isinstance(e["payload"], str) else json.dumps(e["payload"])
        if e["topic"] == "sovd":
            answer = json.loads(payload)
            answers[answer.pop("code")].append((e["rx_ts_ms"], answer))
            c.on_other(e["line"])
            pending_sovd = True
            continue
        item, _ = parse(e["topic"], payload)
        route(c, e["topic"], item, e["line"])
    if pending_sovd:
        c.tick()
    for _ in range(10_000):            # let the last run close as it would live (grace, OpenSOVD, end timeout)
        if c.window is None or clock.t is None:
            break
        advance(clock.t + TICK_MS)
    c.flush()
    return records


def read_jsonl(text: str) -> List[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def same(a: dict, b: dict) -> bool:
    return (a["verdict"], [r["text"] for r in a["reasons"]]) == (b["verdict"], [r["text"] for r in b["reasons"]])


def verify(bundle_path) -> Tuple[bool, List[str]]:
    """(ok, report lines) for an evidence bundle."""
    out, ok = [], True
    with zipfile.ZipFile(bundle_path) as z:
        manifest = json.loads(z.read("manifest.json"))
        for name, digest in sorted(manifest["files"].items()):
            if hashlib.sha256(z.read(name)).hexdigest() != digest:
                ok = False
                out.append(f"CHANGED   {name}: sha256 differs from manifest.json")
        if ok:
            out.append(f"checksums ok ({len(manifest['files'])} files)")
        case = safety_case_mod.parse(z.read("safety_case.yaml").decode())
        stored = {json.loads(z.read(n))["record_id"]: json.loads(z.read(n))
                  for n in z.namelist() if n.startswith("evidence/") and n.endswith(".json")}
        again = {r["record_id"]: r for r in replay(read_jsonl(z.read("events.jsonl").decode()), case)}
    for rid, record in sorted(stored.items()):
        r = again.get(rid)
        if r is None:
            ok = False
            out.append(f"MISSING   {rid}: not reproduced from events.jsonl")
        elif not same(record, r):
            ok = False
            out.append(f"DIFFERS   {rid}: stored {record['verdict']}, replayed {r['verdict']} "
                       f"{[x['text'] for x in r['reasons']]}")
        else:
            out.append(f"same      {rid}: {r['verdict']}")
    return ok, out


def replay_file(path) -> List[dict]:
    return replay(read_jsonl(Path(path).read_text()), safety_case_mod.load())

