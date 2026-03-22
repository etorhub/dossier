# Multi-stage build for Dossier
# Targets: web (slim), worker (feed processing + ollama client)
# Build: docker build --target web .  or  docker build --target worker .

# --- Base: shared apt deps and layout ---
FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/app/
COPY ops/ /app/ops/
COPY config/ /app/config/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/
COPY templates/ /app/templates/
COPY translations/ /app/translations/

ENV PYTHONPATH=/app
ENV FLASK_APP=app:create_app

# --- Web target: slim image, no ML/LLM ---
FROM base AS web

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:application"]

# --- Worker target: feed processing, clustering, rewrite (ollama client; LLM runs in ollama container) ---
FROM base AS worker

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "-m", "app.scheduler"]
