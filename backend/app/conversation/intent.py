"""Intent Classification"""

import logging

from app.conversation.state import ConversationContext
from app.conversation.text_utils import strip_thinking
from app.prompts import render_prompt
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

VALID_INTENTS = frozenset({"FAQ", "RESERVATION", "ORDER", "HUMAN", "UNCLEAR"})


async def classify_intent(
    llm: LLMProvider, restaurant_name: str, context: ConversationContext, latest_message: str
) -> str:
    """
    Classify the caller's latest message into one of VALID_INTENTS.

    Falls back to "UNCLEAR" on any parsing failure — an unrecognized or
    malformed response is treated the same as genuine caller ambiguity,
    which the engine already knows how to handle (ask for clarification,
    then escalate after repeated UNCLEAR turns), rather than as a
    separate error path.
    """
    prompt = render_prompt(
        "intent_classification.txt",
        restaurant_name=restaurant_name,
        conversation_history=context.history_text(),
        latest_message=latest_message,
    )
    raw = await llm.generate(prompt, temperature=0.0)
    cleaned = strip_thinking(raw)

    # TEMPORARY debug logging — remove once it's confirmed FAQ questions
    # (menu/parking/location) aren't being misclassified.
    logger.warning(f"DEBUG classify_intent: message={latest_message!r} raw_llm_output={raw!r}")

    if not cleaned:
        return "UNCLEAR"

    label = cleaned.split()[0].strip(".,!?:;\"'").upper()
    return label if label in VALID_INTENTS else "UNCLEAR"
