#!/usr/bin/env bash
# Dashboard dev server in Docker on http://localhost:5173 (no Node.js needed on the host): Live Monitoring, Safety Evidence
# and the "Run Scenario" control.   scripts/dashboard-dev.sh [start|stop|logs]      (make dashboard / dashboard-stop)
#
# Why the container looks the way it does:
#  * --network host       the Evidence Collector is published on the host's 127.0.0.1:8082 (Linux; see the dashboard README).
#  * docker.sock + CLI    "Run Scenario" runs `docker compose ... run fault-injector` from inside this container; the
#                         compose file is read here but the bind mounts are resolved by the HOST daemon, so
#  * same absolute path   the repository is mounted at the SAME path as on the host (not /repo), and ROM_RUNTIME_REPO is
#                         that path. That is what makes the volumes in infra/docker-compose.yml valid.
#  * --user + group       files created in the clone (node_modules) belong to you, not root; the socket's group is added.
# Overrides: ROM_RUNTIME_REPO=<checkout with the running stack> (default: this clone), DASHBOARD_PORT=5173 (do not change
# unless you also change VITE port: the dev server is started with --strictPort).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUNTIME="$(cd "${ROM_RUNTIME_REPO:-$ROOT}" && pwd -P)"
NAME=rom-dashboard-dev
IMAGE=rom/dashboard-dev:local
SOCK=/var/run/docker.sock
PORT="${DASHBOARD_PORT:-5173}"

case "${1:-start}" in
stop)
  docker rm -f "$NAME" >/dev/null 2>&1 && echo "stopped $NAME" || echo "$NAME is not running"
  exit 0 ;;
logs)
  exec docker logs -f "$NAME" ;;
start) ;;
*) echo "usage: $0 [start|stop|logs]" >&2; exit 2 ;;
esac

[ -S "$SOCK" ] || { echo "error: $SOCK not found: is Docker running?" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "error: cannot talk to Docker. Add your user to the docker group (sudo usermod -aG docker \$USER, then log in again)." >&2; exit 1; }
[ -f "$RUNTIME/infra/docker-compose.yml" ] || { echo "error: ROM_RUNTIME_REPO=$RUNTIME has no infra/docker-compose.yml" >&2; exit 1; }
case "$ROOT$RUNTIME" in *[[:space:]]*) echo "error: paths with spaces are not supported ($ROOT, $RUNTIME)" >&2; exit 1 ;; esac

# build context from stdin: just the Dockerfile, not services/dashboard/node_modules
docker build -q -t "$IMAGE" - < "$ROOT/services/dashboard/Dockerfile.dev" >/dev/null

mounts=(-v "$ROOT:$ROOT")
[ "$RUNTIME" = "$ROOT" ] || mounts+=(-v "$RUNTIME:$RUNTIME")

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --network host \
  --user "$(id -u):$(id -g)" --group-add "$(stat -c %g "$SOCK")" \
  -e HOME=/tmp -e npm_config_cache=/tmp/.npm -e VITE_CACHE_DIR=/tmp/vite-cache \
  -e VITE_DASHBOARD_SOURCE=live -e VITE_EVIDENCE_API_BASE=/evidence-api \
  -e EVIDENCE_API_TARGET="${EVIDENCE_API_TARGET:-http://localhost:8082}" -e ROM_RUNTIME_REPO="$RUNTIME" \
  "${mounts[@]}" -v "$SOCK:$SOCK" -w "$ROOT/services/dashboard" \
  "$IMAGE" sh -lc "[ -d node_modules ] || npm ci; exec npm run dev -- --host 0.0.0.0 --port $PORT --strictPort" >/dev/null

echo "starting $NAME (the first start runs npm ci) ..."
for _ in $(seq 90); do
  curl -sf "http://localhost:$PORT/api/scenarios" >/dev/null 2>&1 && break
  docker ps --format '{{.Names}}' | grep -qx "$NAME" || { docker logs --tail 20 "$NAME" >&2 || true; echo "error: the dashboard container stopped (log above)" >&2; exit 1; }
  sleep 2
done
curl -sf "http://localhost:$PORT/api/scenarios" >/dev/null || { docker logs --tail 20 "$NAME" >&2; echo "error: the dashboard did not come up" >&2; exit 1; }
echo "Live Monitoring  http://localhost:$PORT/#/live"
echo "Safety Evidence  http://localhost:$PORT/#/evidence"
echo "stop: make dashboard-stop   logs: scripts/dashboard-dev.sh logs"
