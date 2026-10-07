# Made with Claude (Claude Code, Anthropic)
# Evidence Collector: records the RoM uProtocol topics, judges every fault campaign run, serves the evidence.
# Self-contained: no bind mounts, configured only via env, logs JSON lines to stdout. Records live in /data
# (mount a volume there so evidence survives restarts).
# Build from the repo root:  docker build -f services/evidence-collector/Dockerfile -t localhost/rom/evidence-collector:dev .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EVIDENCE_DATA_DIR=/data EVIDENCE_HTTP_HOST=0.0.0.0 EVIDENCE_HTTP_PORT=8082

WORKDIR /src
COPY libs/rom-common libs/rom-common
COPY libs/rom-uprotocol libs/rom-uprotocol
COPY services/evidence-collector services/evidence-collector
RUN pip install ./libs/rom-common ./libs/rom-uprotocol ./services/evidence-collector \
 && pip install --no-deps up-python==0.2.0.dev0 \
 && rm -rf /src

RUN useradd --system --no-create-home rom && mkdir /data && chown rom /data
USER rom
WORKDIR /
VOLUME /data
EXPOSE 8082
CMD ["rom-evidence-collector"]
