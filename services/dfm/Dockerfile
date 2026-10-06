# Made with Claude (Claude Code, Anthropic)
# Diagnostic Fault Manager — TODO placeholder, see services/dfm/README.md.
# Self-contained: no bind mounts, configured only via env, logs JSON lines to stdout.
# Build from the repo root:  docker build -f services/dfm/Dockerfile -t localhost/rom/dfm:dev .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY libs/rom-common libs/rom-common
COPY services/dfm services/dfm
RUN pip install ./libs/rom-common ./services/dfm \
 && rm -rf /src

RUN useradd --system --no-create-home rom
USER rom
WORKDIR /
CMD ["rom-dfm"]
