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

  # The whole number list is fetched and matched locally, rather than
  # asking Twilio to filter with ?PhoneNumber=... — because a literal "+"
  # in a query string means a space, so an E.164 number sent that way
  # asks Twilio for " 18304536218" and matches nothing.
  #
  # Hit live, and it failed in the most misleading way available: the
  # script printed "Could not find +18304536218 on this Twilio account"
  # and then, one line later, listed that exact number as being on the
  # account. The webhook silently went un-updated, so the next call
  # reached the pre-reboot ngrok URL and Twilio played "an application
  # error has occurred" to the caller.
  #
  # Matching on digits also makes the cached number tolerant of how it
  # was typed. The suffix comparison is what lets a number written
  # without its country code — (830) 453-6218 — match the E.164
  # +18304536218 Twilio stores; ten digits minimum, so a short string
  # can't match several numbers at once.
  #
  # Captured into a variable rather than piped straight through so the
  # raw response is available if parsing fails, and so a no-match can't
  # abort the whole script under `set -e -o pipefail` — that aborted it
  # once before, taking the EXIT trap's ngrok teardown with it.
  NUMBERS_JSON="$(curl -sS -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
    "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/IncomingPhoneNumbers.json?PageSize=20")"

  PHONE_SID="$(python3 -c "
import json, re, sys

def matches(a, b):
    a, b = re.sub(r'\D', '', a), re.sub(r'\D', '', b)
    if not a or not b:
        return False
    if a == b:
        return True
    # One written without its country code. Ten digits minimum so a
    # short fragment can't match more than one of the account's numbers.
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return len(shorter) >= 10 and longer.endswith(shorter)

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for entry in data.get('incoming_phone_numbers', []):
    if matches(sys.argv[1], entry.get('phone_number', '')):
        print(entry['sid'])
        break
" "$TWILIO_NUMBER" <<< "$NUMBERS_JSON" || true)"

  if [ -z "$PHONE_SID" ]; then
    echo "    Could not find $TWILIO_NUMBER on this Twilio account."
    # Listing what IS on the account distinguishes "wrong number" from
    # "wrong account" in one line, and gives you the value to re-run
    # with: ./scripts/full-restart.sh +1XXXXXXXXXX
    ALL_NUMBERS="$(python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for entry in data.get('incoming_phone_numbers', []):
    print(entry.get('phone_number', ''))
" <<< "$NUMBERS_JSON" || true)"

    if [ -n "$ALL_NUMBERS" ]; then
      echo "    Numbers on this account:"
      echo "$ALL_NUMBERS" | sed 's/^/      /'
      echo "    Re-run with the right one to save it: ./scripts/full-restart.sh +1XXXXXXXXXX"
    else
      echo "    This account has no phone numbers on it at all — check"
      echo "    TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in backend/.env."
    fi

    echo ""
    echo "    Meanwhile, paste this into Twilio Console -> Phone Numbers ->"
    echo "    your number -> Voice Configuration -> 'A call comes in':"
    echo "    $VOICE_WEBHOOK_URL"
    WEBHOOK_OK=""
  else
    # The response is read back rather than discarded, and the URL Twilio
    # reports is compared with the one we sent. An unverified write here
    # is worse than no write: the app starts, everything looks healthy,
    # and the failure only shows up as Twilio reading "an application
    # error has occurred" to a real caller, with nothing in this log.
    UPDATE_RESPONSE="$(curl -sS -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" -X POST \
      "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/IncomingPhoneNumbers/$PHONE_SID.json" \
      --data-urlencode "VoiceUrl=$VOICE_WEBHOOK_URL" \
      --data-urlencode "VoiceMethod=POST")"

    STORED_URL="$(python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('voice_url') or '')
except Exception:
    print('')
" <<< "$UPDATE_RESPONSE" || true)"

    if [ "$STORED_URL" = "$VOICE_WEBHOOK_URL" ]; then
      echo "    Twilio voice webhook updated and verified: $VOICE_WEBHOOK_URL"
      WEBHOOK_OK=1
    else
      echo "    WARNING: Twilio accepted the update but reports a different URL."
      echo "      sent:     $VOICE_WEBHOOK_URL"
      echo "      reported: ${STORED_URL:-<none>}"
      WEBHOOK_OK=""
    fi
  fi
fi

# A running app with a stale webhook is the failure mode that wastes a
# real phone call to discover, so it gets said last — right above the
# uvicorn output, not scrolled off the top of a long startup log.
if [ -z "${WEBHOOK_OK:-}" ]; then
  echo ""
  echo "  ###################################################################"
  echo "  #  TWILIO IS NOT POINTED AT THIS TUNNEL.                          #"
  echo "  #  The app below will start and look healthy, but an incoming     #"
  echo "  #  call will hear \"an application error has occurred\".            #"
  echo "  #                                                                 #"
  echo "  #  Fix it in another terminal, without restarting:                #"
  echo "  #      ./scripts/set-twilio-webhook.sh                            #"
  echo "  ###################################################################"
  echo ""
fi

# --- Free port 8010 -------------------------------------------------------
# A uvicorn from an earlier run of this same script (e.g. a terminal
# that was closed instead of Ctrl+C'd, or a crash that skipped this
# script's own cleanup) can be left holding port 8010. Without this,
# the new uvicorn below fails immediately with "address already in
# use" — hit live: the script printed "Starting the backend" and then
# died right after, with no indication a leftover process was the
# cause. 8010 is a dev-only port this project deliberately chose to
# avoid conflicting with anything else on the machine, so anything
# bound to it here is assumed to be our own stale process.
if command -v lsof >/dev/null 2>&1; then
  STALE_PIDS="$(lsof -ti tcp:8010 2>/dev/null || true)"
  if [ -n "$STALE_PIDS" ]; then
    echo "==> Killing stale process(es) on port 8010 from a previous run: $STALE_PIDS"
    kill $STALE_PIDS 2>/dev/null || true
    sleep 1
  fi
fi

# --- Start the backend -----------------------------------------------------
echo "==> Starting the backend (uvicorn on port 8010)..."
cd "$PROJECT_ROOT/backend"
# shellcheck disable=SC1091
source venv/bin/activate
uvicorn app.main:app --port 8010 --proxy-headers --forwarded-allow-ips='*'
