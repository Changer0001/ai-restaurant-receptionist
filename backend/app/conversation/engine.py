"""
Conversation Engine

The state machine that drives one phone call from greeting to end. Text
in, text out — Phase 5 feeds it STT transcripts and speaks its responses
via TTS; nothing here knows about audio or Twilio.

Design decision: the LLM is never given free rein to decide *which* tool
to call via a self-emitted JSON directive. Instead, the state machine
itself — deterministic, testable Python — decides when a tool runs
(e.g. "we have every required reservation field, so call
create_reservation_request now"), and the LLM's role is narrowly
scoped to natural-language understanding (classify intent, extract
slots) and generation (phrase a grounded answer) within a state the
application already chose. This is a deliberate, more conservative
reading of the spec's "the LLM requests an action, the application
validates it, the application executes it" — a smaller local model on a
live phone call is a much less reliable free-form tool-caller than a
hosted frontier model, and a wrong state transition on a phone call
degrades the caller's experience directly. See docs/architecture.md.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation import hours_answer
from app.conversation.escalation import should_escalate
from app.conversation.intent import classify_intent
from app.conversation.rag_answer import generate_faq_answer
from app.conversation.reservation_extraction import extract_reservation_fields
from app.conversation.state import ConversationContext, ConversationState, ReservationDraft
from app.conversation.tools import create_reservation_request
from app.db.models import Reservation, Restaurant
from app.providers.embedding.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.rag.vector_db import VectorDB
from app.services import hours_service

# Consecutive UNCLEAR-intent turns before escalating — one retry is
# reasonable, two straight misses means the automated path isn't working
# for this caller.
_MAX_UNCLEAR_BEFORE_ESCALATION = 2

_RESERVATION_FIELD_PROMPTS = {
    "customer_name": "Can I get a name for the reservation?",
    "customer_phone": "What's the best phone number to reach you?",
    "reservation_date": "What date would you like to come in?",
    "reservation_time": "What time works for you?",
    "party_size": "How many people will be in your party?",
}

_CONFIRM_WORDS = ("yes", "yeah", "yep", "correct", "that's right", "sounds good", "confirm", "go ahead")
_DENY_WORDS = ("no", "wrong", "change", "actually", "incorrect")


@dataclass
class TurnResult:
    """What the engine produced for one caller turn."""

    response_text: str
    state: ConversationState
    should_transfer: bool = False
    transfer_reason: Optional[str] = None
    reservation: Optional[Reservation] = None


class ConversationEngine:
    def __init__(
        self,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        vector_db: VectorDB,
        db: AsyncSession,
        restaurant: Restaurant,
    ):
        self.llm = llm
        self.embedder = embedder
        self.vector_db = vector_db
        self.db = db
        self.restaurant = restaurant

    def _now(self) -> datetime:
        return datetime.now(ZoneInfo(self.restaurant.timezone))

    async def handle_turn(
        self, context: ConversationContext, message: str, call_sid: Optional[str] = None
    ) -> TurnResult:
        """Process one caller utterance and advance the conversation state."""
        context.add_turn("caller", message)

        if context.state in (ConversationState.GREETING, ConversationState.IDENTIFY_INTENT):
            context.state = ConversationState.IDENTIFY_INTENT
            return await self._handle_identify_intent(context, message)

        if context.state == ConversationState.RESERVATION_COLLECTING:
            return await self._handle_reservation_collecting(context, message)

        if context.state == ConversationState.RESERVATION_CONFIRMING:
            return await self._handle_reservation_confirming(context, message, call_sid)

        # TRANSFER_TO_HUMAN / ENDED: a live call shouldn't reach the engine
        # again in these states (Phase 5 will have transferred or hung up),
        # but handle it gracefully rather than raising.
        return self._say(context, "One moment, I'm connecting you now.")

    # ------------------------------------------------------------------
    # IDENTIFY_INTENT
    # ------------------------------------------------------------------

    async def _handle_identify_intent(self, context: ConversationContext, message: str) -> TurnResult:
        if await should_escalate(self.llm, self.restaurant.name, context, message):
            return self._transfer(context, "escalation")

        intent = await classify_intent(self.llm, self.restaurant.name, context, message)

        if intent == "HUMAN":
            return self._transfer(context, "caller_requested_human")

        if intent == "ORDER":
            return self._transfer(context, "order_request")

        if intent == "RESERVATION":
            context.unclear_count = 0
            context.state = ConversationState.RESERVATION_COLLECTING
            context.reservation_draft = await extract_reservation_fields(
                self.llm, self.restaurant.name, context.reservation_draft, message, self.restaurant.timezone, self._now()
            )
            return self._advance_reservation_collection(context)

        if intent == "FAQ":
            context.unclear_count = 0
            return await self._handle_faq(context, message)

        # UNCLEAR
        context.unclear_count += 1
        if context.unclear_count >= _MAX_UNCLEAR_BEFORE_ESCALATION:
            return self._transfer(context, "repeated_unclear")
        return self._say(context, "I'm sorry, could you tell me a bit more about what you need?")

    async def _handle_faq(self, context: ConversationContext, message: str) -> TurnResult:
        if hours_answer.looks_like_hours_question(message):
            hours = await hours_service.get_hours(self.db, self.restaurant.id)
            if hours_answer.looks_like_closing_time_question(message):
                answer = hours_answer.answer_closing_time_tonight(hours, self._now())
            else:
                answer = hours_answer.format_hours_summary(hours)
            return self._say(context, answer)

        answer, _grounded = await generate_faq_answer(
            self.llm, self.embedder, self.vector_db, self.restaurant.id, self.restaurant.name, message
        )
        return self._say(context, answer)

    # ------------------------------------------------------------------
    # RESERVATION_COLLECTING / RESERVATION_CONFIRMING
    # ------------------------------------------------------------------

    async def _handle_reservation_collecting(self, context: ConversationContext, message: str) -> TurnResult:
        context.reservation_draft = await extract_reservation_fields(
            self.llm, self.restaurant.name, context.reservation_draft, message, self.restaurant.timezone, self._now()
        )
        return self._advance_reservation_collection(context)

    def _advance_reservation_collection(self, context: ConversationContext) -> TurnResult:
        missing = context.reservation_draft.missing_fields()
        if missing:
            return self._say(context, _RESERVATION_FIELD_PROMPTS[missing[0]])

        context.state = ConversationState.RESERVATION_CONFIRMING
        return self._say(context, self._confirmation_text(context.reservation_draft))

    def _confirmation_text(self, draft: ReservationDraft) -> str:
        # Only called once _advance_reservation_collection() has confirmed
        # missing_fields() is empty, so these are guaranteed set.
        assert draft.reservation_date is not None
        assert draft.reservation_time is not None
        date_obj = datetime.strptime(draft.reservation_date, "%Y-%m-%d")
        hour, minute = (int(p) for p in draft.reservation_time.split(":"))
        period = "AM" if hour < 12 else "PM"
        hour_12 = hour % 12 or 12
        time_phrase = f"{hour_12} {period}" if minute == 0 else f"{hour_12}:{minute:02d} {period}"

        return (
            f"Just to confirm, that's a table for {draft.party_size} "
            f"on {date_obj.strftime('%A, %B %-d')} at {time_phrase}, "
            f"under {draft.customer_name}. Should I go ahead and submit this?"
        )

    async def _handle_reservation_confirming(
        self, context: ConversationContext, message: str, call_sid: Optional[str]
    ) -> TurnResult:
        normalized = message.strip().lower()

        if any(word in normalized for word in _CONFIRM_WORDS):
            reservation = await create_reservation_request(self.db, self.restaurant, context.reservation_draft, call_sid)
            context.state = ConversationState.IDENTIFY_INTENT
            context.reservation_draft = ReservationDraft()
            reply = (
                "Great, your reservation request has been submitted. "
                "The restaurant will confirm it with you shortly. Is there anything else I can help with?"
            )
            result = self._say(context, reply)
            result.reservation = reservation
            return result

        if any(word in normalized for word in _DENY_WORDS):
            context.state = ConversationState.RESERVATION_COLLECTING
            return self._say(context, "No problem — what would you like to change?")

        return self._say(context, "Sorry, should I go ahead and submit that reservation request?")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _say(self, context: ConversationContext, text: str) -> TurnResult:
        context.add_turn("assistant", text)
        return TurnResult(response_text=text, state=context.state)

    def _transfer(self, context: ConversationContext, reason: str) -> TurnResult:
        context.state = ConversationState.TRANSFER_TO_HUMAN
        context.transfer_reason = reason
        text = (
            "I'd be happy to connect you with a team member to place your order."
            if reason == "order_request"
            else "Let me connect you with a team member who can help."
        )
        context.add_turn("assistant", text)
        return TurnResult(response_text=text, state=context.state, should_transfer=True, transfer_reason=reason)
