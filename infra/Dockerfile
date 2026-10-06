# Made with Claude (Claude Code, Anthropic)
# Python image with a virtualenv (/opt/venv, always active via PATH) holding all RoM requirements.
# Used for dev/test, the kuksa-client shell, and as a base for service images later.
FROM python:3.12-slim

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
RUN python -m venv $VIRTUAL_ENV
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# up-python pins protobuf==4.24.2 but runs fine on the protobuf 7 kuksa-client needs -> no deps.
RUN pip install --no-cache-dir --no-deps up-python==0.2.0.dev0

COPY . .
CMD ["pytest", "-q"]
