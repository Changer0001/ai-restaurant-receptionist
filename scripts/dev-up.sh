#!/usr/bin/env bash
#
# Bring up everything needed for local voice-call testing after a
# reboot: the Docker infrastructure this project actually needs, then
# the backend itself.
#
# Deliberately starts ONLY postgres/redis/chromadb/ollama — NOT the
# api/worker/frontend containers. Those get *rebuilt from source* on
# every `docker compose up -d` (no args), which is slow, and pulls a
# multi-GB dependency tree (torch, etc.) that can genuinely exhaust
# disk space on a real run — hit live during this project's own local
# voice-call testing. They're also not needed here: the backend runs
# directly from this repo's `backend/venv`, via uvicorn below, not
# through Docker.
#
# Usage:
#   ./scripts/dev-up.sh
#
# Ctrl+C stops uvicorn (this script's own process). The Docker
# containers keep running in the background afterward — that's
# expected, they're persistent services meant to stay up; run
# `docker compose down` separately if you actually want to stop them.
#
# ngrok is NOT started here — it needs its own terminal so you can see
# its printed URL. Run scripts/start-ngrok.sh in a second terminal.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "==> Starting Docker infrastructure (postgres, redis, chromadb, ollama)..."
docker compose up -d postgres redis chromadb ollama

echo "==> Waiting for services to report healthy (up to 60s each)..."
for container in restaurant_ai_postgres restaurant_ai_redis restaurant_ai_chromadb restaurant_ai_ollama; do
  status="unknown"
  for _ in $(seq 1 30); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$container" 2>/dev/null || echo "unknown")"
    if [ "$status" = "healthy" ]; then
      break
    fi
    sleep 2
  done
  service_name="${container#restaurant_ai_}"
  if [ "$status" = "healthy" ]; then
    echo "    $service_name: healthy"
  else
    echo "    $service_name: still '$status' after 60s — check 'docker compose logs $service_name'"
  fi
done

echo "==> Starting the backend (uvicorn on port 8010)..."
cd "$PROJECT_ROOT/backend"
# shellcheck disable=SC1091
source venv/bin/activate
exec uvicorn app.main:app --port 8010 --proxy-headers --forwarded-allow-ips='*'
