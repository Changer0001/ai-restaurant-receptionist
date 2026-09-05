"""
Reading a yes or a no.

Two branches in the engine turn on this — booking a reservation and
transferring a call — and both do something the caller cannot undo from
a phone. A misread "no" costs a turn; a misread "yes" creates a booking
they never agreed to, or hands their call to a person they wanted to
keep talking past.

WHY THIS ISN'T JUST A WORD LIST

It was, and every bug in this area was the same bug: the list was
incomplete or matched too loosely. "no" inside "not" read a complaint as
a refusal. "please" inside "no, please don't" read a refusal as
agreement. "cancel" inside "cancellation" threw away a booking. Each got
patched, and the next phrasing found the next gap — because the set of
ways a person says yes on the phone has no edge to reach: "go on then",
"that works", "nah", "if you would", "I'd rather not", "hold off".

So the list is kept for what it is genuinely good at — the overwhelmingly
common, unambiguous replies — and everything it doesn't recognize goes to
the classifier model, which is what natural language understanding is
for. The engine still decides what to DO; the model only reports what was
said.

WHY IT DOESN'T COST LATENCY

The fast path answers "yes", "yeah", "no thanks", "yes please", "go
ahead" without a network call, which is most replies to a yes/no
question. The model is consulted only for a short reply that matches
nothing — a case that today produces "Sorry, shall I go ahead?" and
costs the caller a whole turn anyway. Trading that wasted turn for one
small-model call is faster in wall-clock terms, not slower.

The failure direction is fixed: anything unparseable, and any error at
all, reads as UNCLEAR. The engine asks again. Nothing is ever booked or
transferred because a classification failed.
"""

import logging
from typing import Literal, Optional

from app.conversation.text_utils import strip_thinking
from app.prompts import render_prompt
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

Reading = Literal["confirm", "deny"]

_LABELS: dict[str, Reading] = {"YES": "confirm", "NO": "deny"}


async def read_confirmation(
    llm: LLMProvider, question: str, latest_message: str
) -> Optional[Reading]:
    """
    Whether a reply to a yes/no question agreed, declined, or neither.

    Returns "confirm", "deny", or None. None means "could not tell" and
    is the safe answer — the caller gets asked again.

    `question` is what the assistant actually asked, because the same
    words answer differently depending on it: "no problem" is agreement
    to "shall I book that?" and something else entirely elsewhere.
    """
    try:
        prompt = render_prompt(
            "confirmation_classification.txt",
            question=question,
            latest_message=latest_message,
        )
        raw = await llm.generate(prompt, temperature=0.0)
    except Exception as exc:
        # A classifier that is down must not be able to book a table.
        logger.warning(f"Confirmation classification failed, treating as unclear: {exc}")
        return None

    cleaned = strip_thinking(raw)
    if not cleaned:
        return None

    label = cleaned.split()[0].strip(".,!?:;\"'").upper()
    return _LABELS.get(label)
