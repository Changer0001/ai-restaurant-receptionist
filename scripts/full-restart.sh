#!/usr/bin/env bash
#
# One-command full restart for local voice-call testing after a
# reboot: Docker infra, native-Ollama check, an ngrok tunnel, and
# automatic updates to both backend/.env AND Twilio's phone number
# webhook to match ngrok's new URL — then starts the backend.
#
# This replaces running dev-up.sh and start-ngrok.sh separately AND
# manually copying the ngrok URL into two places every time it
# changes. Use dev-up.sh/start-ngrok.sh instead if you'd rather do
# those steps by hand (e.g. testing against a fixed/paid ngrok domain
# that never changes).
#
# Usage:
#   ./scripts/full-restart.sh                  # uses your saved number
#   ./scripts/full-restart.sh +16195551234     # sets/updates the number
#
# The Twilio number is asked for once and cached in .twilio-test-number
# (gitignored — it's local machine state, not project config) so you
# don't have to retype it every run.
#
# Ctrl+C stops uvicorn AND the ngrok tunnel this script started.
# Docker containers are left running (they're persistent services);
# run `docker compose down` separately if you want to stop those too.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
ENV_FILE="$PROJECT_ROOT/backend/.env"
NUMBER_CACHE="$PROJECT_ROOT/.twilio-test-number"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found. Copy backend/.env.example to backend/.env and fill it in first." >&2
  exit 1
fi

# --- Docker infra + native Ollama check ---------------------------------
echo "==> Starting Docker infrastructure (postgres, redis, chromadb)..."
docker compose up -d postgres redis chromadb

echo "==> Checking native Ollama (not Docker's) is reachable on localhost:11434..."
if ! curl -sS --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "ERROR: Ollama isn't reachable on localhost:11434. Start it first (e.g. 'ollama serve')." >&2
  exit 1
fi

echo "==> Waiting for Docker services to report healthy (up to 60s each)..."
for container in restaurant_ai_postgres restaurant_ai_redis restaurant_ai_chromadb; do
  status="unknown"
  for _ in $(seq 1 30); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$container" 2>/dev/null || echo "unknown")"
    [ "$status" = "healthy" ] && break
    sleep 2
  done
  echo "    ${container#restaurant_ai_}: $status"
done

# --- ngrok tunnel ---------------------------------------------------------
echo "==> Starting ngrok tunnel on port 8010..."
ngrok http 8010 --log=stdout > /tmp/ngrok.log 2>&1 &
NGROK_PID=$!

cleanup() {
  echo ""
  echo "==> Stopping ngrok (pid $NGROK_PID)..."
  kill "$NGROK_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "==> Waiting for ngrok's public URL..."
NGROK_URL=""
for _ in $(seq 1 30); do
  # `|| true` matters here under `set -e -o pipefail`: grep exits 1 on
  # no match (expected on early loop iterations before ngrok's local
  # API has anything to report), and without it that failure would
  # abort the whole script instead of just this iteration — hit live.
  NGROK_URL="$(curl -sS http://127.0.0.1:4040/api/tunnels 2>/dev/null \
    | grep -o '"public_url":"https://[^"]*"' | head -1 | sed 's/"public_url":"//;s/"$//' || true)"
  [ -n "$NGROK_URL" ] && break
  sleep 1
done

if [ -z "$NGROK_URL" ]; then
  echo "ERROR: ngrok didn't report a URL after 30s. Check /tmp/ngrok.log" >&2
  exit 1
fi

NGROK_HOST="${NGROK_URL#https://}"
echo "    ngrok URL: $NGROK_URL"

# --- Update backend/.env --------------------------------------------------
echo "==> Updating backend/.env with the new ngrok URL..."
sed_inplace() {
  # GNU sed (Linux) takes -i 'script'; BSD/macOS sed needs -i '' 'script'.
  if sed --version >/dev/null 2>&1; then
    sed -i "$1" "$2"
  else
    sed -i '' "$1" "$2"
  fi
}
sed_inplace "s#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=$NGROK_URL#" "$ENV_FILE"
sed_inplace "s#^PUBLIC_DOMAIN=.*#PUBLIC_DOMAIN=$NGROK_HOST#" "$ENV_FILE"

# --- Update Twilio's voice webhook via the API ----------------------------
echo "==> Updating Twilio's voice webhook..."
TWILIO_ACCOUNT_SID="$(grep -E '^TWILIO_ACCOUNT_SID=' "$ENV_FILE" | cut -d= -f2-)"
TWILIO_AUTH_TOKEN="$(grep -E '^TWILIO_AUTH_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
VOICE_WEBHOOK_URL="$NGROK_URL/webhooks/twilio/voice"

if [ -z "$TWILIO_ACCOUNT_SID" ] || [ -z "$TWILIO_AUTH_TOKEN" ]; then
  echo "    Skipped: TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN not set in backend/.env."
  echo "    Paste this into Twilio Console -> Phone Numbers -> your number -> Voice Configuration manually:"
  echo "    $VOICE_WEBHOOK_URL"
else
  if [ -n "${1:-}" ]; then
    TWILIO_NUMBER="$1"
    echo "$TWILIO_NUMBER" > "$NUMBER_CACHE"
  elif [ -f "$NUMBER_CACHE" ]; then
    TWILIO_NUMBER="$(cat "$NUMBER_CACHE")"
    echo "    Using saved Twilio number: $TWILIO_NUMBER (pass a different number as an argument to change it)"
  else
    read -rp "    Enter your Twilio phone number in E.164 format (e.g. +16195551234): " TWILIO_NUMBER
    echo "$TWILIO_NUMBER" > "$NUMBER_CACHE"
  fi

  # Captured separately from the grep/sed pipeline (rather than piped
  # straight in) for two reasons: so the raw response is available to
  # print if the lookup fails, and so a no-match grep (exit 1) can't
  # abort the whole script under `set -e -o pipefail` — hit live,
  # silently killing this script (including its EXIT trap tearing down
  # ngrok) right after printing the cached phone number, before ever
  # reaching the "Could not find" fallback below or starting uvicorn.
  PHONE_LOOKUP_RESPONSE="$(curl -sS -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
    "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/IncomingPhoneNumbers.json?PhoneNumber=$TWILIO_NUMBER")"
  PHONE_SID="$(echo "$PHONE_LOOKUP_RESPONSE" | grep -o '"sid":"[^"]*"' | head -1 | sed 's/"sid":"//;s/"$//' || true)"

  if [ -z "$PHONE_SID" ]; then
    echo "    Could not find $TWILIO_NUMBER on this Twilio account — update the webhook manually:"
    echo "    $VOICE_WEBHOOK_URL"
    echo "    Twilio's lookup response was: $PHONE_LOOKUP_RESPONSE"
  else
    curl -sS -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" -X POST \
      "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/IncomingPhoneNumbers/$PHONE_SID.json" \
      --data-urlencode "VoiceUrl=$VOICE_WEBHOOK_URL" \
      --data-urlencode "VoiceMethod=POST" >/dev/null
    echo "    Twilio voice webhook updated automatically: $VOICE_WEBHOOK_URL"
  fi
fi

# --- Start the backend -----------------------------------------------------
echo "==> Starting the backend (uvicorn on port 8010)..."
cd "$PROJECT_ROOT/backend"
# shellcheck disable=SC1091
source venv/bin/activate
uvicorn app.main:app --port 8010 --proxy-headers --forwarded-allow-ips='*'
