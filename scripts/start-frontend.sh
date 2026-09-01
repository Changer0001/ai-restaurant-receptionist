#!/usr/bin/env bash
#
# Starts the frontend dev server pointed at the backend this project's
# other scripts actually run (port 8010 — see dev-up.sh/full-restart.sh),
# not Vite's own default of 8000.
#
# Why this matters: vite.config.ts's dev-server proxy for /api defaults
# to http://localhost:8000 (correct for the normal Docker workflow,
# where docker-compose's `api` container listens on 8000) — but this
# project's local, non-Docker backend runs on 8010 specifically to
# avoid a real port-8000 conflict on this machine. Without this
# override, every frontend API call (including login) silently goes to
# port 8000 instead — whatever else is listening there, if anything —
# and fails in confusing ways that look like a login/form bug but
# aren't. Hit live: a real login with correct credentials failing with
# "Field required" every time, because the request never reached this
# project's actual backend at all.
#
# Usage:
#   ./scripts/start-frontend.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT/frontend"

if [ ! -d node_modules ]; then
  echo "==> Installing frontend dependencies (first run)..."
  npm install
fi

echo "==> Starting frontend dev server on http://localhost:5173 (API proxied to localhost:8010)..."
export VITE_API_PROXY_TARGET="http://localhost:8010"
npm run dev
