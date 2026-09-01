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
from app.voice.session import CallSession, _is_prompt_echo, _split_into_speakable_chunks
from tests.fakes import FakeTTSProvider, ScriptedLLMProvider, ScriptedSTTProvider, contains


def _fake_audio_frame():
    return np.ones(1600, dtype=np.int16) * 5000  # 200ms of "speech" @ 8kHz


class _RecordingSender:
    """
    Collects every audio chunk CallSession sends, for assertions.

    Note that chunks are NOT one-per-reply: replies are synthesized and
    sent a sentence at a time so the caller starts hearing the answer
    while the rest is still being generated (see _speak). Assert on
    whether audio was sent, not on how many pieces it arrived in.
    """

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

    assert len(sender.sent) >= 1  # the greeting was spoken
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


async def test_punctuation_only_transcription_is_ignored(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    Whisper renders silence and line noise as bare punctuation, not as an
    empty string. A real call produced ".  .  .  ." from a pause, which
    ran the full intent and escalation pipeline and had the assistant
    offer to transfer the caller over a sound they never made.
    """
    llm = ScriptedLLMProvider([], default="FAQ")
    stt = ScriptedSTTProvider([(".  .  .  .", 0.3)])
    session, sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()

    assert len(sender.sent) == 0
    assert session.context.history == []


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
    assert len(sender.sent) >= 1
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
    assert len(sender.sent) >= 2  # at least one chunk per spoken reply

    from sqlalchemy import select

    from app.db.models import Reservation

    result = await db_session.execute(
        select(Reservation).where(Reservation.restaurant_id == restaurant.id)
    )
    reservation = result.scalar_one()
    assert reservation.customer_name == "Jane Smith"
    assert reservation.call_sid == "CA_test"


async def test_order_request_offers_a_transfer_before_closing(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    The engine now asks before transferring on an order request (see
    ConversationState.CONFIRM_TRANSFER's docstring) rather than closing
    the call on the first turn — should_close only flips True once the
    caller actually agrees to be connected.
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "ORDER"),
        ]
    )
    stt = ScriptedSTTProvider([("I want to order two burgers", 0.9), ("Yes please", 0.9)])
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()
    assert session.should_close is False
    assert session.context.state == ConversationState.CONFIRM_TRANSFER

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


# ----------------------------------------------------------------------
# Streaming speech synthesis
#
# Kokoro on CPU costs roughly as long as the reply is long — measured at
# 1.6s for "Okay" and 6.2s for a two-sentence answer. Synthesizing the
# whole reply before sending any of it means the caller hears nothing
# for that whole time, so replies are sent a sentence at a time.
# ----------------------------------------------------------------------


def test_speech_is_split_into_sentences_for_streaming():
    chunks = _split_into_speakable_chunks(
        "Yes, we're all halal. Everything on the menu is. Did you want to hear the specials?"
    )
    assert chunks == [
        "Yes, we're all halal. Everything on the menu is.",
        "Did you want to hear the specials?",
    ]


def test_short_leading_fragments_merge_forward():
    """
    The point is to start speaking sooner, not to chop delivery into
    pieces — a bare "Yes." isn't worth its own synthesis pass and the
    audible seam it costs.
    """
    assert _split_into_speakable_chunks("Yes. We're open until ten tonight.") == [
        "Yes. We're open until ten tonight."
    ]


def test_single_sentence_is_one_chunk():
    assert _split_into_speakable_chunks("We're at 388 East Main Street in El Cajon.") == [
        "We're at 388 East Main Street in El Cajon."
    ]


# ----------------------------------------------------------------------
# Whisper echoing its own vocabulary hint
#
# STT_INITIAL_PROMPT is fed to Whisper as preceding context to bias it
# toward the restaurant's dish names. Whisper's job is to continue the
# text it is given, so on unclear audio it sometimes continues the
# prompt instead of transcribing the caller — a real call logged the
# caller as saying "We serve halal Syrian and Mediterranean food."
# ----------------------------------------------------------------------


def test_prompt_echo_is_detected():
    from app.core.config import settings

    assert _is_prompt_echo("shawarma, kibbeh, falafel, hummus, tahina")
    # The echo comes back reworded and repunctuated, not character-exact.
    assert _is_prompt_echo(" ".join(settings.STT_INITIAL_PROMPT.split()[:8]))


def test_a_caller_using_menu_words_is_not_mistaken_for_an_echo():
    """
    Callers say these words — that's the whole reason they're in the
    hint. Only an utterance made almost entirely of them is an echo.
    """
    assert not _is_prompt_echo("Do you have chicken shawarma?")
    assert not _is_prompt_echo("Is the falafel vegan?")
    assert not _is_prompt_echo("How much is the hummus and the mixed grill?")
    assert not _is_prompt_echo("shawarma")
