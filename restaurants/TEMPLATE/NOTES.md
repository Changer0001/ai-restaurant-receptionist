# REPLACE-THIS — Restaurant Name

Where this content came from, and what still needs checking. Keep it
updated: six months from now, "is this price still right?" is
unanswerable without knowing where it came from.

## Source

REPLACE THIS. Their website? Their printed menu? A phone call with the
owner? Say which, and give the date.

## Prices

REPLACE THIS. State whether these are the restaurant's own prices or a
delivery platform's — the two genuinely disagree, because the platforms
mark up to cover commission, and a phone caller is asking about dining
in or pickup, so the restaurant's own price is the correct one.

List any dish where you could not verify a price and therefore left it
out. Omitting a price is handled properly by the assistant; guessing one
is not.

## Still unverified

REPLACE THIS — and until the owner has confirmed the content, say so
here plainly. A published menu can be months out of date.

## What is deliberately NOT here

**Hours.** They come from the `RestaurantHours` table and are answered
deterministically (`backend/app/conversation/hours_answer.py`). A second
copy here would be a competing source of truth that goes stale — and
hours are the most-asked question, so a stale copy would be the
most-heard wrong answer.

Holiday hours DO belong here if they have them: that's the one hours
case the structured table can't express.
