#!/usr/bin/env bash
#
# Loads one restaurant's own content into its AI receptionist: the RAG
# knowledge base and the speech-recognition vocabulary for its menu.
#
# Usage:
#   ./scripts/seed-knowledge.sh restaurants/mal-al-sham
#   KEEP_EXISTING=1 ./scripts/seed-knowledge.sh restaurants/some-place
#   ASSUME_YES=1    ./scripts/seed-knowledge.sh restaurants/some-place
#
# ONBOARDING A NEW BUSINESS:
#   cp -r restaurants/TEMPLATE restaurants/their-name
#   ...edit the text files...
#   ./scripts/seed-knowledge.sh restaurants/their-name
#
# There is NO restaurant content in this file, on purpose. Everything
# that varies between clients lives under restaurants/<name>/, so
# onboarding never means editing a script — and one restaurant's menu
# can't be shipped to another by someone who forgot to change a line
# here. See restaurants/README.md.
#
# Uploads go through the real /knowledge/upload API rather than raw SQL,
# because this data has to be chunked and embedded into the vector DB,
# which only the running app can do (backend/app/services/
# knowledge_service.py).
#
# You'll be prompted for your dashboard login. Email and password are
# sent only to your own backend (API_BASE below) to get a login token —
# never anywhere else, never logged. Requires FEATURE_RAG on (the
# default) and the backend already running (dev-up.sh / full-restart.sh).

set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8010/api}"

# --- Locate and validate the restaurant's content directory ---------------
RESTAURANT_DIR="${1:-}"
if [ -z "$RESTAURANT_DIR" ]; then
  echo "ERROR: which restaurant's content should be loaded?" >&2
  echo >&2
  echo "  ./scripts/seed-knowledge.sh <directory>" >&2
  echo >&2
  echo "Available:" >&2
  for dir in restaurants/*/; do
    name="$(basename "$dir")"
    [ "$name" = "TEMPLATE" ] && continue
    [ -f "$dir/manifest.tsv" ] && echo "  restaurants/$name" >&2
  done
  echo >&2
  echo "New business: cp -r restaurants/TEMPLATE restaurants/their-name" >&2
  exit 1
fi

RESTAURANT_DIR="${RESTAURANT_DIR%/}"
MANIFEST="$RESTAURANT_DIR/manifest.tsv"

if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: no manifest.tsv in $RESTAURANT_DIR" >&2
  echo "Expected $MANIFEST — see restaurants/TEMPLATE for the layout." >&2
  exit 1
fi

# Every document is checked to exist BEFORE anything is deleted or
# uploaded. A typo in the manifest must not leave the restaurant with
# half its old knowledge base wiped and half a new one loaded.
MISSING=""
while IFS=$'\t' read -r filename doc_type title; do
  case "$filename" in ''|'#'*) continue ;; esac
  [ -f "$RESTAURANT_DIR/documents/$filename" ] || MISSING="$MISSING  $filename"$'\n'
  if [ -z "$doc_type" ] || [ -z "$title" ]; then
    echo "ERROR: $MANIFEST line for '$filename' is missing a type or title." >&2
    echo "Fields must be separated by real TABs, not spaces." >&2
    exit 1
  fi
done < "$MANIFEST"

if [ -n "$MISSING" ]; then
  echo "ERROR: manifest.tsv lists documents that don't exist:" >&2
  printf '%s' "$MISSING" >&2
  echo "Nothing was changed." >&2
  exit 1
fi

# --- Log in ---------------------------------------------------------------
read -rp "Dashboard email: " EMAIL
read -rsp "Dashboard password: " PASSWORD
echo
# Looked up automatically below when left blank — most accounts have
# exactly one restaurant, and going to find the ID first was enough
# friction to have this step skipped repeatedly.
read -rp "Restaurant ID (press Enter to detect it automatically): " RESTAURANT_ID

echo "==> Logging in..."
LOGIN_RESPONSE="$(curl -sS -X POST "$API_BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$EMAIL\", \"password\": \"$PASSWORD\"}")"

ACCESS_TOKEN="$(python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])" <<< "$LOGIN_RESPONSE" 2>/dev/null || true)"

if [ -z "$ACCESS_TOKEN" ]; then
  echo "ERROR: Login failed. Response was:" >&2
  echo "$LOGIN_RESPONSE" >&2
  exit 1
fi
echo "    Logged in."

# --- Resolve the restaurant ID --------------------------------------------
if [ -z "$RESTAURANT_ID" ]; then
  echo "==> Looking up your restaurant..."
  RESTAURANTS="$(curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" "$API_BASE/restaurants")"
  # Only auto-select when there's exactly one: picking the first of
  # several on a platform-admin account would silently seed the wrong
  # restaurant's knowledge base.
  RESTAURANT_ID="$(python3 -c "
import json, sys
try:
    items = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if len(items) == 1:
    print(items[0]['id'])
else:
    for r in items:
        print(f\"    {r['id']}  {r.get('name', '')}\", file=sys.stderr)
" <<< "$RESTAURANTS" || true)"

  if [ -z "$RESTAURANT_ID" ]; then
    echo "ERROR: Could not pick a restaurant automatically." >&2
    echo "Re-run and paste one of the IDs listed above (if none are listed, the" >&2
    echo "login worked but the account has no restaurant yet). Raw response:" >&2
    echo "$RESTAURANTS" >&2
    exit 1
  fi
fi

# --- Confirm the target, by name ------------------------------------------
# The one failure this script can cause that a caller would hear is
# loading one restaurant's menu into another's knowledge base. Retrieval
# is tenant-filtered, so it can't leak on its own (see
# backend/tests/test_rag_search.py) — but nothing stops a human pasting
# the wrong ID, and a UUID is unreadable. So resolve it to a NAME and
# show it before touching anything.
RESTAURANT_NAME="$(curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" \
  "$API_BASE/restaurants/$RESTAURANT_ID" \
  | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('name') or '')
except Exception:
    print('')
" || true)"

if [ -z "$RESTAURANT_NAME" ]; then
  echo "ERROR: no restaurant $RESTAURANT_ID on this account." >&2
  exit 1
fi

DOC_COUNT="$(grep -cvE '^\s*(#|$)' "$MANIFEST" || true)"
echo
echo "    Content:    $RESTAURANT_DIR ($DOC_COUNT documents)"
echo "    Restaurant: $RESTAURANT_NAME"
echo "                $RESTAURANT_ID"
echo

if [ -z "${ASSUME_YES:-}" ]; then
  read -rp "Load this content into \"$RESTAURANT_NAME\"? [y/N] " CONFIRM
  case "$CONFIRM" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Cancelled. Nothing was changed."; exit 0 ;;
  esac
fi

# --- Clear previously seeded documents ------------------------------------
# Without this, every re-run stacks another near-identical copy of each
# document into the vector DB, and retrieval starts handing the LLM three
# copies of the same chunk instead of three different facts.
if [ -z "${KEEP_EXISTING:-}" ]; then
  echo "==> Removing previously indexed documents (set KEEP_EXISTING=1 to skip)..."
  EXISTING="$(curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" \
    "$API_BASE/restaurants/$RESTAURANT_ID/knowledge")"
  DOC_IDS="$(python3 -c "
import json, sys
try:
    print(' '.join(str(d['id']) for d in json.load(sys.stdin)))
except Exception:
    pass
" <<< "$EXISTING" || true)"
  for doc_id in $DOC_IDS; do
    curl -sS -X DELETE -H "Authorization: Bearer $ACCESS_TOKEN" \
      "$API_BASE/restaurants/$RESTAURANT_ID/knowledge/$doc_id" >/dev/null || true
    echo "    Deleted $doc_id"
  done
fi

# --- Speech-recognition vocabulary ----------------------------------------
VOCAB_FILE="$RESTAURANT_DIR/vocabulary.txt"
if [ -f "$VOCAB_FILE" ]; then
  # Comments stripped, remaining lines joined into one comma-separated
  # list — the file is formatted for a human to edit, the API wants a
  # single string.
  STT_VOCABULARY="$(python3 -c "
import sys
terms = []
for line in open(sys.argv[1], encoding='utf-8'):
    line = line.split('#')[0].strip().strip(',')
    if line:
        terms.append(line)
print(', '.join(terms))
" "$VOCAB_FILE")"
else
  STT_VOCABULARY=""
fi

if [ -n "$STT_VOCABULARY" ]; then
  echo "==> Setting the speech-recognition vocabulary..."
  VOCAB_RESPONSE="$(python3 -c "
import json, sys
print(json.dumps({'stt_vocabulary': sys.argv[1]}))
" "$STT_VOCABULARY" | curl -sS \
    -X PATCH "$API_BASE/restaurants/$RESTAURANT_ID" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    --data-binary @-)"

  # Checked by reading the value back out of the response, NOT by
  # trusting the status code. A backend running code older than the
  # stt_vocabulary field drops the unknown key and still answers 200 —
  # so a status-only check reports success on a request that stored
  # nothing, which is exactly the "it said OK but nothing happened"
  # failure this script exists to avoid.
  VOCAB_STORED="$(python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('stt_vocabulary') or '')
except Exception:
    print('')
" <<< "$VOCAB_RESPONSE" || true)"

  if [ "$VOCAB_STORED" = "$STT_VOCABULARY" ]; then
    echo "    OK"
  else
    echo "    NOT SET. The documents below still upload, but speech recognition" >&2
    echo "    falls back to the generic default, so this menu's dish names will" >&2
    echo "    be transcribed worse. Two usual causes:" >&2
    echo "      1. The migration hasn't run:" >&2
    echo "           cd backend && source venv/bin/activate && alembic upgrade head" >&2
    echo "      2. The backend is still running pre-stt_vocabulary code — restart" >&2
    echo "         it after pulling, or it silently ignores the field." >&2
    echo "    Server said: $VOCAB_RESPONSE" >&2
  fi
fi

# --- Upload the documents -------------------------------------------------
FAILED=0

upload() {
  local file="$1" title="$2" doc_type="$3"
  echo "==> Uploading: $title"
  response="$(curl -sS -w $'\nHTTP_STATUS:%{http_code}' -X POST "$API_BASE/restaurants/$RESTAURANT_ID/knowledge/upload" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -F "file=@$file" \
    -F "title=$title" \
    -F "document_type=$doc_type")"
  status="$(echo "$response" | grep -o 'HTTP_STATUS:[0-9]*' | cut -d: -f2)"
  body="$(echo "$response" | sed 's/HTTP_STATUS:[0-9]*$//')"
  if [ "$status" = "201" ]; then
    echo "    OK"
  else
    echo "    FAILED (HTTP $status): $body" >&2
    FAILED=$((FAILED + 1))
  fi
}

while IFS=$'\t' read -r filename doc_type title; do
  case "$filename" in ''|'#'*) continue ;; esac
  upload "$RESTAURANT_DIR/documents/$filename" "$title" "$doc_type"
done < "$MANIFEST"

echo
if [ "$FAILED" -gt 0 ]; then
  echo "$FAILED document(s) failed to upload — see the errors above." >&2
  exit 1
fi

echo "Done — $RESTAURANT_NAME is loaded. List what's indexed with:"
echo "  curl -s -H \"Authorization: Bearer \$TOKEN\" $API_BASE/restaurants/$RESTAURANT_ID/knowledge"
