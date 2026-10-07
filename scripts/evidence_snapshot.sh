#!/usr/bin/env bash
# Saves what the running Evidence Collector has recorded so far as a completed run for the dashboard's Safety Evidence view:
#   runs/<RUN_ID>/{evidence.json, summary.json, evidence-bundle.zip, bundle/}      (make evidence-snapshot)
# Everything is fetched from the collector (http://localhost:8082); nothing is generated or edited here. The bundle is
# extracted (report.html, manifest.json, ...) and checked with `rom-evidence-collector verify` unless VERIFY=0.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
API="${EVIDENCE_URL:-http://localhost:8082}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="$ROOT/runs/$RUN_ID"

curl -sf "$API/health" >/dev/null || { echo "error: Evidence Collector not reachable at $API (start the stack: make guardian)" >&2; exit 1; }
[ ! -e "$RUN_DIR" ] || { echo "error: $RUN_DIR already exists" >&2; exit 1; }
mkdir -p "$RUN_DIR"
trap 'rm -rf "$RUN_DIR"' ERR   # never leave an incomplete run behind: the dashboard only shows complete ones

curl -sf "$API/evidence?limit=1000" > "$RUN_DIR/evidence.json"
curl -sf "$API/evidence/summary" > "$RUN_DIR/summary.json"
curl -sf -o "$RUN_DIR/evidence-bundle.zip" "$API/evidence/bundle.zip"
n="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$RUN_DIR/evidence.json")"
[ "$n" -gt 0 ] || { echo "error: the collector holds no evidence records yet (run a campaign: make campaign C=thermal_runaway)" >&2; exit 1; }

mkdir -p "$RUN_DIR/bundle"
python3 -m zipfile -e "$RUN_DIR/evidence-bundle.zip" "$RUN_DIR/bundle"
[ -s "$RUN_DIR/bundle/report.html" ] || { echo "error: the bundle has no report.html" >&2; exit 1; }

if [ "${VERIFY:-1}" != 0 ]; then
  ( cd "$ROOT" && docker compose -f infra/docker-compose.yml run --rm --no-deps -T dev \
      rom-evidence-collector verify "/app/runs/$RUN_ID/evidence-bundle.zip" ) | tail -1
fi
trap - ERR
python3 - "$RUN_DIR/evidence.json" <<'P'
import collections, json, sys
c = collections.Counter(r["verdict"] for r in json.load(open(sys.argv[1])))
print(f"{sum(c.values())} records: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
P
echo "saved runs/$RUN_ID (gitignored). Safety Evidence shows the newest complete run: http://localhost:5173/#/evidence"
