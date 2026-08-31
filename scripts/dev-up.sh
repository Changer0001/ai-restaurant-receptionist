#!/usr/bin/env bash
#
# Bring up everything needed for local voice-call testing after a
# reboot: the Docker infrastructure this project actually needs, then
# the backend itself.
#
# Deliberately starts ONLY postgres/redis/chromadb — NOT ollama, and
# NOT the api/worker/frontend containers.
#
#   - The Docker `ollama` service requires an NVIDIA GPU reservation
#     (see its `deploy:` block in docker-compose.yml) and fails outright
#     on a CPU-only machine with "could not select device driver...
#     with capabilities: [[gpu]]" — hit live running this script. It's
#     also simply not used in this CPU-only setup: backend/.env points
#     OLLAMA_BASE_URL at a separately, natively-installed Ollama
#     (`ollama serve`, listening on localhost:11434), not this
#     container. Make sure that native Ollama is running before
#     starting this script — `ollama list` should work in another
#     terminal. (If you DO have a GPU and want the Dockerized ollama
#     instead, add `ollama` back to the `docker compose up -d` line
#     below and switch OLLAMA_BASE_URL to http://localhost:11434 to
#     match its published port — same value either way, so no .env
#     change is actually needed unless you remap its port.)
#   - api/worker/frontend get *rebuilt from source* on every
#     `docker compose up -d` (no args), which is slow and pulls a
#     multi-GB dependency tree (torch, etc.) that can genuinely exhaust
#     disk space on a real run — also hit live during this project's
#     own testing. They're unneeded here: the backend runs directly
#     from this repo's `backend/venv`, via uvicorn below, not Docker.
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

echo "==> Starting Docker infrastructure (postgres, redis, chromadb)..."
docker compose up -d postgres redis chromadb

echo "==> Checking native Ollama (not Docker's) is reachable on localhost:11434..."
if curl -sS --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "    ollama: reachable"
else
  echo "    ollama: NOT reachable — start it first (e.g. 'ollama serve', or open the Ollama app)"
fi

echo "==> Waiting for services to report healthy (up to 60s each)..."
for container in restaurant_ai_postgres restaurant_ai_redis restaurant_ai_chromadb; do
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
