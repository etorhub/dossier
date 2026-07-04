#!/usr/bin/env bash
# Run the off-host LLM pipeline stages (embed+cluster → rewrite → highlight)
# against the NAS's production Postgres from any machine with `cloudflared` and
# `docker` installed (local machine, an ad-hoc box, a VPS). The NAS worker runs
# "light" (fetch/enrich/availability only); this script produces the digest.
# See docs/REMOTE_REWRITE.md for one-time setup (Cloudflare Access service token,
# dossier_pipeline role password). For the primary Modal runner, see deploy/modal/.
#
# Required env vars:
#   CF_DB_HOSTNAME              e.g. db.yourdomain.com (the Tunnel's TCP ingress hostname)
#   CF_ACCESS_CLIENT_ID         Cloudflare Access service token ID
#   CF_ACCESS_CLIENT_SECRET     Cloudflare Access service token secret
#   DOSSIER_PIPELINE_PASSWORD   password for the dossier_pipeline Postgres role
# Optional env vars:
#   OLLAMA_HOST                 default: http://host.docker.internal:11434
#   DOSSIER_TAG                 default: latest
#
# Note: --network host is Linux-only. On Docker Desktop (macOS/Windows),
# drop --network host and use OLLAMA_HOST=http://host.docker.internal:11434
# with -p enabled instead, since host networking isn't available there.

set -euo pipefail

: "${CF_DB_HOSTNAME:?set CF_DB_HOSTNAME}"
: "${CF_ACCESS_CLIENT_ID:?set CF_ACCESS_CLIENT_ID}"
: "${CF_ACCESS_CLIENT_SECRET:?set CF_ACCESS_CLIENT_SECRET}"
: "${DOSSIER_PIPELINE_PASSWORD:?set DOSSIER_PIPELINE_PASSWORD}"

cloudflared access tcp \
  --hostname "$CF_DB_HOSTNAME" \
  --url 127.0.0.1:5432 \
  --service-token-id "$CF_ACCESS_CLIENT_ID" \
  --service-token-secret "$CF_ACCESS_CLIENT_SECRET" &
TUNNEL_PID=$!
trap 'kill "$TUNNEL_PID" 2>/dev/null || true' EXIT

echo "Waiting for tunnel proxy on 127.0.0.1:5432..."
until pg_isready -h 127.0.0.1 -p 5432 -U dossier_pipeline >/dev/null 2>&1; do
  sleep 0.5
done

docker run --rm \
  -e DATABASE_URL="postgresql://dossier_pipeline:${DOSSIER_PIPELINE_PASSWORD}@127.0.0.1:5432/dossier" \
  -e OLLAMA_HOST="${OLLAMA_HOST:-http://host.docker.internal:11434}" \
  --network host \
  "ghcr.io/etorhub/dossier-worker:${DOSSIER_TAG:-latest}" \
  python -m app.worker_cli run-llm-stages
