"""
What the caller hears when something behind the scenes breaks.

A phone call has no error page. If Groq is down, or Ollama is not
running, or the vector store is unreachable, the caller is still on the
line — and the worst possible response is the one that costs nothing to
implement: silence, until they give up and hang up.

Every scenario here asserts two things: the caller hears something, and
what they hear does not leak the failure.
"""

import logging

import numpy as np

from app.db.models import CallOutcomeEnum
from app.services import call_service
from app.voice.session import CallSession
from tests.fakes import FakeTTSProvider, ScriptedLLMProvider, ScriptedSTTProvider


def _fake_audio_frame():
    return np.ones(1600, dtype=np.int16) * 5000


class _RecordingSender:
    def __init__(self):
        self.sent: list[bytes] = []

    async def __call__(self, mulaw_bytes: bytes) -> None:
        self.sent.append(mulaw_bytes)


class _BrokenLLM(ScriptedLLMProvider):
    """Stands in for a provider outage — Groq 503, a timeout, a DNS failure."""

    def __init__(self, message="Groq is unreachable"):
        super().__init__([])
        self.message = message

    async def generate(self, prompt: str, **kwargs) -> str:
        raise ConnectionError(self.message)


async def _session(db_session, restaurant, vector_db, embedding_provider, llm, stt):
    call = await call_service.create_call(
        db_session, restaurant.id, "CA_fail", "+15551234567", restaurant.phone_number
    )
    sender = _RecordingSender()
    session = CallSession(
        db_session, call, restaurant, stt, FakeTTSProvider(), llm,
        embedding_provider, vector_db, sender,
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()
    return session, sender


async def test_an_llm_outage_does_not_leave_the_caller_in_silence(
    db_session, restaurant, vector_db, embedding_provider, caplog
):
    """
    The engine has no error handling of its own, so a provider raising
    propagated all the way to the turn task, which logged it and
    returned. The caller heard nothing at all and eventually hung up.
    """
    stt = ScriptedSTTProvider([("do you have parking?", 0.9)])
    session, sender = await _session(
        db_session, restaurant, vector_db, embedding_provider, _BrokenLLM(), stt
    )

    with caplog.at_level(logging.INFO):
        await session._process_utterance()

    assert sender.sent, "the caller heard nothing"

    spoken = " ".join(t.content for t in session.context.history if t.role == "assistant")
    assert spoken, "nothing was recorded as said"
    # And it must not read the stack trace out to them.
    for leak in ("Groq", "ConnectionError", "Traceback", "unreachable", "None"):
        assert leak not in spoken, f"internal detail {leak!r} leaked to the caller"


async def test_a_repeatedly_broken_backend_hands_the_caller_to_a_person(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    Apologising forever is its own failure. If the backend is genuinely
    down, the caller should reach someone who can actually help.
    """
    stt = ScriptedSTTProvider([("do you have parking?", 0.9)] * 5)
    session, _sender = await _session(
        db_session, restaurant, vector_db, embedding_provider, _BrokenLLM(), stt
    )

    for _ in range(3):
        await session._process_utterance()

    assert session.should_close is True
    assert session.final_outcome == CallOutcomeEnum.HUMAN_ESCALATION


async def test_a_working_turn_clears_the_failure_streak(
    db_session, restaurant, vector_db, embedding_provider
):
    """One blip mid-call must not push a later one straight to a human."""
    from tests.fakes import contains

    class _FlakyLLM(ScriptedLLMProvider):
        def __init__(self):
            super().__init__(
                [
                    (contains("decide if it needs to be handed off"), "NO"),
                    (contains("Respond with exactly one of these labels"), "FAQ"),
                ]
            )
            self.calls_made = 0

        async def generate(self, prompt: str, **kwargs) -> str:
            self.calls_made += 1
            if self.calls_made <= 2:  # the first turn's two classifier calls
                raise ConnectionError("blip")
            return await super().generate(prompt, **kwargs)

    stt = ScriptedSTTProvider([("do you have parking?", 0.9)] * 4)
    session, _sender = await _session(
        db_session, restaurant, vector_db, embedding_provider, _FlakyLLM(), stt
    )

    await session._process_utterance()   # fails
    await session._process_utterance()   # recovers
    await session._process_utterance()   # would be strike 3 if it counted

    assert session.should_close is False


# ----------------------------------------------------------------------
# Failures on the paths GAP-006 did not cover
# ----------------------------------------------------------------------


class _BrokenTTS(FakeTTSProvider):
    """Speech synthesis is down — no audio can be produced at all."""

    async def synthesize(self, text: str):
        raise RuntimeError("kokoro pipeline unavailable")


async def test_a_greeting_that_cannot_be_spoken_reaches_a_person(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    Worse than any mid-call failure: the line is answered and silent from
    the first second. Dropping the call loses the customer; the caller
    rang a restaurant, so send them to the restaurant.
    """
    call = await call_service.create_call(
        db_session, restaurant.id, "CA_greet", "+15551234567", restaurant.phone_number
    )
    session = CallSession(
        db_session, call, restaurant, ScriptedSTTProvider([]), _BrokenTTS(),
        ScriptedLLMProvider([], default="FAQ"), embedding_provider, vector_db,
        _RecordingSender(),
    )

    await session.start()  # must not raise

    assert session.should_close is True
    assert session.final_outcome == CallOutcomeEnum.HUMAN_ESCALATION


async def test_a_booking_that_succeeded_is_never_reported_as_failed(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    describe_reservation string-parses the stored time and is called
    AFTER the reservation is written. A formatting failure there used to
    fail the whole turn — so the table existed and the caller was told
    something went wrong. Telling someone their booking failed when it
    did not is worse than any wording problem the read-back could have.
    """
    import json

    from app.conversation.engine import ConversationEngine
    from app.conversation.state import ConversationContext, ConversationState
    from app.services import caller_service
    from tests.dates import FUTURE_DATE
    from tests.fakes import contains

    def _broken_describe(_reservation):
        raise ValueError("unexpected time format")

    original = caller_service.describe_reservation
    caller_service.describe_reservation = _broken_describe
    try:
        llm = ScriptedLLMProvider(
            [
                (contains("decide if it needs to be handed off"), "NO"),
                (contains("Respond with exactly one of these labels"), "RESERVATION"),
                (
                    contains("Extract reservation details"),
                    json.dumps({"customer_name": "Jane", "customer_phone": "5551234567",
                                "reservation_date": FUTURE_DATE, "reservation_time": "19:00",
                                "party_size": 2, "special_notes": None}),
                ),
            ]
        )
        engine = ConversationEngine(
            llm, embedding_provider, vector_db, db_session, restaurant
        )
        context = ConversationContext(restaurant_id=restaurant.id)

        await engine.handle_turn(context, "table for two Friday at 7, Jane, 555-123-4567")
        assert context.state == ConversationState.RESERVATION_CONFIRMING

        result = await engine.handle_turn(context, "yes please", call_sid="CA_book")

        # The booking stands, and the caller is told so.
        assert result.reservation is not None
        assert "got that down" in result.response_text
    finally:
        caller_service.describe_reservation = original


async def test_tts_failing_mid_reply_does_not_kill_the_turn(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    Replies are synthesized a sentence at a time. The second sentence
    failing must not throw away the first, nor take down the call.
    """
    class _FailsAfterFirst(FakeTTSProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def synthesize(self, text: str):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("kokoro fell over")
            return await super().synthesize(text)

    call = await call_service.create_call(
        db_session, restaurant.id, "CA_mid", "+15551234567", restaurant.phone_number
    )
    sender = _RecordingSender()
    session = CallSession(
        db_session, call, restaurant, ScriptedSTTProvider([]), _FailsAfterFirst(),
        ScriptedLLMProvider([], default="FAQ"), embedding_provider, vector_db, sender,
    )

    await session._speak("Here is the first sentence. And here is a second one.")

    # The caller heard what could be produced, and the call survives.
    assert len(sender.sent) == 1
