#!/usr/bin/env bash
#
# Seeds the AI's RAG knowledge base with real restaurant content
# (menu/dietary/halal info, location/parking) via the actual
# /knowledge/upload API — not raw SQL, since this data needs to be
# chunked and embedded into the vector DB, which only the running app
# can do (see backend/app/services/knowledge_service.py).
#
# Usage:
#   ./scripts/seed-knowledge.sh
#
# You'll be prompted for your dashboard login and restaurant ID.
# Email/password are sent only to your own local backend (API_BASE
# below) to get a login token — never anywhere else, never logged.
# Requires FEATURE_RAG on (the default) and the backend already
# running (e.g. via dev-up.sh / full-restart.sh).
#
# The two documents below are written for Mal Al Sham - The Taste of
# Damascus specifically — edit their content in this script for a
# different restaurant, or adapt the `upload` calls at the bottom to
# add more documents (parking, holiday hours, allergy info, etc.).

set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8010/api}"

read -rp "Dashboard email: " EMAIL
read -rsp "Dashboard password: " PASSWORD
echo
read -rp "Restaurant ID (from the dashboard URL): " RESTAURANT_ID

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

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cat > "$TMP_DIR/menu_and_dietary.txt" << 'EOF'
Mal Al Sham - The Taste of Damascus serves authentic Syrian and Mediterranean cuisine.

Every dish on the menu is halal.

Popular dishes include: beef and chicken shawarma, kibbeh (hand-rolled), a mixed grill platter, fresh hummus, and manakeesh (a Middle Eastern flatbread, often served in the morning).

Vegetarian and vegan options are available, including hummus, falafel, and a variety of salads.

If a caller asks about specific dietary needs beyond what's covered here (allergies, gluten-free, etc.), let them know restaurant staff can give exact ingredient details.
EOF

cat > "$TMP_DIR/location_and_parking.txt" << 'EOF'
Mal Al Sham - The Taste of Damascus is located at 388 E Main St, El Cajon, CA 92020, on Main Street in El Cajon's Little Baghdad neighborhood.

Parking: both street parking and a nearby lot are available. Street parking can be limited during busy times (weekend evenings especially), so allowing a few extra minutes to park is a good idea.
EOF

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
    echo "    FAILED (HTTP $status): $body"
  fi
}

upload "$TMP_DIR/menu_and_dietary.txt" "Menu, Halal Status & Dietary Options" "menu"
upload "$TMP_DIR/location_and_parking.txt" "Location & Parking" "policy"

echo
echo "Done. List what's indexed with:"
echo "  curl -s -H \"Authorization: Bearer \$TOKEN\" $API_BASE/restaurants/$RESTAURANT_ID/knowledge"
