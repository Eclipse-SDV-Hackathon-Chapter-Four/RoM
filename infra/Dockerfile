# Made with Claude (Claude Code, Anthropic)
# Python image with all RoM requirements; used for dev/test and as a base for service images later.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["pytest", "-q"]
