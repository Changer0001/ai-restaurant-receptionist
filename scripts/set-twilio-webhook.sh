#!/usr/bin/env bash
#
# Points your Twilio number's voice webhook at whatever ngrok URL is
# running right now, without touching the Twilio Console.
#
# Usage:
#   ./scripts/set-twilio-webhook.sh                # auto: one number on the account
#   ./scripts/set-twilio-webhook.sh +16195551234   # pick a specific number
#
# full-restart.sh already does this as part of a normal start. This
# exists for when that step fails or gets skipped — a console that keeps
# bouncing back to the dashboard (a region or subaccount mismatch will
# do it), an ngrok tunnel restarted on its own, or simply not being sure
# whether the URL in Twilio is still the live one.
#
# Reads credentials from backend/.env and the live URL from ngrok's own
# local API, so there is nothing to copy by hand and no way to paste a
# URL that has already expired.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/backend/.env"
NUMBER_CACHE="$PROJECT_ROOT/.twilio-test-number"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found." >&2
  exit 1
fi

TWILIO_ACCOUNT_SID="$(grep -E '^TWILIO_ACCOUNT_SID=' "$ENV_FILE" | cut -d= -f2- || true)"
TWILIO_AUTH_TOKEN="$(grep -E '^TWILIO_AUTH_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)"

if [ -z "$TWILIO_ACCOUNT_SID" ] || [ -z "$TWILIO_AUTH_TOKEN" ]; then
  echo "ERROR: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set in $ENV_FILE." >&2
  exit 1
fi

API="https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID"

# --- Which account are these credentials actually for? --------------------
# Worth printing every time: a console that keeps redirecting, and an API
# that can't find your number, are both explained instantly if the
# credentials belong to a different account than the one you're looking
# at in the browser.
ACCOUNT_NAME="$(curl -sS -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" "$API.json" \
  | grep -o '"friendly_name": *"[^"]*"' | head -1 | sed 's/.*: *"//;s/"$//' || true)"

if [ -z "$ACCOUNT_NAME" ]; then
  echo "ERROR: Twilio rejected these credentials. Check TWILIO_ACCOUNT_SID and" >&2
  echo "TWILIO_AUTH_TOKEN in $ENV_FILE against https://console.twilio.com/" >&2
  exit 1
fi
echo "==> Twilio account: $ACCOUNT_NAME ($TWILIO_ACCOUNT_SID)"

# --- The URL ngrok is serving right now -----------------------------------
NGROK_URL="$(curl -sS http://127.0.0.1:4040/api/tunnels 2>/dev/null \
  | grep -o '"public_url":"https://[^"]*"' | head -1 | sed 's/"public_url":"//;s/"$//' || true)"

if [ -z "$NGROK_URL" ]; then
  echo "ERROR: ngrok isn't running (nothing on its API at 127.0.0.1:4040)." >&2
  echo "Start the stack first: ./scripts/full-restart.sh" >&2
  exit 1
fi

VOICE_WEBHOOK_URL="$NGROK_URL/webhooks/twilio/voice"
echo "==> Live ngrok URL: $NGROK_URL"

# --- Which number ---------------------------------------------------------
NUMBERS_JSON="$(curl -sS -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  "$API/IncomingPhoneNumbers.json?PageSize=20")"

# Paired sid/number lines, so the SID is taken from the same entry as the
# number it belongs to rather than by position.
ENTRIES="$(python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for n in data.get('incoming_phone_numbers', []):
    print(f\"{n['sid']} {n['phone_number']}\")
" <<< "$NUMBERS_JSON" || true)"

if [ -z "$ENTRIES" ]; then
  echo "ERROR: This account has no phone numbers on it." >&2
  echo "The number you're testing with is on a different Twilio account or" >&2
  echo "subaccount than these credentials — which is also why the console" >&2
  echo "keeps sending you back to the dashboard." >&2
  exit 1
fi

WANTED="${1:-}"
if [ -z "$WANTED" ] && [ -f "$NUMBER_CACHE" ]; then
  WANTED="$(cat "$NUMBER_CACHE")"
fi

if [ -n "$WANTED" ]; then
  MATCH="$(echo "$ENTRIES" | grep -F " $WANTED" || true)"
  if [ -z "$MATCH" ]; then
    echo "ERROR: $WANTED is not on this account. It has:" >&2
    echo "$ENTRIES" | awk '{print "      " $2}' >&2
    echo "Re-run with one of those: ./scripts/set-twilio-webhook.sh +1XXXXXXXXXX" >&2
    exit 1
  fi
elif [ "$(echo "$ENTRIES" | wc -l)" -eq 1 ]; then
  MATCH="$ENTRIES"
else
  echo "This account has several numbers — say which one:" >&2
  echo "$ENTRIES" | awk '{print "      " $2}' >&2
  echo "  ./scripts/set-twilio-webhook.sh +1XXXXXXXXXX" >&2
  exit 1
fi

PHONE_SID="$(echo "$MATCH" | awk '{print $1}')"
PHONE_NUMBER="$(echo "$MATCH" | awk '{print $2}')"

# --- Set it ---------------------------------------------------------------
echo "==> Pointing $PHONE_NUMBER at $VOICE_WEBHOOK_URL"
curl -sS -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" -X POST \
  "$API/IncomingPhoneNumbers/$PHONE_SID.json" \
  --data-urlencode "VoiceUrl=$VOICE_WEBHOOK_URL" \
  --data-urlencode "VoiceMethod=POST" >/dev/null

# --- Read it back ---------------------------------------------------------
# Confirming from Twilio's own record rather than trusting the POST: the
# whole point of this script is knowing, not assuming.
LIVE_URL="$(curl -sS -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  "$API/IncomingPhoneNumbers/$PHONE_SID.json" \
  | grep -o '"voice_url": *"[^"]*"' | head -1 | sed 's/.*: *"//;s/"$//' || true)"

if [ "$LIVE_URL" = "$VOICE_WEBHOOK_URL" ]; then
  echo "$PHONE_NUMBER" > "$NUMBER_CACHE"
  echo "==> Confirmed. Twilio now has: $LIVE_URL"
  echo "    Call $PHONE_NUMBER to test."
else
  echo "ERROR: Twilio still reports: ${LIVE_URL:-(nothing)}" >&2
  echo "The update didn't take — check the credentials have write access." >&2
  exit 1
fi
