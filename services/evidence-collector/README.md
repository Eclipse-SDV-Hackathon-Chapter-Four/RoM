<!-- Made with Claude (Claude Code, Anthropic) -->
# evidence-collector — Evidence Collector

Listens to **every RoM uProtocol topic**, groups the messages of one fault campaign run, asks Eclipse OpenSOVD whether
the expected DTCs are really there **for this run**, and stores a **PASS / FAIL / INCONCLUSIVE** evidence record with
readable reasons. Each record proves the chain
**hazard → safety goal → safety requirement → injected fault → detection → diagnostics (DTC) → mitigation → verdict**.
All records can be downloaded as a ZIP **with SHA-256 checksums**.

```
fault-injector --up://…/1003/1/8005 campaign events--+
guardian ------up://…/1002/1/8006 state--------------+
guardian ------up://…/1002/1/8003 fault events-------+--> Recorder --> events.jsonl + SQLite (every message, numbered)
client --------up://…/1001/1/8002 cells, …/8004 hb---+        |
                                                              v
                                    Correlator (one window per run) --GET faults/{code}--> OpenSOVD
                                                              v
                                    verdict.judge() --> evidence/<record_id>.json --> HTTP API, HTML, bundle.zip
```

Everything comes over uProtocol: the collector never reads logs or the KUKSA Databroker.

## Run

```bash
make guardian                        # the stack, evidence-collector included
make campaign C=thermal_runaway      # one run; the record appears GRACE_MS (5 s) after campaign_end
make evidence                        # summary + newest verdicts in the terminal
open http://localhost:8082/ui/       # report: coverage per safety goal, every run with timeline
make evidence-bundle                 # evidence-all.zip  (RUN=thermal-runaway-01 for one campaign)
make campaigns-all                   # every bundled campaign in a row, then `make evidence`
```

Check a bundle somebody gave you, without any stack (checksums + every verdict judged again from the bundle's own
`events.jsonl` and `safety_case.yaml`):

```bash
pip install ./libs/rom-common ./libs/rom-uprotocol ./services/evidence-collector && pip install --no-deps up-python==0.2.0.dev0
rom-evidence-collector verify evidence-all.zip     # exit 0 = untouched and reproducible
rom-evidence-collector replay events.jsonl         # judge a whole recording again (e.g. the collector's /data/events.jsonl)
```

Run **one campaign at a time**: a second campaign started meanwhile (another terminal) mixes its faults into the
first one, and both runs become INCONCLUSIVE ("campaign X ran at the same time").

## Modules

| File | Job |
|---|---|
| `recorder.py` | one raw listener per topic; each message → numbered line in `events.jsonl` + SQLite, then the correlator. Nothing is filtered (duplicates, invalid payloads, periodic repeats). Numbering continues after a restart. The collector's own OpenSOVD answers are recorded too (topic `sovd`) |
| `replay.py` | `replay` / `verify`: recorded lines through the same parser, correlator and rules on the recorded clock, OpenSOVD = the recorded answers |
| `correlator.py` | the run window: `campaign_start` opens, `fault_injected` sets t0 and the precondition, FAILED of an expected code starts an OpenSOVD poll, `campaign_end` + grace closes |
| `verdict.py` | pure `judge(Observed) -> Judgement`, no clock, no network |
| `safety_case.yaml` / `.py` | H → SG → SR → campaigns (`run_id`); refuses to start on a broken chain |
| `sovd.py` | `GET <SOVD_URL>/v1/apps/battery_guardian/faults/{code}`; never raises |
| `store.py`, `bundle.py`, `report.py`, `api.py` | SQLite, ZIP, plain HTML (no JS), FastAPI |

## Verdict rules (`verdict.py`)

| Rule | Verdict |
|---|---|
| no `campaign_start`, no `campaign_end`, campaign `aborted` / `interrupted`, nothing injected | INCONCLUSIVE |
| guardian not `MONITORING` when the first fault went in | INCONCLUSIVE |
| an `expected_faults` code never raised (FAILED) after the first injection, or later than `max_detect_ms` | FAIL |
| `expected_state` WARNING / CRITICAL / SENSOR_FAULT / MITIGATING not reached within `max_detect_ms` | FAIL |
| `expected_state` MONITORING / CLEAR left during the run | FAIL |
| CRITICAL expected, but no MITIGATING after it (cooling never requested) | FAIL |
| a FAILED code that the campaign does not expect (false alarm), once per code | FAIL |
| expected DTC not in OpenSOVD, not confirmed, or its `environment_data.run_id` is another run | FAIL |
| campaign not in the safety case, or its `hazard` / `safety_goal` ids do not match it | INCONCLUSIVE |
| another campaign ran at the same time | INCONCLUSIVE, even over a FAIL |

FAIL wins over INCONCLUSIVE, no reasons is PASS. Latencies use the timestamps in the messages (all from the same host
clock); the OpenSOVD visibility time (`diagnostics[].latency_ms`) is measured by the collector's polling (every 500 ms).

## Evidence record

```json
{"record_id": "thermal-runaway-01@20261007T125548.449Z", "run_id": "thermal-runaway-01", "verdict": "PASS",
 "trace": [{"requirement": {"id": "SR-01", ...}, "safety_goal": {"id": "SG1", ...}, "hazards": [{"id": "H1", ...}]}],
 "campaign": {"hazard": "H1: ...", "expected_state": "CRITICAL", "expected_faults": [...], "max_detect_ms": 35000, "seed": 7, "status": "completed"},
 "injected": [{"ts_ms": ..., "target": "simulator", "type": "drift", "cells": [1], ...}],
 "state_at_injection": "MONITORING",
 "detection": {"faults": [{"code": "battery_guardian.over_temp_critical", "latency_ms": 23389, "msg_id": "01a1166f-...", ...}],
               "state": {"expected": "CRITICAL", "reached": true, "latency_ms": 23389, ...}},
 "mitigation": {"critical_at": ..., "mitigating_at": ..., "latency_ms": 1},
 "diagnostics": [{"code": "battery_guardian.over_temp_critical", "url": "http://opensovd:7690/sovd/v1/apps/battery_guardian/faults/...",
                  "visible": true, "confirmed": true, "run_id": "thermal-runaway-01", "latency_ms": 461}],
 "unexpected_faults": [], "interference": [], "reasons": [],
 "raw_events": "events.jsonl#L2604-L3447"}
```

One record per execution (`run_id@start time`), so reruns of the same campaign (e.g. remote reruns) sit side by side.
`raw_events` points to the exact lines of `events.jsonl` behind the verdict (`context_lines`: the guardian state from
before the run, the precondition); `msg_id`s are uProtocol message ids. Those lines, OpenSOVD answers included, are
enough to reach the same verdict again: `verify` does exactly that.

## HTTP API (port 8082)

| Endpoint | What |
|---|---|
| `GET /evidence?run_id=&limit=` | newest records |
| `GET /evidence/summary?run_id=` | pass rate, coverage per safety goal, slowest detection |
| `GET /evidence/bundle.zip?run_id=` | ZIP: `evidence/*.json`, the referenced `events.jsonl` lines, `safety_case.yaml`, static `report.html`, `manifest.json` (SHA-256 per file) |
| `GET /evidence/{record_id}` | one record |
| `GET /events?since=&limit=` | raw messages |
| `GET /ui/`, `GET /ui/{record_id}` | HTML report, one run with its timeline |
| `GET /health` | 200 when subscribed to every topic, else 503 |

Check a bundle: `unzip evidence-all.zip && sha256sum -c <(python3 -c 'import json; [print(h, f) for f, h in json.load(open("manifest.json"))["files"].items()]')`

## Env

| Variable | Default | |
|---|---|---|
| `EVIDENCE_DATA_DIR` | `./evidence-data` (`/data` in the image) | `events.jsonl`, `evidence.db` |
| `EVIDENCE_DIR` | `$EVIDENCE_DATA_DIR/evidence` | one JSON file per record |
| `SAFETY_CASE_PATH` | bundled `safety_case.yaml` | |
| `SOVD_URL`, `SOVD_APP` | `http://127.0.0.1:7690/sovd`, `battery_guardian` | OpenSOVD |
| `EVIDENCE_HTTP_HOST`, `EVIDENCE_HTTP_PORT` | `127.0.0.1` (`0.0.0.0` in the image), `8082` | |
| `EVIDENCE_GRACE_MS`, `EVIDENCE_DIAG_TIMEOUT_MS`, `EVIDENCE_END_TIMEOUT_MS` | `5000`, `5000`, `30000` | late messages, DTC visibility limit, missing `campaign_end` |
| `UP_AUTHORITY`, `ZENOH_*` | see [`libs/rom-uprotocol`](../../libs/rom-uprotocol/README.md) | compose: listens on 7447 (fault-injector), connects to the client and the guardian |

`rom-evidence-collector --check` validates the safety case and exits.

Replay: the clock is the lines' `rx_ts_ms`; at each tick the correlator gets the newest OpenSOVD answer recorded up to
then. "Same" means same verdict and reasons; detection latencies come from message timestamps and are identical, the
OpenSOVD visibility time can differ by one tick (500 ms).

## Test

```bash
pytest services/evidence-collector    # verdict rules, safety case (every bundled campaign is traced), correlator on a
                                      # fake clock + fake OpenSOVD (tests/bench.py), replay = live verdict, a changed
                                      # bundle does not verify, API + bundle checksums
```
