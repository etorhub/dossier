#!/usr/bin/env bash
# Run Alembic migrations and seed minimal reader data against the Compose Postgres.
#
# Requires docker-compose.override.yml (or another bind mount) so /app/scripts exists
# inside the web image; the production Dockerfile web stage does not COPY scripts/.
#
# Environment: docker compose reads COMPOSE_FILE, COMPOSE_PROJECT_NAME, etc. from the
# environment. Seed-specific vars (DEV_EMAIL, DEV_PASSWORD) are passed through to the
# container when exported on the host before invoking this script.
#
# Usage:
#   ./scripts/seed_docker_db.sh
#   ./scripts/seed_docker_db.sh --skip-sources
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

extra=""
if [ "$#" -gt 0 ]; then
  extra=$(printf '%q ' "$@")
fi

exec docker compose run --rm web sh -c "alembic upgrade head && python scripts/seed_dev_data.py ${extra}"
