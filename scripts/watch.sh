#!/usr/bin/env bash
# Made with Claude (Claude Code, Anthropic)
# One fault campaign, watched live in one terminal: simulator -> guardian -> DFM -> OpenSOVD, then the verdict.
#   make watch C=thermal_runaway        (stack from docker compose; started if it is not up)
set -euo pipefail
cd "$(dirname "$0")/.."
C=${1:-thermal_runaway}
DC="docker compose -f infra/docker-compose.yml --profile tools"
EVIDENCE=http://127.0.0.1:8082

echo "== stack up (first time: builds images)"
$DC build -q fault-injector >/dev/null 2>&1
$DC up -d --build databroker simulator vss-uprotocol-client guardian dfm opensovd evidence-collector >/dev/null 2>&1
echo "== waiting for the guardian to be calm (MONITORING)"
until curl -sf "$EVIDENCE/health" | grep -q '"guardian_state":"MONITORING"'; do sleep 2; done
BEFORE=$(curl -sf "$EVIDENCE/evidence?limit=1000" | jq length)

echo "== campaign $C   (time = seconds since the fault went in)"
{
  $DC logs -f --no-color --since 1s simulator guardian dfm &
  LOGS=$!
  $DC run --rm -T fault-injector rom-fault-injector run "$C" || true
  sleep 3; kill $LOGS
} 2>/dev/null | python3 scripts/watch_fmt.py

echo "== waiting for the verdict"
until [ "$(curl -sf "$EVIDENCE/evidence?limit=1000" | jq length)" -gt "$BEFORE" ]; do sleep 1; done
sleep 2
curl -sf "$EVIDENCE/evidence?limit=1" | jq -r '.[0] | "\n   \(.verdict)  \(.run_id)\(if .as_expected == false then "  (UNEXPECTED, expected \(.campaign.expected_verdict // "PASS"))" elif .verdict != "PASS" then "  (as expected)" else "" end)\n" + ([.reasons[].text] | map("   - " + .) | join("\n"))'
ID=$(curl -sf "$EVIDENCE/evidence?limit=1" | jq -r '.[0].record_id')
echo "   report: $EVIDENCE/ui/$ID"
xdg-open "$EVIDENCE/ui/$ID" >/dev/null 2>&1 || true
