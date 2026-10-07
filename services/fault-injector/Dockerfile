# Made with Claude (Claude Code, Anthropic)
# Fault Campaign Runner: YAML campaigns over HTTP, see services/fault-injector/README.md.
# Self-contained: no bind mounts, configured only via env, logs JSON lines to stdout.
# Build from the repo root:  docker build -f services/fault-injector/Dockerfile -t localhost/rom/fault-injector:dev .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY libs/rom-common libs/rom-common
COPY services/fault-injector services/fault-injector
RUN pip install ./libs/rom-common ./services/fault-injector \
 && rm -rf /src

RUN useradd --system --no-create-home rom
USER rom
WORKDIR /
CMD ["rom-fault-injector", "list"]
