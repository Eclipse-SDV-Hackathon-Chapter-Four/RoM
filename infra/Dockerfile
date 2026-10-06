# Made with Claude (Claude Code, Anthropic)
# Dev/test image: a virtualenv (/opt/venv, always active via PATH) with every RoM package installed
# editable, so the repo bind-mounted at /app is live code. Used for tests, the kuksa-client shell,
# the simulator and the adapter. Services that run under Ankaios have their own image (services/*/Dockerfile).
FROM python:3.12-slim

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN python -m venv $VIRTUAL_ENV
WORKDIR /app

COPY . .
RUN pip install --no-cache-dir -r requirements.txt
# up-python pins protobuf==4.24.2 but runs fine on the protobuf 7 kuksa-client needs -> no deps.
RUN pip install --no-cache-dir --no-deps up-python==0.2.0.dev0

CMD ["pytest", "-q"]
