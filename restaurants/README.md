# Restaurant content

One directory per client. Everything in here is **data** — what a
particular restaurant tells its callers. Nothing in here is code, and
nothing in `backend/` or `frontend/` needs to change to add a business.

```
restaurants/
  TEMPLATE/          copy this to start a new one
  mal-al-sham/
    manifest.tsv     filename -> document type -> title
    vocabulary.txt   dish names for speech recognition
    NOTES.md         where the content came from, what's unverified
    documents/*.txt  the knowledge base itself
```

## Adding a business

```bash
cp -r restaurants/TEMPLATE restaurants/their-name
# edit the text files
./scripts/seed-knowledge.sh restaurants/their-name
```

The script has no restaurant content in it. It reads the manifest,
uploads each document through the real API so it gets chunked and
embedded, sets the vocabulary, and reads the vocabulary back to confirm
it actually stored.

Three other things a business needs, none of them code:

- **Its row** — name, address, timezone, transfer number. Dashboard →
  Profile, or the register flow.
- **Its hours** — Dashboard → Hours. These are answered from the
  `RestaurantHours` table, deterministically, not from RAG. Don't put
  hours in a document; a second copy just goes stale.
- **Its phone number** — a `RestaurantPhoneNumber` row mapping the
  Twilio number to the restaurant. That mapping is the whole basis of
  multi-tenancy for voice: an inbound call's "To" number is what decides
  whose receptionist answers.

## Write documents as questions, then answers

This is the single highest-value thing on this page, and it isn't
obvious.

Retrieval compares the embedding of **what the caller said** against the
embedding of each stored chunk. A chunk that already contains the
caller's question sits much closer to it than prose that merely happens
to contain the answer.

Measured on real calls against an earlier prose version of these same
documents: "where are you located?" matched the correct location
document at **0.485** — barely clear of the 0.43–0.48 that completely
unrelated documents scored on the same query. Rewritten to lead with the
questions callers actually ask, the same fact scored **0.75**.

So every document opens with a line of real caller phrasings, including
the clumsy ones ("what part of town are you in?", "how much are your
plates?"), and then answers them.

This is also why you can't just scrape a website into here. The About
page has the facts, but in the wrong shape, and it will retrieve badly.

## Rules that are not style preferences

**Facts only. Never instructions to the assistant.** Anything in a
document can be retrieved and read aloud verbatim. An earlier version
ended one with "say the team can give them the exact price" — that came
back as a retrieved chunk on a live call, one step from being spoken to
a caller. Guidance about how to answer belongs in `backend/app/prompts/`.

**No price you can't verify.** A dish listed without a price is handled
properly: the assistant gives what it has and offers to have someone
confirm the rest. A confidently wrong price is the kind of error a
customer argues about at the counter.

**Restaurant's own prices, not the delivery apps'.** They genuinely
differ — the platforms mark up to cover commission. A phone caller is
asking about dining in or pickup.

**No hours.** They come from `RestaurantHours` and are answered
deterministically. Holiday hours are the exception — that's the one case
the structured table can't express.

## Vocabulary

`vocabulary.txt` lists the words that restaurant's menu makes callers say
that aren't everyday English. It's fed to Whisper as a decoder hint. Real
calls produced "hollow options" for "halal options" and "chicken show,
Emma" for "chicken shawarma" before it existed.

It is stored on the restaurant's own row, never globally, because it
would actively hurt a different restaurant: one cuisine's dish names bias
the recognizer toward "shawarma" when an Italian restaurant's caller said
"carbonara". Leaving the file empty is safe — it falls back to a
cuisine-neutral default.

## Can one restaurant's content reach another?

Not at retrieval. Search filters on `restaurant_id` in the vector store,
and `backend/tests/test_rag_search.py` asserts it: two restaurants are
seeded with deliberately similar documents and each search returns only
its own.

The way it *could* happen is a human pasting the wrong restaurant ID into
the seeding script. That's why the script resolves the ID to a **name**
and makes you confirm — "Load this content into "Mal Al Sham"? [y/N]" —
before it deletes or uploads anything.
