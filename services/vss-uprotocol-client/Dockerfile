# Made with Claude (Claude Code, Anthropic)
# VSS uProtocol Client: KUKSA Databroker -> uProtocol (env: KUKSA_HOST/PORT, VSS_SOURCE_PATH, UP_*, ZENOH_*).
# Self-contained: no bind mounts, configured only via env, logs JSON lines to stdout.
# Build from the repo root:  docker build -f services/vss-uprotocol-client/Dockerfile -t localhost/rom/vss-uprotocol-client:dev .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY libs/rom-common libs/rom-common
COPY libs/rom-uprotocol libs/rom-uprotocol
COPY services/vss-uprotocol-client services/vss-uprotocol-client
RUN pip install ./libs/rom-common ./libs/rom-uprotocol ./services/vss-uprotocol-client \
 && pip install --no-deps up-python==0.2.0.dev0 \
 && rm -rf /src

RUN useradd --system --no-create-home rom
USER rom
WORKDIR /
CMD ["vss-uprotocol-client"]
