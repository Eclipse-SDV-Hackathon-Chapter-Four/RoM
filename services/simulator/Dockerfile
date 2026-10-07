# Made with Claude (Claude Code, Anthropic)
# Simulator: 4 battery cells into KUKSA + HTTP fault API + cooling actuator (env: KUKSA_*, SIM_*, UP_*, ZENOH_*).
# Self-contained: no bind mounts, configured only via env, logs JSON lines to stdout.
# Build from the repo root:  docker build -f services/simulator/Dockerfile -t localhost/rom/simulator:dev .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY libs/rom-common libs/rom-common
COPY libs/rom-uprotocol libs/rom-uprotocol
COPY services/simulator services/simulator
RUN pip install "./libs/rom-common[kuksa]" ./libs/rom-uprotocol ./services/simulator \
 && pip install --no-deps up-python==0.2.0.dev0 \
 && rm -rf /src

RUN useradd --system --no-create-home rom
USER rom
WORKDIR /
CMD ["rom-simulator"]
