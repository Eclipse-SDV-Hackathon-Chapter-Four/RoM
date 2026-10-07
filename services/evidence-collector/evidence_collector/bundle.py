# Made with Claude (Claude Code, Anthropic)
"""Evidence bundle: one ZIP with everything behind the verdicts, and SHA-256 checksums to prove nothing changed.

    evidence-<name>.zip
    ├─ evidence/<record_id>.json   every evidence record
    ├─ events.jsonl                only the raw lines the records point to (original line numbers kept)
    ├─ safety_case.yaml            why each campaign exists
    ├─ report.html                 static report, opens without the server
    └─ manifest.json               {"name", "created_at", "algorithm": "sha256", "files": {name: sha256}, "how_to_check"}
"""
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Callable, List

from .report import report_html

HOW_TO_CHECK = "unzip, then compare `sha256sum <file>` with files[<file>] here; any difference means it was changed"


def build(name: str, records: List[dict], events: Callable[[int, int], List[dict]], safety_case_text: str) -> bytes:
    """events(first, last) -> the raw event entries of lines first..last."""
    files = {}
    for r in records:
        files[f"evidence/{r['record_id']}.json"] = json.dumps(r, indent=2, sort_keys=True, default=str) + "\n"
    lines = {}
    for r in records:
        first, last = r.get("lines") or (0, -1)
        for e in events(first, last):
            lines[e["line"]] = e
    files["events.jsonl"] = "".join(json.dumps(lines[n], separators=(",", ":")) + "\n" for n in sorted(lines))
    files["safety_case.yaml"] = safety_case_text
    files["report.html"] = report_html(records, title=f"Evidence report: {name}")
    manifest = {"name": name, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "algorithm": "sha256", "how_to_check": HOW_TO_CHECK,
                "files": {n: hashlib.sha256(t.encode()).hexdigest() for n, t in sorted(files.items())}}
    files["manifest.json"] = json.dumps(manifest, indent=2) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, t in files.items():
            z.writestr(n, t)
    return buf.getvalue()
