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

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation import hours_answer, smalltalk
from app.conversation.confirmation import read_confirmation
from app.conversation.escalation import should_escalate
from app.conversation.intent import classify_intent
from app.conversation.phrasing import pick
from app.conversation.rag_answer import build_retrieval_query, generate_faq_answer
from app.conversation.reservation_extraction import extract_reservation_fields
from app.conversation.state import ConversationContext, ConversationState, ReservationDraft
from app.conversation.tools import create_reservation_request
from app.core.config import settings
from app.db.models import Reservation, Restaurant
from app.providers.embedding.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.rag.vector_db import VectorDB
from app.services import caller_service, hours_service

# Consecutive UNCLEAR-intent turns before escalating — one retry is
# reasonable, two straight misses means the automated path isn't working
# for this caller.
_MAX_UNCLEAR_BEFORE_ESCALATION = 2

_RESERVATION_FIELD_PROMPTS = {
    "customer_name": "Can I take a name for the booking?",
    "customer_phone": "What's the best number to reach you on?",
    "reservation_date": "What day were you thinking?",
    "reservation_time": "And what time suits you?",
    "party_size": "How many of you will there be?",
}

# Said before the next question while taking a booking. A person
# acknowledges what you just told them; asking the next question with
# nothing in between is what filling in a form sounds like.
_ACKNOWLEDGEMENTS = ("Got it.", "Perfect.", "Great, thank you.", "Lovely.")

# Asked when the caller's intent isn't clear. Several phrasings because
# this is the line most likely to be heard twice in a row, and hearing
# the identical sentence back is what makes a line feel automated. They
# also avoid "I'm sorry" as an opener — apologizing for not
# understanding, every time, wears on a caller quickly.
_UNCLEAR_PROMPTS = (
    "Sorry, I didn't quite catch that — what can I help you with?",
    "I want to make sure I get this right. What were you after?",
    "Could you say a bit more about what you need?",
)

_CONFIRM_WORDS = (
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "ok",
    "okay",
    "please",
    "correct",
    "that's right",
    "sounds good",
    "confirm",
    "go ahead",
)
_DENY_WORDS = ("no", "nope", "not", "don't", "wrong", "change", "incorrect")

# Phrases that contain a deny word but are not denials — several are
# among the most common ways to say yes. Removed before the deny check,
# so "sure, no problem" isn't read as a refusal.
_AFFIRMATIVE_IDIOMS = ("no problem", "no worries", "no doubt", "why not")


# Beyond this length, a reply that merely contains "yes" or "no" is
# saying something of its own — see _handle_confirm_transfer.
_SHORT_REPLY_WORDS = 4


def _is_short_reply(message: str) -> bool:
    return len(message.split()) <= _SHORT_REPLY_WORDS


# The caller wanting out of the booking they were in the middle of.
# Without this the reservation flow has no exit: every utterance goes to
# slot extraction, so "I don't want to make reservation", "I just want to
# cancel the reservation" and "no, I would like to place an order" were
# all read as booking details — and a reservation was created for a
# caller who had said three times that they didn't want one.
_ABANDON_RESERVATION_PHRASES = (
    "cancel",
    "never mind",
    "nevermind",
    "forget it",
    "forget the",
    "changed my mind",
    "change my mind",
    "don't want to make",
    "dont want to make",
    "don't want a reservation",
    "don't want the reservation",
    "don't want to book",
    "no reservation",
    "not a reservation",
    "place an order",
    "order instead",
    "stop",
)


def _wants_out_of_reservation(message: str) -> bool:
    """
    Whole-word, not substring: "cancel" lives inside "cancellation", so
    a caller mid-booking asking "what's your cancellation policy?" had
    their half-finished reservation thrown away and their question
    ignored. "stop" inside "non-stop" is the same trap.
    """
    return _says_any_of(message, _ABANDON_RESERVATION_PHRASES)


def _says_any_of(message: str, phrases: tuple[str, ...]) -> bool:
    """
    Whole-word matching, not substring.

    "You are not answering my question" was read as a "no" and treated as
    the caller declining a transfer, because "no" appears inside "not" —
    the caller was then dropped back to the start having had neither
    their question answered nor their transfer. "know", "nothing" and
    "now" all carry the same trap.
    """
    padded = f" {re.sub(r'[^a-z0-9 ]+', ' ', message.lower())} "
    padded = re.sub(r"\s+", " ", padded)
    return any(f" {re.sub(r'[^a-z0-9 ]+', ' ', phrase)} " in padded for phrase in phrases)


def _reads_as(message: str) -> Optional[str]:
    """
    The fast path for reading a yes or a no — "confirm", "deny" or None.

    None means "this list doesn't recognize it", NOT "the caller said
    neither". The engine sends those on to the classifier model (see
    _read_yes_no); this only ever answers when it is sure, because the
    set of ways to say yes on a phone has no edge a word list can reach.

    Deny wins when both appear, because both appearing is what a refusal
    looks like: "no, please don't" contains the confirm word "please",
    and checking confirm first booked a table for a caller who had just
    said not to. The two outcomes are not symmetric — a wrongly-heard
    "no" costs a turn, a wrongly-heard "yes" creates a reservation the
    caller never agreed to, or transfers a call they wanted to keep.

    Affirmative idioms are stripped first so that precedence doesn't
    swallow "sure, no problem", which is a yes.
    """
    lowered = message.lower()
    said_idiom = False
    for idiom in _AFFIRMATIVE_IDIOMS:
        if idiom in lowered:
            said_idiom = True
            lowered = lowered.replace(idiom, " ")

    if _says_any_of(lowered, _DENY_WORDS):
        return "deny"
    if _says_any_of(lowered, _CONFIRM_WORDS):
        return "confirm"
    # "no problem" and "why not" are whole answers on their own, and both
    # mean yes. Stripping them without this would leave nothing to match.
    return "confirm" if said_idiom else None

# What to ask when offering a transfer (see _offer_transfer) — keyed by
# the same reason strings should_escalate/classify_intent/unclear-count
# handling already produce. Falls back to a generic phrasing for any
# reason not listed here.
_OFFER_TRANSFER_PROMPTS = {
    "order_request": "I'm not able to take orders directly — would you like me to connect you with someone who can help with that?",
    "reservation_request": "I'd like to make sure your reservation is taken care of properly — would you like me to connect you with someone at the restaurant who can help with that?",
    "escalation": "I want to make sure you get the help you need — would you like me to connect you with a team member?",
    "repeated_unclear": "I'm having a hard time understanding — would you like me to connect you with a team member instead?",
    "unknown_answer": "I don't have that one in front of me, I'm afraid. Would you like me to connect you with someone at the restaurant who can tell you?",
    "change_existing_reservation": "Changing or cancelling a booking isn't something I can do myself — shall I put you through to someone who can sort that out?",
}


# Phrasings that ask about a booking the caller already has, rather than
# asking to make a new one. Kept as literal phrases rather than another
# LLM call: this only ever runs when the caller is already known to have
# an upcoming reservation, so the question it disambiguates is narrow.
_EXISTING_RESERVATION_PHRASES = (
    "remind me",
    "already booked",
    "already made",
    "already have",
    "my reservation",
    "my booking",
    "my table",
    "confirm my",
    "check my",
    "did i book",
    "do i have",
    "what time is my",
    "you should have",
)


def _asks_about_existing_reservation(message: str) -> bool:
    lowered = message.lower()
    return any(phrase in lowered for phrase in _EXISTING_RESERVATION_PHRASES)


# Changing or cancelling a booking that already exists. The AI cannot do
# either — nothing in the system cancels or amends a reservation — and
# pretending otherwise is what happened on a real call: "Can I cancel
# that reservation first?" and "I want to cancel it" were both
# classified RESERVATION and answered by collecting a brand new booking,
# so the caller ended up with a second table instead of none.
#
# The honest answer is a person. Kept as literal phrases rather than
# another model call because the wording is narrow and the cost of
# getting it wrong is a caller sent to a human they didn't need.
_CANCEL_OR_CHANGE_PHRASES = (
    "cancel",
    "cancel it",
    "cancel that",
    "cancel my",
    "call it off",
    "move my",
    "move it to",
    "change my",
    "change that",
    "reschedule",
    "push it back",
    "make it later",
    "make it earlier",
)


def _wants_to_change_a_booking(message: str) -> bool:
    return _says_any_of(message, _CANCEL_OR_CHANGE_PHRASES)


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
        classifier_llm: Optional[LLMProvider] = None,
    ):
        self.llm = llm
        self.embedder = embedder
        self.vector_db = vector_db
        self.db = db
        self.restaurant = restaurant
        # The escalation and intent calls answer with a single word from
        # a fixed list, so they can use a smaller, faster model than the
        # one that phrases what the caller actually hears. Defaults to
        # the same provider, so nothing changes unless one is supplied.
        self.classifier_llm = classifier_llm or llm

    def _now(self) -> datetime:
        return datetime.now(ZoneInfo(self.restaurant.timezone))

    async def _read_yes_no(
        self, context: ConversationContext, message: str
    ) -> Optional[str]:
        """
        Whether the caller agreed, declined, or neither.

        The word lists answer the common replies with no network call at
        all. Anything they don't recognize goes to the classifier rather
        than being treated as a non-answer — that fallback replaces a
        turn the caller would otherwise have spent being asked the same
        question again, so it costs nothing in practice and closes the
        gap a fixed list can never close. See confirmation.py.
        """
        fast = _reads_as(message)
        if fast is not None:
            return fast

        asked = context.last_assistant_text()
        if not asked:
            return None
        return await read_confirmation(self.classifier_llm, asked, message)

    def _collects_reservations(self) -> bool:
        """
        Whether this restaurant wants the AI to take booking details, or
        to offer a human instead.

        Per-restaurant, falling back to the deployment default when the
        restaurant hasn't expressed a preference — a place with a booking
        system and a place with a paper diary want opposite behavior, and
        that is a property of the client, not of the deployment.
        """
        if self.restaurant.takes_reservations is None:
            return settings.FEATURE_RESERVATION_COLLECTION
        return self.restaurant.takes_reservations

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

        if context.state == ConversationState.CONFIRM_TRANSFER:
            return await self._handle_confirm_transfer(context, message)

        # TRANSFER_TO_HUMAN / ENDED: a live call shouldn't reach the engine
        # again in these states (Phase 5 will have transferred or hung up),
        # but handle it gracefully rather than raising.
        return self._say(context, "One moment, I'm connecting you now.")

    # ------------------------------------------------------------------
    # IDENTIFY_INTENT
    # ------------------------------------------------------------------

    async def _handle_identify_intent(self, context: ConversationContext, message: str) -> TurnResult:
        # Both classify the same message and neither reads the other's
        # result, so they go out together rather than one after the
        # other. On a hosted LLM that's a whole network round trip taken
        # off every single turn — measured at 0.4-0.6s each on real
        # calls, on a path where the caller is sitting in silence.
        #
        # When escalation comes back YES the intent result is discarded,
        # which is the deliberate trade: one wasted classification call
        # on the rare turn, against a faster reply on every other turn.
        escalate, intent = await asyncio.gather(
            should_escalate(self.classifier_llm, self.restaurant.name, context, message),
            classify_intent(self.classifier_llm, self.restaurant.name, context, message),
        )

        if escalate:
            return self._offer_transfer(context, "escalation")

        if intent == "OUT_OF_SCOPE":
            # Not an escalation and not a knowledge gap — a restaurant
            # simply doesn't know the weather. Offering to transfer the
            # caller to a team member for it would waste everyone's time.
            context.unclear_count = 0
            return self._say(
                context, smalltalk.out_of_scope_reply(context.last_assistant_text())
            )

        if intent == "SMALLTALK":
            context.unclear_count = 0
            return self._say(context, self._smalltalk_reply(context, message))

        if intent == "HUMAN":
            # Belt and braces over the classifier: "what's your name?"
            # came back HUMAN on a real call and transferred the caller
            # out of a conversation they were perfectly happy in. Asking
            # who picked up is never a request to be handed to someone
            # else, so it never transfers, whatever the label says.
            if smalltalk.is_identity_question(message):
                context.unclear_count = 0
                return self._say(context, self._smalltalk_reply(context, message))
            return self._transfer(context, "caller_requested_human")

        if intent == "ORDER":
            return self._offer_transfer(context, "order_request")

        if intent == "RESERVATION":
            context.unclear_count = 0
            return await self._handle_reservation_intent(context, message)

        if intent == "FAQ":
            context.unclear_count = 0
            return await self._handle_faq(context, message)

        # UNCLEAR
        context.unclear_count += 1
        if context.unclear_count >= _MAX_UNCLEAR_BEFORE_ESCALATION:
            return self._offer_transfer(context, "repeated_unclear")
        return self._say(context, pick(_UNCLEAR_PROMPTS, context.last_assistant_text()))

    def _smalltalk_reply(self, context: ConversationContext, message: str) -> str:
        return smalltalk.reply_to(
            message,
            self.restaurant.name,
            avoid=context.last_assistant_text(),
            caller_name=context.caller_name,
            already_helped=context.answered_something,
        )

    async def _handle_reservation_intent(
        self, context: ConversationContext, message: str
    ) -> TurnResult:
        # Asking about a booking they already have is not a request to
        # make another one. A real caller asked "can you remind me my
        # reservation?" and was walked through booking from scratch —
        # name, phone number, party size — for a table they had booked
        # minutes earlier on the same call.
        if context.known_reservation and _asks_about_existing_reservation(message):
            context.answered_something = True
            return self._say(context, context.known_reservation)

        # Cancelling or moving an existing booking is something this
        # system genuinely cannot do — there is no code path that amends
        # or deletes a reservation. On a real call "Can I cancel that
        # reservation first?" was classified RESERVATION and answered by
        # collecting a whole new booking, so a caller trying to cancel
        # one table ended up holding two. Offer the person who can
        # actually do it.
        if _wants_to_change_a_booking(message):
            return self._offer_transfer(context, "change_existing_reservation")

        if not self._collects_reservations():
            # Some restaurants have no booking system of their own to
            # write a collected reservation into (e.g. paper-only) —
            # offering a human handoff instead of the AI collecting
            # details is the more honest MVP behavior there. A restaurant
            # that DOES want the AI to collect and create a real pending
            # Reservation row turns this back on.
            return self._offer_transfer(context, "reservation_request")

        context.state = ConversationState.RESERVATION_COLLECTING
        context.reservation_draft = await extract_reservation_fields(
            self.llm, self.restaurant.name, context.reservation_draft, message, self.restaurant.timezone, self._now()
        )
        self._prefill_known_caller_details(context)
        return self._advance_reservation_collection(context)

    def _prefill_known_caller_details(self, context: ConversationContext) -> None:
        """
        Fill in what the phone system and past bookings already told us,
        so the caller isn't asked for it.

        Asking someone to read out the number they are calling from is
        the clearest "this isn't really listening" moment a phone line
        has — and on a real call it cost a turn and came back from
        speech recognition as "619-689." with the last four digits
        missing, needing another turn to correct. Both prefilled values
        are read back for confirmation before anything is booked (see
        _confirmation_text), so a caller booking for someone else, or on
        someone else's phone, can still correct them.
        """
        draft = context.reservation_draft
        if draft.customer_phone is None and context.caller_number:
            draft.customer_phone = context.caller_number
        if draft.customer_name is None and context.caller_name:
            draft.customer_name = context.caller_name

    async def _handle_faq(self, context: ConversationContext, message: str) -> TurnResult:
        if hours_answer.looks_like_hours_question(message):
            hours = await hours_service.get_hours(self.db, self.restaurant.id)
            now = self._now()
            # Most specific question first: a caller who asked about one
            # day wants an answer about that day, not the whole week.
            if hours_answer.looks_like_tomorrow_question(message):
                answer = hours_answer.answer_hours_tomorrow(hours, now)
            elif hours_answer.looks_like_open_now_question(message):
                answer = hours_answer.answer_open_now(hours, now)
            elif hours_answer.looks_like_closing_time_question(message):
                answer = hours_answer.answer_closing_time_tonight(hours, now)
            else:
                answer = hours_answer.format_hours_summary(hours)
            context.answered_something = True
            return self._say(context, answer)

        answer, grounded = await generate_faq_answer(
            self.llm,
            self.embedder,
            self.vector_db,
            self.restaurant.id,
            self.restaurant.name,
            message,
            # Follow-ups ("what are they?", "does it come with a side?")
            # have to be searched together with the turn that gave them
            # their subject — see build_retrieval_query.
            search_query=build_retrieval_query(context.history, message),
            # The answer also needs the exchange, not just the right
            # chunks: "what are they?" has to be answered about
            # whatever was being discussed a moment ago.
            conversation_context=context.history_text(max_turns=6),
        )
        # An ungrounded answer offers to connect the caller with someone —
        # so actually make that offer, rather than saying the words and
        # dropping back to intent classification, where the caller's "yes,
        # please" lands as a brand-new request and goes nowhere. Hit live:
        # two turns in a row promising a connection that never came.
        if not grounded:
            return self._offer_transfer(context, "unknown_answer")
        context.answered_something = True
        return self._say(context, answer)

    # ------------------------------------------------------------------
    # RESERVATION_COLLECTING / RESERVATION_CONFIRMING
    # ------------------------------------------------------------------

    async def _abandon_reservation(self, context: ConversationContext, message: str) -> TurnResult:
        """
        Drop the half-collected booking and deal with what they actually
        said. Re-running intent rather than just apologising means "no, I
        would like to place an order" is acted on in the same breath,
        instead of costing the caller another turn to repeat themselves.
        """
        context.reservation_draft = ReservationDraft()
        context.state = ConversationState.IDENTIFY_INTENT
        context.unclear_count = 0
        return await self._handle_identify_intent(context, message)

    async def _handle_reservation_collecting(self, context: ConversationContext, message: str) -> TurnResult:
        if _wants_out_of_reservation(message):
            return await self._abandon_reservation(context, message)

        context.reservation_draft = await extract_reservation_fields(
            self.llm, self.restaurant.name, context.reservation_draft, message, self.restaurant.timezone, self._now()
        )
        return self._advance_reservation_collection(context, acknowledge=True)

    def _advance_reservation_collection(
        self, context: ConversationContext, acknowledge: bool = False
    ) -> TurnResult:
        missing = context.reservation_draft.missing_fields()
        if missing:
            question = _RESERVATION_FIELD_PROMPTS[missing[0]]
            # A person says "got it" before the next question. Firing one
            # question straight after another, with nothing in between,
            # is what filling in a form sounds like.
            if acknowledge:
                question = f"{pick(_ACKNOWLEDGEMENTS, context.last_assistant_text())} {question}"
            return self._say(context, question)

        context.state = ConversationState.RESERVATION_CONFIRMING
        return self._say(context, self._confirmation_text(context.reservation_draft, context))

    def _confirmation_text(self, draft: ReservationDraft, context: ConversationContext) -> str:
        # Only called once _advance_reservation_collection() has confirmed
        # missing_fields() is empty, so these are guaranteed set.
        assert draft.reservation_date is not None
        assert draft.reservation_time is not None
        date_obj = datetime.strptime(draft.reservation_date, "%Y-%m-%d")
        hour, minute = (int(p) for p in draft.reservation_time.split(":"))
        period = "AM" if hour < 12 else "PM"
        hour_12 = hour % 12 or 12
        time_phrase = f"{hour_12} {period}" if minute == 0 else f"{hour_12}:{minute:02d} {period}"

        readback = (
            f"Let me read that back: a table for {draft.party_size} "
            f"on {date_obj.strftime('%A, %B %-d')} at {time_phrase}, "
            f"under {draft.customer_name}."
        )

        # A number taken from caller ID was never spoken aloud by the
        # caller, so it gets confirmed here rather than silently assumed
        # — they can correct it before anything is booked.
        if draft.customer_phone and draft.customer_phone == context.caller_number:
            readback += " I'll use the number you're calling from."

        return f"{readback} Shall I put that in for you?"

    async def _handle_reservation_confirming(
        self, context: ConversationContext, message: str, call_sid: Optional[str]
    ) -> TurnResult:
        if _wants_out_of_reservation(message):
            return await self._abandon_reservation(context, message)

        normalized = message.strip().lower()

        # A longer reply may be changing a detail rather than answering
        # the question — "yes, but can you make it 8 instead" contains
        # "yes", and reading only that books the table at the time the
        # caller was in the middle of correcting. This is the same guard
        # _handle_confirm_transfer already had; its absence here was
        # worse, because this branch writes a real reservation.
        #
        # So the reply is re-extracted first. If it moved any field, the
        # new details get read back for confirmation instead of being
        # booked silently; if it changed nothing, it's just a wordy yes
        # or no and is treated as one.
        if not _is_short_reply(normalized):
            previous = context.reservation_draft
            context.reservation_draft = await extract_reservation_fields(
                self.llm,
                self.restaurant.name,
                context.reservation_draft,
                message,
                self.restaurant.timezone,
                self._now(),
            )
            if context.reservation_draft != previous:
                return self._advance_reservation_collection(context, acknowledge=True)

        reading = await self._read_yes_no(context, normalized)

        if reading == "confirm":
            reservation = await create_reservation_request(self.db, self.restaurant, context.reservation_draft, call_sid)
            context.state = ConversationState.IDENTIFY_INTENT
            context.reservation_draft = ReservationDraft()
            # Not "submitted" — that's software talking. But not
            # "you're booked" either: this is a request the restaurant
            # still has to confirm, and a caller who turns up thinking
            # they have a table when they don't is the worst outcome
            # this flow can produce.
            # Remember it for the rest of THIS call. known_reservation was
            # only ever filled at call start from past bookings, so a
            # table booked two minutes ago was invisible: a real caller
            # asked "can you remind me what was my booking?", then "no, I
            # am asking for my current reservation that you booked", then
            # "I'm asking for the reservation that I just made for
            # tomorrow" — and was walked toward a fresh booking all three
            # times, because as far as the engine knew they had none.
            context.known_reservation = caller_service.describe_reservation(reservation)

            reply = (
                "Lovely, I've got that down. Someone will give you a quick call to confirm it. "
                "Anything else I can help with?"
            )
            result = self._say(context, reply)
            result.reservation = reservation
            return result

        if reading == "deny":
            context.state = ConversationState.RESERVATION_COLLECTING
            return self._say(context, "No problem — what would you like to change?")

        return self._say(context, "Sorry, shall I go ahead and put that booking in?")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _say(self, context: ConversationContext, text: str) -> TurnResult:
        context.add_turn("assistant", text)
        return TurnResult(response_text=text, state=context.state)

    def _transfer(self, context: ConversationContext, reason: str) -> TurnResult:
        """
        Transfer immediately, no confirmation asked. Only for
        "caller_requested_human" — they already explicitly asked for a
        person, so asking "would you like a human?" back would be a
        redundant, irritating extra turn. Every other transfer trigger
        goes through _offer_transfer instead.
        """
        context.state = ConversationState.TRANSFER_TO_HUMAN
        context.transfer_reason = reason
        text = "Let me connect you with a team member who can help."
        context.add_turn("assistant", text)
        return TurnResult(response_text=text, state=context.state, should_transfer=True, transfer_reason=reason)

    def _offer_transfer(self, context: ConversationContext, reason: str) -> TurnResult:
        """
        Ask before transferring, rather than forcing a handoff on the
        engine's own judgment — the way a human agent would say "would
        you like me to get someone for you?" instead of silently
        forwarding the call. context.transfer_reason holds the reason
        while parked in CONFIRM_TRANSFER; should_transfer only becomes
        True once _handle_confirm_transfer sees the caller actually
        agree.
        """
        context.state = ConversationState.CONFIRM_TRANSFER
        context.transfer_reason = reason
        text = _OFFER_TRANSFER_PROMPTS.get(
            reason, "Would you like me to connect you with a team member who can help?"
        )
        context.add_turn("assistant", text)
        return TurnResult(response_text=text, state=context.state)

    async def _handle_confirm_transfer(
        self, context: ConversationContext, message: str
    ) -> TurnResult:
        normalized = message.strip().lower()

        # A question asked while the offer is pending gets answered, and
        # the offer stands. A caller asked "sure, but before you transfer
        # me, what's your name?" and got neither — just the offer
        # repeated — and said, fairly, "you are not answering my
        # question."
        if smalltalk.is_identity_question(message):
            return self._say(
                context,
                f"{smalltalk.identity_answer(self.restaurant.name)} "
                "Would you still like me to connect you with a team member?",
            )

        # Only a SHORT reply is treated as answering the offer. A longer
        # sentence that happens to start with "yes" or "no" is the caller
        # telling you what they actually want, and taking just the first
        # word throws the rest away — live, "not yet, I just need a
        # reservation for 7 o'clock tomorrow" was heard as "no" and the
        # reservation never happened, and "yes, but also I want to make
        # sure that if we arrive early" was heard as "yes" and the
        # question was never answered.
        if _is_short_reply(normalized):
            reading = await self._read_yes_no(context, normalized)

            if reading == "confirm":
                reason = context.transfer_reason
                context.state = ConversationState.TRANSFER_TO_HUMAN
                text = "Okay, connecting you now."
                context.add_turn("assistant", text)
                return TurnResult(response_text=text, state=context.state, should_transfer=True, transfer_reason=reason)

            if reading == "deny":
                context.state = ConversationState.IDENTIFY_INTENT
                context.transfer_reason = None
                # A fresh start on identifying what they need — the UNCLEAR
                # streak (if any) that led here shouldn't count against a
                # caller who just chose to keep talking to the AI instead.
                context.unclear_count = 0
                return self._say(context, "No problem — is there anything else I can help with?")

        # Anything else is a new request, not an answer to the offer.
        # Repeating the offer instead traps the caller: they ask their
        # question, hear the offer again, ask again — a real call went
        # round that loop three times, with the caller eventually saying
        # "well, I'm asking you if I arrive early."
        context.state = ConversationState.IDENTIFY_INTENT
        context.transfer_reason = None
        context.unclear_count = 0
        return await self._handle_identify_intent(context, message)
