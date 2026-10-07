# Made with Claude (Claude Code, Anthropic)
"""Formats the JSON log lines of the RoM services (stdin) into one readable timeline; polls OpenSOVD for DTC changes.

Used by scripts/watch.sh. Time column: seconds since the first injected fault (before that: since start).
"""
import json
import sys
import threading
import time
import urllib.request

SOVD = "http://127.0.0.1:7690/sovd/v1/apps/battery_guardian/faults"
COLOR = {"fault-injector": 35, "simulator": 36, "guardian": 33, "dfm": 34, "sovd": 32}
t0 = [None]
start = time.time() * 1000
lock = threading.Lock()


def out(component, text, ts_ms=None):
    ts_ms = ts_ms or time.time() * 1000
    rel = (ts_ms - (t0[0] or start)) / 1000
    with lock:
        print(f"{rel:+7.1f}s  \033[{COLOR.get(component, 37)}m{component:<14}\033[0m {text}", flush=True)


def cells(c):
    if isinstance(c, dict):
        return " ".join(f"{v:5.1f}" for _, v in sorted(c.items(), key=lambda kv: int(kv[0])))
    return c or ""


def show(e):
    ev, comp, ts = e.get("event"), e.get("component"), e.get("ts_ms")
    if comp == "simulator" and ev == "sample" and e.get("seq", 0) % 2 == 0:
        faults = ",".join(f["type"] for f in e.get("faults", [])) or "-"
        cool = f"  cooling {e['cooling_c']:+.1f}" if e.get("cooling_c") else ""
        out(comp, f"\033[2mcells {cells(e.get('cells'))}  fault {faults}{cool}\033[0m", ts)
    elif comp == "fault-injector" and ev in ("campaign_start", "fault_injected", "fault_cleared", "campaign_end"):
        if ev == "fault_injected" and t0[0] is None:
            t0[0] = ts
        detail = {"campaign_start": f"{e.get('run_id')}  expect {e.get('expected_state')} {e.get('expected_faults')}",
                  "campaign_end": e.get("status")}.get(ev, f"{e.get('type')} cells={e.get('cells')}")
        out(comp, f"\033[1m{ev}\033[0m  {detail}", ts)
    elif comp == "guardian" and ev == "state_change":
        out(comp, f"\033[1m{e.get('from')} -> {e.get('to')}\033[0m  {e.get('reason')}  temp {e.get('temp_c')}", ts)
    elif comp == "guardian" and ev == "reason_change":
        out(comp, f"\033[1m{e.get('state', '')}\033[0m  {e.get('previous_reason')} -> {e.get('reason')}", ts)
    elif comp == "guardian" and ev == "fault_event":
        out(comp, f"{e['stage']:<6} {e['code']}  ({e.get('reason')})", ts)
    elif comp == "dfm" and ev == "fault_record":
        out(comp, f"{e['stage']:<6} {e['code']}  written in {e.get('latency_ms')} ms", ts)


def poll_sovd():
    seen, first = {}, True              # first poll: DTCs left over from earlier runs, not shown
    while True:
        try:
            data = json.load(urllib.request.urlopen(SOVD, timeout=2))
            for f in data.get("items", data) if isinstance(data, dict) else data:
                s = f["status"]
                now = (s.get("test_failed"), s.get("test_failed_since_last_clear"))
                if now[1] and seen.get(f["code"]) != now and not first:
                    out("sovd", f"{f['code']}  {'ACTIVE' if now[0] else 'was active, now cleared'}")
                seen[f["code"]] = now
            first = False
        except Exception:
            pass
        time.sleep(0.5)


threading.Thread(target=poll_sovd, daemon=True).start()
for line in sys.stdin:
    i = line.find("{")
    if i < 0:
        continue
    try:
        show(json.loads(line[i:]))
    except (ValueError, KeyError, TypeError):
        pass
