# Mal Al Sham — The Taste of Damascus

Where this content came from, and what still needs checking. Keep this
file updated when the content changes: six months from now, "is this
price still right?" is unanswerable without knowing where it came from.

## Source

Hand-written from the restaurant's own website (malalsham.com) and its
published menu. **Not scraped**, and not taken from the delivery
aggregators.

## Prices

These are the restaurant's OWN published prices, not the delivery-app
ones. The two genuinely disagree — hummus is 8.99 on the restaurant's
menu and 9.99 on Uber Eats/Postmates, because the platforms mark prices
up to cover their commission. A caller on the phone is asking about
dining in or picking up, so the restaurant's own price is the correct
answer; quoting the marked-up one would be wrong in the direction the
caller complains about later.

Where only an aggregator price was available — falafel, foul, the salads
— **no price is stated at all**. Better the assistant says it doesn't
have that one than quote a confidently wrong number.

## Still unverified

**Nobody at the restaurant has confirmed any of this.** A published menu
can be months out of date, and the owner is the only authority on what
they charge today. Verify before real callers hear it.

## What is deliberately NOT here

**Hours.** They're answered deterministically from the `RestaurantHours`
table (see `backend/app/conversation/hours_answer.py`). A second,
hand-edited copy here would be a competing source of truth that goes
stale — and hours are the single most-asked question, so a stale copy
would be the most-heard wrong answer.

Holiday hours DO belong here if the restaurant has them: that's the one
hours case the structured table can't express.
