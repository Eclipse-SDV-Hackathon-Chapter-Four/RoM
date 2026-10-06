# Made with Claude (Claude Code, Anthropic)
# Battery Thermal Guardian, input over uProtocol only (env: WARN_C, CRIT_C, UP_*, ZENOH_*, MQTT_*).
# Self-contained: no bind mounts, configured only via env, logs JSON lines to stdout.
# Build from the repo root:  docker build -f services/guardian/Dockerfile -t localhost/rom/guardian:dev .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY libs/rom-common libs/rom-common
COPY libs/rom-uprotocol libs/rom-uprotocol
COPY services/guardian services/guardian
RUN pip install "./libs/rom-common[mqtt]" ./libs/rom-uprotocol ./services/guardian \
 && pip install --no-deps up-python==0.2.0.dev0 \
 && rm -rf /src

RUN useradd --system --no-create-home rom
USER rom
WORKDIR /
CMD ["rom-guardian", "--uprotocol"]
