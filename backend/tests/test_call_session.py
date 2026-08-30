"""
Tests for app.voice.session.CallSession — the per-call orchestrator.

_process_utterance() is exercised directly (bypassing the VAD/turn
detector, which has its own dedicated tests in test_audio_vad.py) by
feeding it canned audio via turn_detector.pop_utterance() — this keeps
these tests focused on the STT -> conversation engine -> TTS ->
outcome-tracking pipeline, not on reproducing realistic speech audio.
"""

import base64
import json

import numpy as np

from app.conversation.state import ConversationState
from app.db.models import CallOutcomeEnum
from app.services import call_service
from app.voice.session import CallSession
from tests.fakes import FakeTTSProvider, ScriptedLLMProvider, ScriptedSTTProvider, contains


def _fake_audio_frame():
    return np.ones(1600, dtype=np.int16) * 5000  # 200ms of "speech" @ 8kHz


class _RecordingSender:
    """Collects every audio chunk CallSession sends, for assertions."""

    def __init__(self):
        self.sent: list[bytes] = []

    async def __call__(self, mulaw_bytes: bytes) -> None:
        self.sent.append(mulaw_bytes)


async def _make_session(db_session, restaurant, vector_db, embedding_provider, llm, stt=None):
    call = await call_service.create_call(
        db_session, restaurant.id, "CA_test", "+15551234567", restaurant.phone_number
    )
    sender = _RecordingSender()
    session = CallSession(
        db_session,
        call,
        restaurant,
        stt or ScriptedSTTProvider([]),
        FakeTTSProvider(),
        llm,
        embedding_provider,
        vector_db,
        sender,
    )
    return session, sender


async def test_start_speaks_default_greeting(db_session, restaurant, vector_db, embedding_provider):
    llm = ScriptedLLMProvider([], default="FAQ")
    session, sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm
    )

    await session.start()

    assert len(sender.sent) == 1  # one audio chunk was sent
    assert any(
        t.role == "assistant" and restaurant.name in t.content for t in session.context.history
    )


async def test_start_uses_custom_ai_greeting(db_session, restaurant, vector_db, embedding_provider):
    restaurant.ai_greeting = "Welcome to our custom greeting!"
    llm = ScriptedLLMProvider([], default="FAQ")
    session, sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm
    )

    await session.start()

    assert session.context.history[0].content == "Welcome to our custom greeting!"


async def test_handle_media_ignores_audio_while_speaking(
    db_session, restaurant, vector_db, embedding_provider
):
    """No barge-in: while _speaking_until is in the future, incoming
    audio must not reach the turn detector at all."""
    llm = ScriptedLLMProvider([], default="FAQ")
    stt = ScriptedSTTProvider([("should not be called", 0.9)])
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )

    import time

    session._speaking_until = time.monotonic() + 60  # far in the future

    payload = base64.b64encode(b"\xff" * 160).decode("ascii")
    for _ in range(50):  # enough frames to normally trigger a turn
        await session.handle_media(payload)

    assert len(stt.calls) == 0  # transcribe() was never reached


async def test_empty_transcription_is_ignored(
    db_session, restaurant, vector_db, embedding_provider
):
    llm = ScriptedLLMProvider([], default="FAQ")
    stt = ScriptedSTTProvider([("", 0.0)])
    session, sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()

    assert len(sender.sent) == 0  # nothing spoken back
    assert session.context.history == []  # no turn recorded either


async def test_faq_utterance_updates_outcome_and_speaks_response(
    db_session, restaurant, vector_db, embedding_provider
):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
            (contains("using ONLY the information below"), "SHOULD_NOT_BE_CALLED"),
        ]
    )
    stt = ScriptedSTTProvider([("What time do you close tonight?", 0.95)])
    session, sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()

    assert session.final_outcome == CallOutcomeEnum.FAQ_ANSWERED
    assert len(sender.sent) == 1
    assert any(
        "close" in t.content.lower() for t in session.context.history if t.role == "assistant"
    )


async def test_full_reservation_flow_creates_reservation_and_sets_outcome(
    db_session, restaurant, vector_db, embedding_provider
):
    extraction_responses = iter(
        [
            json.dumps(
                {
                    "customer_name": "Jane Smith",
                    "customer_phone": "555-123-4567",
                    "reservation_date": "2026-09-04",
                    "reservation_time": "19:00",
                    "party_size": 4,
                    "special_notes": None,
                }
            )
        ]
    )
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
            (contains("Extract reservation details"), lambda _p: next(extraction_responses)),
        ]
    )
    stt = ScriptedSTTProvider(
        [
            ("Table for four, Jane Smith, Friday at 7, 555-123-4567", 0.9),
            ("Yes that's correct", 0.9),
        ]
    )
    session, sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )

    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()
    await session._process_utterance()
    assert session.context.state == ConversationState.RESERVATION_CONFIRMING

    await session._process_utterance()
    assert session.final_outcome == CallOutcomeEnum.RESERVATION_CREATED
    assert len(sender.sent) == 2

    from sqlalchemy import select

    from app.db.models import Reservation

    result = await db_session.execute(
        select(Reservation).where(Reservation.restaurant_id == restaurant.id)
    )
    reservation = result.scalar_one()
    assert reservation.customer_name == "Jane Smith"
    assert reservation.call_sid == "CA_test"


async def test_order_request_sets_should_close_and_transferred_outcome(
    db_session, restaurant, vector_db, embedding_provider
):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "ORDER"),
        ]
    )
    stt = ScriptedSTTProvider([("I want to order two burgers", 0.9)])
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()

    assert session.should_close is True
    assert session.final_outcome == CallOutcomeEnum.CALL_TRANSFERRED


async def test_end_finalizes_call_marks_unresolved_calls_abandoned(
    db_session, restaurant, vector_db, embedding_provider
):
    llm = ScriptedLLMProvider([], default="FAQ")
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm
    )

    await session.end()
    await db_session.commit()

    assert session.call.outcome == CallOutcomeEnum.CALL_ABANDONED
    assert session.call.end_time is not None


async def test_end_preserves_a_resolved_outcome(
    db_session, restaurant, vector_db, embedding_provider
):
    llm = ScriptedLLMProvider([], default="FAQ")
    stt = ScriptedSTTProvider([("What time do you close tonight?", 0.9)])
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()
    await session.end()
    await db_session.commit()

    assert session.call.outcome == CallOutcomeEnum.FAQ_ANSWERED
