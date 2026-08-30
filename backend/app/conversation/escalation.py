"""Escalation Detection"""

from app.conversation.state import ConversationContext
from app.conversation.text_utils import strip_thinking
from app.prompts import render_prompt
from app.providers.llm.base import LLMProvider


async def should_escalate(
    llm: LLMProvider, restaurant_name: str, context: ConversationContext, latest_message: str
) -> bool:
    """
    Ask whether this conversation needs a human, based on tone and
    history (frustration, a complaint, repeated misunderstanding) —
    distinct from the engine's own unclear_count-based escalation, which
    catches the case where classification itself keeps failing rather
    than the caller being upset.
    """
    prompt = render_prompt(
        "escalation.txt",
        restaurant_name=restaurant_name,
        conversation_history=context.history_text(),
        latest_message=latest_message,
    )
    raw = await llm.generate(prompt, temperature=0.0)
    return strip_thinking(raw).strip().upper().startswith("YES")
