#!/usr/bin/env bash
#
# Seeds one restaurant's AI receptionist with its own content: the RAG
# knowledge base (via the actual /knowledge/upload API — not raw SQL,
# since this data has to be chunked and embedded into the vector DB,
# which only the running app can do; see backend/app/services/
# knowledge_service.py) and the speech-recognition vocabulary for its
# menu.
#
# ONBOARDING ANOTHER BUSINESS: copy this file, replace the documents and
# the STT_VOCABULARY list with theirs, and run it. Everything that varies
# between clients is data — this script, the RestaurantHours table, and
# the restaurant's own row. There is no per-client code.
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
# The content is for Mal Al Sham - The Taste of Damascus.
#
# Prices below are the restaurant's OWN published prices (malalsham.com),
# not the ones on the delivery aggregators. That distinction is the whole
# reason the two disagree: hummus is 8.99 on the restaurant's own menu
# and 9.99 on Uber Eats/Postmates, because delivery platforms mark prices
# up to cover their commission. A caller on the phone is asking about
# dining in or picking up, so the restaurant's own price is the correct
# answer, and quoting an aggregator's marked-up price would be wrong in
# the caller's favor to complain about later.
#
# Where only an aggregator price was available (falafel, foul, the
# salads), no price is stated at all — better the assistant says it
# doesn't have that one than quote a confidently wrong number.
#
# Documents contain FACTS ONLY, never instructions to the assistant.
# Anything written here can be retrieved and read aloud verbatim: an
# earlier version ended a document with "say the team can give them the
# exact price", and that line came back as a retrieved chunk on a live
# call, one step away from being spoken to a caller. Guidance about how
# to answer belongs in backend/app/prompts/, not in the knowledge base.
#
# STILL VERIFY WITH THE RESTAURANT before real callers hear any of this:
# a published menu can be months out of date, and the owner is the only
# authority on what they charge today.
# ---------------------------------------------------------------------

set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8010/api}"

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
  echo "    Using restaurant: $RESTAURANT_ID"
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
Do you have shawarma? What kind of shawarma do you have? Do you have kebabs? What grill dishes do you have? How much is the shawarma? What does a platter cost? How much are your plates? How much does that cost?

Beef shawarma — marinated beef carved fresh off the rotisserie, served with tahina sauce — is 18.99.

Chicken shawarma — marinated chicken off the spit with our garlic sauce — is 16.99.

The mixed grill, with beef kebab, chicken kebab, beef tikka and chicken tikka, all charcoal grilled, is 24.99.

Fried kibbeh stuffed with spiced ground beef and walnuts is 14.99.

Shawarma fries, topped with beef or chicken shawarma with tahini and garlic paste, are 14.99.

These are our prices for dining in and for pickup. Ordering through a delivery app costs more, because the apps set their own higher prices.
EOF

cat > "$TMP_DIR/menu_appetizers.txt" << 'EOF'
What appetizers do you have? Do you have hummus? How much is the hummus? Do you have falafel? What salads do you have? Do you have manakeesh? Do you serve breakfast? What are your starters?

We have hummus made fresh daily — chickpeas blended with tahina, lemon and olive oil — for 8.99.

Falafel comes as a dish of twelve balls with tahina, tomatoes and chopped parsley, served with pickles and pita bread.

Our salads include fattoush: tomato, cucumber, red onion, lettuce and parsley with lemon juice, topped with baked pita chips and pomegranate molasses.

We also do baba ghanoush, baked eggplant mashed with tahina, yogurt, lemon and garlic; and foul, slow-boiled fava beans with tomato, parsley, lemon, garlic and olive oil.

Manakeesh, our fresh-baked flatbread with zaatar and olive oil, is 8.99, and it's a morning item — we serve it in the mornings only.
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

# --- Speech-recognition vocabulary ----------------------------------------
# The words on this menu that aren't everyday English, handed to Whisper
# as a decoder hint so it spells them right. Stored per restaurant on
# purpose: one backend serves them all, and a list of Syrian dish names
# would bias the recognizer toward "shawarma" when a caller to an Italian
# restaurant said "carbonara". Onboarding a new business means rewriting
# the list below from ITS menu — there is no code change to make.
#
# Keep it a bare comma-separated term list, never a fluent sentence:
# Whisper continues sentences it is given, and an earlier prose version
# came back as a transcript of what the caller supposedly said.
STT_VOCABULARY="shawarma, beef shawarma, chicken shawarma, kebab, kabob, tikka, mixed grill, kibbeh, falafel, hummus, tahina, tabouli, fattoush, baba ghanoush, foul, manakeesh, zaatar, shish tawook, mansaf, baklava, halal, vegan, vegetarian, gluten free, takeout, delivery, catering, reservation, parking"

echo "==> Setting the speech-recognition vocabulary..."
VOCAB_RESPONSE="$(python3 -c "
import json, sys
print(json.dumps({'stt_vocabulary': sys.argv[1]}))
" "$STT_VOCABULARY" | curl -sS \
  -X PATCH "$API_BASE/restaurants/$RESTAURANT_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @-)"

# Checked by reading the value back out of the response, NOT by trusting
# the status code. A backend running code older than the stt_vocabulary
# field drops the unknown key and still answers 200 — so a status-only
# check reports success on a request that stored nothing, which is
# exactly the "it said OK but nothing happened" failure this script
# exists to avoid.
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
