#!/usr/bin/env bash
#
# Seeds the AI's RAG knowledge base with real restaurant content via the
# actual /knowledge/upload API — not raw SQL, since this data needs to
# be chunked and embedded into the vector DB, which only the running app
# can do (see backend/app/services/knowledge_service.py).
#
# Usage:
#   ./scripts/seed-knowledge.sh                  # replaces previously seeded docs
#   KEEP_EXISTING=1 ./scripts/seed-knowledge.sh  # adds without deleting
#
# You'll be prompted for your dashboard login and restaurant ID.
# Email/password are sent only to your own local backend (API_BASE
# below) to get a login token — never anywhere else, never logged.
# Requires FEATURE_RAG on (the default) and the backend already
# running (e.g. via dev-up.sh / full-restart.sh).
#
# ---------------------------------------------------------------------
# Why the documents below are written as questions and answers
#
# RAG retrieval compares the embedding of what the *caller said* against
# the embedding of each stored chunk. A chunk that already contains the
# caller's question ("Where are you located?") sits much closer to that
# query than a chunk of prose that merely happens to contain the address.
# Measured on real calls against the earlier prose-style version of these
# documents, a correct location match scored only 0.485 — barely clear of
# the 0.43-0.48 that completely unrelated documents scored on the same
# query. Phrasing each fact as the question a caller actually asks is the
# cheapest retrieval improvement available here, so every document below
# leads with real caller phrasings, including the clumsy ones.
#
# Hours are deliberately NOT in here: they're answered deterministically
# from the RestaurantHours table (see backend/app/conversation/
# hours_answer.py), and a second, hand-edited copy of the hours in the
# knowledge base would be a competing source of truth that goes stale.
# Holiday hours DO belong here — that's the one hours case the structured
# table can't express.
#
# The content is for Mal Al Sham - The Taste of Damascus, compiled from
# the restaurant's public listings. VERIFY PRICES AND DETAILS WITH THE
# RESTAURANT before using this with real callers — third-party listings
# go stale, and a confidently wrong price is worse than no price at all.
# ---------------------------------------------------------------------

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

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cat > "$TMP_DIR/location.txt" << 'EOF'
Where are you located? What is your address? How do I get to you? Where are you? What part of town are you in? Can you tell me your location?

We're at 388 East Main Street, El Cajon, California, 92020.

We're on Main Street in El Cajon, in the Little Baghdad neighborhood in the heart of downtown El Cajon. We're easy to reach from Interstate 8 — take the Main Street exit and we're a short drive down.

Our phone number is 619-401-1055.
EOF

cat > "$TMP_DIR/parking.txt" << 'EOF'
Where do I park? Is there parking? Do you have a parking lot? Is parking free? Is it hard to find parking? Do you have valet?

Yes, there's parking. We have a small lot behind the restaurant, and there's street parking on Main Street and the side streets around us.

The lot behind us is on the small side, so at busy times — weekend evenings especially — you may need to wait for a space to open up, or park on the street nearby. Coming a few minutes early makes it easy.
EOF

cat > "$TMP_DIR/halal_and_dietary.txt" << 'EOF'
Is your food halal? Are you a halal restaurant? Is the meat halal? Do you serve pork? Do you serve alcohol? Do you have vegetarian food? Do you have vegan options? Is there anything gluten free? I have a food allergy.

Yes, everything we serve is one hundred percent halal. All of our meat is halal, and we don't serve pork or alcohol.

We have plenty for vegetarians: hummus, falafel, baba ghanoush, foul, fattoush and our other salads, and manakeesh with zaatar. Several of those are vegan as well — hummus, falafel, foul and the salads.

For allergies or strict gluten-free needs, our kitchen staff can go through the exact ingredients in any dish, so it's best to ask when you come in, or call and speak with the team.
EOF

cat > "$TMP_DIR/menu_overview.txt" << 'EOF'
What kind of food do you serve? What's on your menu? What do you recommend? What are you known for? What's popular? What kind of restaurant are you? Can you tell me about your menu?

We serve authentic Syrian and Mediterranean food — Damascus home cooking, made fresh here every day.

What we're known for is charcoal-grilled kebabs, shawarma carved fresh off the spit, hand-rolled kibbeh, and hummus we make daily. The mixed grill is the most popular thing on the menu, with the beef and chicken shawarma right behind it.

We serve breakfast, lunch and dinner, and we do desserts and Middle Eastern drinks as well.
EOF

cat > "$TMP_DIR/menu_grill_and_shawarma.txt" << 'EOF'
Do you have shawarma? What kind of shawarma do you have? Do you have kebabs? What grill dishes do you have? How much is the shawarma? What does a platter cost? How much are your plates?

Beef shawarma — marinated beef carved fresh off the rotisserie, served with tahina sauce — is about 18.99.

Chicken shawarma — marinated chicken off the spit with our garlic sauce — is about 16.99.

The mixed grill, with beef kebab, chicken kebab, beef tikka and chicken tikka, all charcoal grilled, is about 24.99. Fried kibbeh stuffed with spiced ground beef and walnuts is about 14.99. Shawarma fries, topped with beef or chicken shawarma with tahini and garlic paste, are about 14.99.

When a caller asks about a price, give the price and mention that prices can change, so the team can confirm the exact amount.
EOF

cat > "$TMP_DIR/menu_appetizers.txt" << 'EOF'
What appetizers do you have? Do you have hummus? Do you have falafel? What salads do you have? Do you have manakeesh? Do you serve breakfast? What are your starters?

We have hummus made fresh daily — chickpeas blended with tahina, lemon and olive oil. Falafel comes as a dish of twelve balls with tahina, tomatoes and chopped parsley, served with pickles and pita bread.

Our salads include fattoush: tomato, cucumber, red onion, lettuce and parsley with lemon juice, topped with baked pita chips and pomegranate molasses.

We also do baba ghanoush, baked eggplant mashed with tahina, yogurt, lemon and garlic; and foul, slow-boiled fava beans with tomato, parsley, lemon, garlic and olive oil.

Manakeesh, our fresh-baked flatbread with zaatar and olive oil, is a morning item — we serve it in the mornings only.
EOF

cat > "$TMP_DIR/ordering_and_catering.txt" << 'EOF'
Do you do takeout? Can I order for pickup? Do you deliver? Do you do delivery? Can I order online? Do you cater? Can you cater an event? Do you take large orders? Do you have a patio? Can I dine in?

Yes, we do takeout — call ahead and pick it up. Our number is 619-401-1055.

For delivery, we're on Grubhub, DoorDash and Uber Eats.

We also cater across San Diego County: basmati rice trays, mansaf, and family platters. For catering, please call at least a day ahead so we can prepare it properly.

For dining in, we have indoor seating and a patio.
EOF

cat > "$TMP_DIR/about.txt" << 'EOF'
How long have you been open? Who owns the restaurant? Are you family owned? Tell me about the restaurant. What's your story?

We're family owned. The Ahmed brothers opened us in 2018 as the first Syrian restaurant in El Cajon, cooking from generations-old Damascus family recipes.

Everything is made in house, fresh every day.
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

upload "$TMP_DIR/location.txt" "Location & Address" "policy"
upload "$TMP_DIR/parking.txt" "Parking" "policy"
upload "$TMP_DIR/halal_and_dietary.txt" "Halal, Vegetarian & Dietary Needs" "faq"
upload "$TMP_DIR/menu_overview.txt" "Menu Overview & Recommendations" "menu"
upload "$TMP_DIR/menu_grill_and_shawarma.txt" "Menu: Shawarma & Grill" "menu"
upload "$TMP_DIR/menu_appetizers.txt" "Menu: Appetizers, Salads & Breakfast" "menu"
upload "$TMP_DIR/ordering_and_catering.txt" "Takeout, Delivery & Catering" "faq"
upload "$TMP_DIR/about.txt" "About the Restaurant" "faq"

echo
echo "Done. List what's indexed with:"
echo "  curl -s -H \"Authorization: Bearer \$TOKEN\" $API_BASE/restaurants/$RESTAURANT_ID/knowledge"
