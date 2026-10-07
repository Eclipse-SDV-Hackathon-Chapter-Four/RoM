# Made with Claude (Claude Code, Anthropic)
"""Plain HTML (no JavaScript): the summary over many records, and one record with its timeline.

Used by the HTTP pages and by the static report.html in the evidence bundle, so both look the same.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from typing import List, Optional

CSS = """
:root{--bg:#fff;--fg:#1d2330;--muted:#5b6475;--line:#d9dee7;--pass:#1f7a3d;--fail:#b3261e;--inc:#8a5a00;--card:#f6f8fb}
@media (prefers-color-scheme:dark){:root{--bg:#14171d;--fg:#e6e9ef;--muted:#9aa3b2;--line:#2c323d;--pass:#5fc27e;
--fail:#ff7b72;--inc:#e3b341;--card:#1b1f27}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}
h1{font-size:22px}h2{font-size:17px;margin-top:28px}a{color:inherit}
table{border-collapse:collapse;width:100%;margin:8px 0}th,td{border-bottom:1px solid var(--line);padding:6px 8px;
text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600}
.v{font-weight:700}.PASS{color:var(--pass)}.FAIL{color:var(--fail)}.INCONCLUSIVE{color:var(--inc)}
.muted{color:var(--muted)}.card{background:var(--card);border-radius:8px;padding:12px 16px;margin:8px 0}
code{font:12px ui-monospace,monospace}.scroll{overflow-x:auto}
"""


def _ts(ms: Optional[int]) -> str:
    if ms is None:
        return "–"
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"


def _ms(v) -> str:
    return "–" if v is None else f"{v} ms"


def _verdict(v: str) -> str:
    return f'<span class="v {escape(v)}">{escape(v)}</span>'


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'><title>{escape(title)}</title>"
            f"<style>{CSS}</style></head><body><h1>{escape(title)}</h1>{body}</body></html>")


def summary(records: List[dict]) -> dict:
    """Pass rate, coverage (safety goal x verdict) and the slowest detection per goal."""
    counts = Counter(r["verdict"] for r in records)
    coverage, slowest = defaultdict(Counter), {}
    for r in records:
        goals = [t["safety_goal"]["id"] for t in r.get("trace") or []] or ["(not traced)"]
        latencies = [f.get("latency_ms") for f in (r.get("detection") or {}).get("faults", [])]
        worst = max((v for v in latencies if v is not None), default=None)
        for g in goals:
            coverage[g][r["verdict"]] += 1
            if worst is not None and worst > slowest.get(g, (-1,))[0]:
                slowest[g] = (worst, r["record_id"])
    return {"total": len(records), "verdicts": dict(counts),
            "pass_rate": round(counts["PASS"] / len(records), 3) if records else None,
            "coverage": {g: dict(c) for g, c in sorted(coverage.items())},
            "slowest_detection": {g: {"latency_ms": v, "record_id": rid} for g, (v, rid) in sorted(slowest.items())}}


def report_html(records: List[dict], title: str = "Evidence report", link=None) -> str:
    """Summary + one row per record. link(record_id) -> href, or None for a self-contained file."""
    s = summary(records)
    rate = "–" if s["pass_rate"] is None else f"{s['pass_rate']:.0%}"
    head = (f"<div class=card>{s['total']} runs · pass rate {rate} · "
            + " · ".join(f"{_verdict(v)} {n}" for v, n in sorted(s["verdicts"].items())) + "</div>")
    cov = "".join(f"<tr><td>{escape(g)}</td>" + "".join(f"<td>{c.get(v, 0)}</td>" for v in ("PASS", "FAIL", "INCONCLUSIVE"))
                  + f"<td>{_ms(s['slowest_detection'].get(g, {}).get('latency_ms'))}</td></tr>"
                  for g, c in s["coverage"].items())
    cov_table = ("<h2>Coverage by safety goal</h2><div class=scroll><table><tr><th>Safety goal</th><th>PASS</th>"
                 f"<th>FAIL</th><th>INCONCLUSIVE</th><th>Slowest detection</th></tr>{cov}</table></div>")
    rows = []
    for r in records:
        rid = escape(r["record_id"])
        name = f'<a href="{escape(link(r["record_id"]))}">{rid}</a>' if link else f'<a href="#{rid}">{rid}</a>'
        goals = ", ".join(t["safety_goal"]["id"] for t in r.get("trace") or []) or "–"
        first = (r.get("detection") or {}).get("faults") or []
        lat = max((f["latency_ms"] for f in first if f.get("latency_ms") is not None), default=None)
        rows.append(f"<tr><td>{name}</td><td>{escape(goals)}</td><td>{_verdict(r['verdict'])}</td><td>{_ms(lat)}</td>"
                    f"<td>{'<br>'.join(escape(x['text']) for x in r.get('reasons', [])) or '–'}</td></tr>")
    table = ("<h2>Runs</h2><div class=scroll><table><tr><th>Run</th><th>Goal</th><th>Verdict</th><th>Detection</th>"
             f"<th>Reasons</th></tr>{''.join(rows)}</table></div>")
    details = "" if link else "".join(f'<div id="{escape(r["record_id"])}">{record_body(r)}</div>' for r in records)
    return _page(title, head + cov_table + table + details)


def record_body(r: dict) -> str:
    c, d, m = r.get("campaign") or {}, r.get("detection") or {}, r.get("mitigation") or {}
    trace = "".join(f"<tr><td>{escape(t['hazards'][0]['id'] if t['hazards'] else '–')}"
                    f"{(' +' + str(len(t['hazards']) - 1)) if len(t['hazards']) > 1 else ''}</td>"
                    f"<td>{escape(t['safety_goal']['id'])}: {escape(t['safety_goal']['description'])}</td>"
                    f"<td>{escape(t['requirement']['id'])}: {escape(t['requirement']['description'])}</td></tr>"
                    for t in r.get("trace") or [])
    out = [f"<h2>{escape(r['record_id'])} {_verdict(r['verdict'])}</h2>",
           f"<div class=card>{escape(str(c.get('hazard')))}<br>{escape(str(c.get('safety_goal')))}<br>"
           f"<span class=muted>expected {escape(str(c.get('expected_state')))} within {_ms(c.get('max_detect_ms'))}, "
           f"seed {escape(str(c.get('seed')))}, campaign {escape(str(c.get('status')))} · "
           f"guardian at injection: {escape(str(r.get('state_at_injection')))} · raw: "
           f"<code>{escape(r.get('raw_events', ''))}</code></span></div>"]
    if r.get("reasons"):
        out.append("<ul>" + "".join(f"<li class={escape(x['verdict'])}>{escape(x['text'])}</li>" for x in r["reasons"])
                   + "</ul>")
    out.append("<h3>Trace</h3><div class=scroll><table><tr><th>Hazard</th><th>Safety goal</th><th>Requirement</th>"
               f"</tr>{trace or '<tr><td colspan=3>not in the safety case</td></tr>'}</table></div>")
    det = "".join(f"<tr><td><code>{escape(f['code'])}</code></td><td>{_ts(f.get('at'))}</td><td>{_ms(f.get('latency_ms'))}</td>"
                  f"<td><code>{escape(str(f.get('msg_id') or '–'))}</code></td><td>{_ts(f.get('cleared_at'))}</td></tr>"
                  for f in d.get("faults", []))
    st = d.get("state") or {}
    state_row = (f"<p>State {escape(str(st.get('expected')))}: reached/held "
                 f"{escape(str(st.get('reached', st.get('held'))))} {_ms(st.get('latency_ms'))}</p>") if st else ""
    out.append("<h3>Detection</h3>" + state_row + "<div class=scroll><table><tr><th>Fault</th><th>Raised</th>"
               f"<th>Latency</th><th>msg_id</th><th>Cleared</th></tr>{det}</table></div>")
    if m:
        out.append(f"<p>Mitigation: CRITICAL {_ts(m.get('critical_at'))} → MITIGATING {_ts(m.get('mitigating_at'))} "
                   f"({_ms(m.get('latency_ms'))})</p>")
    diag = "".join(f"<tr><td><code>{escape(x['code'])}</code></td><td>{x.get('visible')}</td><td>{x.get('confirmed')}</td>"
                   f"<td>{escape(str(x.get('run_id')))}</td><td>{_ms(x.get('latency_ms'))}</td>"
                   f"<td>{escape(str(x.get('error') or x.get('note') or ''))}</td></tr>" for x in r.get("diagnostics", []))
    out.append("<h3>Diagnostics (OpenSOVD)</h3><div class=scroll><table><tr><th>DTC</th><th>Visible</th><th>Confirmed</th>"
               f"<th>run_id</th><th>Visible after</th><th>Note</th></tr>{diag}</table></div>")
    timeline = sorted([(i["ts_ms"], "injected" if not i.get("failed") else "inject failed",
                        f"{i.get('target')} {i.get('type')} {i.get('cells') or ''}") for i in r.get("injected", [])]
                      + [(f["ts_ms"], f["stage"], f"{f['code']} ({f.get('reason')})") for f in r.get("fault_events", [])]
                      + [(s["ts_ms"], "state", f"{s.get('previous')} → {s.get('state')} ({s.get('reason')})")
                         for s in r.get("state_changes", [])], key=lambda x: x[0])
    rows = "".join(f"<tr><td>{_ts(t)}</td><td>{escape(k)}</td><td>{escape(w)}</td></tr>" for t, k, w in timeline)
    out.append(f"<h3>Timeline</h3><div class=scroll><table><tr><th>Time</th><th>What</th><th></th></tr>{rows}</table></div>")
    return "".join(out)


def record_html(r: dict) -> str:
    return _page(f"Evidence {r['record_id']}", '<p><a href="../">← all runs</a></p>' + record_body(r))
