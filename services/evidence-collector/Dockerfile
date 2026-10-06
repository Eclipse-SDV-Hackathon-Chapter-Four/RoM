# Made with Claude (Claude Code, Anthropic)
# Evidence Collector — TODO placeholder, see services/evidence-collector/README.md.
# Self-contained: no bind mounts, configured only via env, logs JSON lines to stdout.
# Build from the repo root:  docker build -f services/evidence-collector/Dockerfile -t localhost/rom/evidence-collector:dev .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY libs/rom-common libs/rom-common
COPY services/evidence-collector services/evidence-collector
RUN pip install ./libs/rom-common ./services/evidence-collector \
 && rm -rf /src

RUN useradd --system --no-create-home rom
USER rom
WORKDIR /
CMD ["rom-evidence-collector"]
