#!/usr/bin/env bash
# Made with Claude (Claude Code, Anthropic)
# Final orchestrated run under Eclipse Ankaios (podman), one command, nothing to do by hand:
#   images -> network + volumes -> ank-server + ank-agent -> stack (infra/ankaios/rom.yaml) -> fault campaigns
#   -> evidence (logs of every workload + SOVD faults) -> evidence collector -> teardown.
# Everything of a run lands in runs/<RUN_ID>/ (input of the evidence collector, see infra/ankaios/README.md).
#
#   scripts/final_run.sh                                    all bundled campaigns
#   CAMPAIGNS="thermal_runaway sensor_stuck_cell3" scripts/final_run.sh
#   KEEP=1 scripts/final_run.sh                             leave the stack running afterwards
set -euo pipefail
cd "$(dirname "$0")/.."

RUN_ID=${RUN_ID:-$(date +%Y%m%d-%H%M%S)}
RUN_DIR=$PWD/runs/$RUN_ID
CAMPAIGNS=${CAMPAIGNS:-}          # empty = every bundled campaign (rom-fault-injector list)
SETTLE_S=${SETTLE_S:-15}          # before the first and after every campaign: guardian back to MONITORING
KEEP=${KEEP:-0}
ANK_ADDR=127.0.0.1:25551
export ANK_INSECURE=true ANK_SERVER_URL=http://$ANK_ADDR
AGENT=rom_hpc
STACK="mosquitto databroker simulator vss-uprotocol-client dfm guardian opensovd"
SOVD_URL=http://127.0.0.1:7690/sovd

say() { printf '\n== %s\n' "$*"; }

# SOVD (7690) must be ours, not the docker compose dev stack's: the evidence would come from the wrong DFM
for port in 7690 25551; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "port $port is taken (docker compose dev stack still up? make down) - stop it first"; exit 1
  fi
done
mkdir -p "$RUN_DIR/logs" "$RUN_DIR/ankaios/agent"

say "images (podman, log: runs/$RUN_ID/build.log)"
{
  for s in simulator vss-uprotocol-client guardian dfm opensovd fault-injector evidence-collector; do
    podman build -f "services/$s/Dockerfile" -t "localhost/rom/$s:dev" .
  done
  podman build -f infra/databroker/Dockerfile -t localhost/rom/databroker:dev .
} > "$RUN_DIR/build.log" 2>&1 || { tail -20 "$RUN_DIR/build.log"; exit 1; }

say "podman network + fresh volumes"
podman ps -aq --filter "label=agent=$AGENT" | xargs -r podman rm -f >/dev/null   # leftovers of an aborted run
podman network exists rom || podman network create rom >/dev/null
for v in rom-iceoryx2-shm rom-iceoryx2 rom-dfm-storage; do podman volume rm -f "$v" >/dev/null 2>&1 || true; done
# iceoryx2 shm + service files live and die together (see services/opensovd/README.md); fresh DFM records per run
podman volume create --opt type=tmpfs --opt device=tmpfs rom-iceoryx2-shm >/dev/null
podman volume create --opt type=tmpfs --opt device=tmpfs rom-iceoryx2 >/dev/null
podman volume create rom-dfm-storage >/dev/null

say "Ankaios server + agent $AGENT"
# own config files: /etc/ankaios/ank-server.conf may start a demo startup manifest
ank-server -k -x infra/ankaios/ank-server.conf -a "$ANK_ADDR" > "$RUN_DIR/ankaios/server.log" 2>&1 &
SERVER=$!
ank-agent -k -x infra/ankaios/ank-agent.conf -n "$AGENT" -s "http://$ANK_ADDR" -r "$RUN_DIR/ankaios/agent" \
  > "$RUN_DIR/ankaios/agent.log" 2>&1 &
AGENT_PID=$!

cleanup() {
  if [ "$KEEP" = 1 ]; then
    say "KEEP=1: stack still running. SOVD: $SOVD_URL  ank: ANK_INSECURE=true ank get workloads"
    say "stop it: kill $SERVER $AGENT_PID; podman ps -aq --filter label=agent=$AGENT | xargs -r podman rm -f"
    return
  fi
  say "teardown"
  ank -q delete workload $STACK campaigns evidence-collector >/dev/null 2>&1 || true
  kill "$AGENT_PID" "$SERVER" 2>/dev/null || true
  wait 2>/dev/null || true
  podman ps -aq --filter "label=agent=$AGENT" | xargs -r podman rm -f >/dev/null 2>&1
}
trap cleanup EXIT

until ank -q get state >/dev/null 2>&1; do sleep 0.5; done
until ank get state -o json | jq -e ".agents.$AGENT" >/dev/null 2>&1; do sleep 0.5; done

say "stack: $STACK"
ank apply infra/ankaios/rom.yaml > "$RUN_DIR/ankaios/apply.log"
until curl -sf -o /dev/null "$SOVD_URL/v1/apps/battery_guardian/faults"; do sleep 1; done   # dfm + opensovd up

# finished = the workload's execution state is Succeeded or Failed
state() { ank get state -o json | jq -r ".workloadStates.$AGENT.\"$1\" | to_entries[0].value.state // empty"; }
wait_done() { until state "$1" | grep -qE 'Succeeded|Failed'; do sleep 2; done; state "$1"; }

say "campaigns: ${CAMPAIGNS:-all bundled} (settle ${SETTLE_S}s around each)"
cat > "$RUN_DIR/ankaios/campaigns.yaml" <<EOF
apiVersion: v1
workloads:
  campaigns:
    runtime: podman
    agent: $AGENT
    restartPolicy: NEVER
    dependencies:
      guardian: ADD_COND_RUNNING
      simulator: ADD_COND_RUNNING
      opensovd: ADD_COND_RUNNING
    runtimeConfig: |
      image: localhost/rom/fault-injector:dev
      commandOptions: ["--network", "rom", "-e", "SIMULATOR_URL=http://simulator:8080",
                       "-e", "PUBLISHER_URL=http://vss-uprotocol-client:8081",
                       "-e", "CAMPAIGNS=$CAMPAIGNS", "-e", "SETTLE_S=$SETTLE_S"]
      commandArgs: ["sh", "-c", "sleep \$SETTLE_S; rc=0; for c in \${CAMPAIGNS:-\$(rom-fault-injector list)}; do rom-fault-injector run \$c || rc=1; sleep \$SETTLE_S; done; exit \$rc"]
EOF
ank apply "$RUN_DIR/ankaios/campaigns.yaml" >> "$RUN_DIR/ankaios/apply.log"
until state campaigns | grep -q .; do sleep 1; done
ank logs -f campaigns 2>/dev/null | jq -Rr --unbuffered 'fromjson? | select(.event == "campaign_end")
  | "   \(.run_id): \(.status)"' &
FOLLOW=$!
CAMPAIGNS_STATE=$(wait_done campaigns)
kill "$FOLLOW" 2>/dev/null || true

say "evidence -> runs/$RUN_ID/"
for w in $STACK campaigns; do ank logs "$w" > "$RUN_DIR/logs/$w.log" 2>&1 || true; done
curl -sf "$SOVD_URL/v1/apps/battery_guardian/faults" > "$RUN_DIR/sovd_faults.json" || echo "   SOVD not reachable"
jq -n --arg run_id "$RUN_ID" --arg campaigns "$CAMPAIGNS_STATE" --arg ankaios "$(ank --version)" \
  '{run_id: $run_id, campaigns_state: $campaigns, ankaios: $ankaios}' > "$RUN_DIR/run.json"

say "evidence collector"
cat > "$RUN_DIR/ankaios/evidence.yaml" <<EOF
apiVersion: v1
workloads:
  evidence-collector:
    runtime: podman
    agent: $AGENT
    restartPolicy: NEVER
    runtimeConfig: |
      image: localhost/rom/evidence-collector:dev
      # --user 0: rootless podman maps it to you, so the report can be written into runs/$RUN_ID
      commandOptions: ["--network", "rom", "--user", "0", "-v", "$RUN_DIR:/evidence:z",
                       "-e", "EVIDENCE_DIR=/evidence", "-e", "RUN_ID=$RUN_ID", "-e", "SOVD_URL=http://opensovd:7690/sovd"]
EOF
ank apply "$RUN_DIR/ankaios/evidence.yaml" >> "$RUN_DIR/ankaios/apply.log"
until state evidence-collector | grep -q .; do sleep 1; done
echo "   $(wait_done evidence-collector)"
ank logs evidence-collector > "$RUN_DIR/logs/evidence-collector.log" 2>&1 || true

say "done: runs/$RUN_ID  (campaigns: $CAMPAIGNS_STATE)"
ls "$RUN_DIR" "$RUN_DIR/logs"
