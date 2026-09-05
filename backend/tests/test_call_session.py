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
from tests.dates import FUTURE_DATE
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


async def test_quiet_audio_while_speaking_does_not_start_a_turn(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    While the assistant is speaking, audio below the barge-in bar must
    not reach the turn detector — it's line noise, or echo of our own
    voice. Only sustained speech interrupts (see the barge-in tests at
    the bottom of this file).
    """
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
                    "reservation_date": FUTURE_DATE,
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
# A vocabulary hint is fed to Whisper as preceding context to bias it
# toward the restaurant's dish names. Whisper's job is to continue the
# text it is given, so on unclear audio it sometimes continues the
# prompt instead of transcribing the caller — a real call logged the
# caller as saying "We serve halal Syrian and Mediterranean food."
#
# The hint is per restaurant, so these tests supply their own rather
# than reading the deployment default.
# ----------------------------------------------------------------------

_MENU_WORDS = "shawarma, kibbeh, falafel, hummus, tahina, tabouli, fattoush, baklava"


def test_prompt_echo_is_detected():
    assert _is_prompt_echo("shawarma, kibbeh, falafel, hummus, tahina", _MENU_WORDS)
    # The echo comes back reworded and repunctuated, not character-exact.
    assert _is_prompt_echo(" ".join(_MENU_WORDS.split()[:6]), _MENU_WORDS)


def test_a_caller_using_menu_words_is_not_mistaken_for_an_echo():
    """
    Callers say these words — that's the whole reason they're in the
    hint. Only an utterance made almost entirely of them is an echo.
    """
    assert not _is_prompt_echo("Do you have chicken shawarma?", _MENU_WORDS)
    assert not _is_prompt_echo("Is the falafel vegan?", _MENU_WORDS)
    assert not _is_prompt_echo("How much is the hummus and the tabouli?", _MENU_WORDS)
    assert not _is_prompt_echo("shawarma", _MENU_WORDS)


def test_the_echo_guard_follows_the_restaurants_own_vocabulary():
    """
    The guard is meaningless if it checks against a different
    restaurant's words: an Italian restaurant's caller saying "carbonara,
    marinara, bolognese" is an echo of ITS hint, and nothing to do with
    a Mediterranean menu.
    """
    italian = "carbonara, marinara, bolognese, arrabbiata, bruschetta"
    assert _is_prompt_echo("carbonara, marinara, bolognese, arrabbiata", italian)
    assert not _is_prompt_echo("carbonara, marinara, bolognese, arrabbiata", _MENU_WORDS)


# ----------------------------------------------------------------------
# Per-restaurant speech-recognition vocabulary
#
# One process serves every restaurant, so the vocabulary hint has to
# travel with the call, not with the deployment. A global list of one
# cuisine's dish names actively hurts another's: it biases the
# recognizer toward "shawarma" when the caller said "carbonara".
# ----------------------------------------------------------------------


async def test_a_restaurants_own_vocabulary_reaches_speech_recognition(
    db_session, restaurant, vector_db, embedding_provider
):
    restaurant.stt_vocabulary = "carbonara, marinara, bolognese, bruschetta"
    llm = ScriptedLLMProvider([], default="FAQ")
    stt = ScriptedSTTProvider([("Do you have carbonara?", 0.9)])
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()

    assert stt.vocabularies == ["carbonara, marinara, bolognese, bruschetta"]


async def test_a_restaurant_without_its_own_vocabulary_gets_the_default(
    db_session, restaurant, vector_db, embedding_provider
):
    """Onboarding a business must never be blocked on filling this in —
    an unset vocabulary is no worse off than having no per-restaurant
    setting at all."""
    from app.core.config import settings

    assert restaurant.stt_vocabulary is None
    llm = ScriptedLLMProvider([], default="FAQ")
    stt = ScriptedSTTProvider([("What time do you close?", 0.9)])
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()

    assert stt.vocabularies == [settings.STT_INITIAL_PROMPT]


# ----------------------------------------------------------------------
# What the call gets recorded as
#
# The outcome is what the dashboard counts, so an over-generous one is
# not a cosmetic problem — it reports the AI succeeding at calls it
# didn't.
# ----------------------------------------------------------------------


async def test_a_call_where_nothing_was_answered_is_not_recorded_as_answered(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    Any completed turn used to count as FAQ_ANSWERED, so a caller who
    only said hello — or whose question the knowledge base couldn't
    cover — was filed as a question successfully answered.
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "SMALLTALK"),
        ]
    )
    stt = ScriptedSTTProvider([("Hello, how are you doing today?", 0.9)])
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()

    assert session.final_outcome == CallOutcomeEnum.UNKNOWN
    assert session.context.answered_something is False

    # And an abandoned call is what it actually was.
    await session.end()
    await db_session.commit()
    assert session.call.outcome == CallOutcomeEnum.CALL_ABANDONED


# ----------------------------------------------------------------------
# Audio too poor to act on
#
# Whisper always returns its best guess. A real call answered "Fiyopas."
# (confidence 0.42) and "free of us" (0.41) with confident replies to
# things the caller never said — the confidence was in the log the whole
# time and nothing read it.
# ----------------------------------------------------------------------


async def test_a_low_confidence_transcript_is_not_acted_on(
    db_session, restaurant, vector_db, embedding_provider
):
    llm = ScriptedLLMProvider([], default="SHOULD_NOT_BE_CALLED")
    stt = ScriptedSTTProvider([("Fiyopas.", 0.42)])
    session, sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()

    # Nothing was classified, retrieved against, or answered.
    assert llm.calls == []
    # But the caller is asked again rather than met with silence.
    assert len(sender.sent) >= 1
    assert session.context.history[-1].role == "assistant"
    assert session.context.history[-1].content.rstrip().endswith("?")


async def test_a_confident_transcript_still_goes_through(
    db_session, restaurant, vector_db, embedding_provider
):
    """The guard must not start rejecting ordinary speech — real short
    replies on a phone line score around 0.5-0.6."""
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
        ]
    )
    stt = ScriptedSTTProvider([("What time do you close tonight?", 0.58)])
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    await session._process_utterance()

    assert llm.calls  # it was actually processed
    assert session.final_outcome == CallOutcomeEnum.FAQ_ANSWERED


async def test_repeated_unintelligible_audio_hands_over_to_a_person(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    A bad line or an accent this model can't follow shouldn't loop
    forever. Three tries is a fair attempt; a fourth is where the caller
    gives up on the whole system rather than on the connection.
    """
    llm = ScriptedLLMProvider([], default="SHOULD_NOT_BE_CALLED")
    stt = ScriptedSTTProvider([("Fiyopas.", 0.42), ("free of us", 0.41), ("mmhm", 0.30)])
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    for _ in range(3):
        await session._process_utterance()

    assert session.should_close is True
    assert session.final_outcome == CallOutcomeEnum.HUMAN_ESCALATION
    assert session.context.state == ConversationState.TRANSFER_TO_HUMAN


async def test_one_bad_turn_does_not_count_against_a_later_one(
    db_session, restaurant, vector_db, embedding_provider
):
    """The counter is for a run of failures, not a tally across the call
    — a single crackle early on must not push a later one to a transfer."""
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
        ]
    )
    stt = ScriptedSTTProvider(
        [("Fiyopas.", 0.42), ("What time do you close tonight?", 0.9), ("blorp", 0.30)]
    )
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm, stt
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    for _ in range(3):
        await session._process_utterance()

    assert session.should_close is False
    assert session._unheard_count == 1


# ----------------------------------------------------------------------
# Barge-in
# ----------------------------------------------------------------------


def _payload(amplitude: int, samples: int = 160) -> str:
    """One 20ms Twilio media payload at the given amplitude."""
    from app.audio.codec import pcm16_to_mulaw

    pcm = np.full(samples, amplitude, dtype=np.int16)
    return base64.b64encode(pcm16_to_mulaw(pcm)).decode("ascii")


class _ClearRecorder:
    def __init__(self):
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1


async def _speaking_session(db_session, restaurant, vector_db, embedding_provider, stt=None):
    llm = ScriptedLLMProvider([], default="FAQ")
    call = await call_service.create_call(
        db_session, restaurant.id, "CA_barge", "+15551234567", restaurant.phone_number
    )
    sender = _RecordingSender()
    clearer = _ClearRecorder()
    session = CallSession(
        db_session, call, restaurant,
        stt or ScriptedSTTProvider([]), FakeTTSProvider(), llm,
        embedding_provider, vector_db, sender, None, clearer,
    )
    import time

    session._speaking_until = time.monotonic() + 60  # mid-reply
    return session, sender, clearer


async def test_talking_over_the_assistant_stops_it(
    db_session, restaurant, vector_db, embedding_provider
):
    session, _sender, clearer = await _speaking_session(
        db_session, restaurant, vector_db, embedding_provider
    )

    for _ in range(20):  # 400ms of speech, over the 300ms bar
        await session.handle_media(_payload(6000))

    assert clearer.calls == 1, "Twilio must be told to drop the buffered reply"
    assert session._interrupted is True
    assert session._is_speaking() is False  # listening again immediately


async def test_the_interrupted_words_are_kept_for_transcription(
    db_session, restaurant, vector_db, embedding_provider
):
    """The frames that proved someone was talking are the start of what
    they said — they belong to the utterance, not to the detector."""
    session, _sender, _clearer = await _speaking_session(
        db_session, restaurant, vector_db, embedding_provider
    )

    for _ in range(20):
        await session.handle_media(_payload(6000))

    assert len(session.turn_detector.pop_utterance()) > 0


async def test_line_noise_does_not_interrupt_the_assistant(
    db_session, restaurant, vector_db, embedding_provider
):
    """A false interruption is a worse call than no barge-in at all."""
    session, _sender, clearer = await _speaking_session(
        db_session, restaurant, vector_db, embedding_provider
    )

    for _ in range(200):  # four seconds of quiet line
        await session.handle_media(_payload(150))

    assert clearer.calls == 0
    assert session._interrupted is False
    assert session._is_speaking() is True


async def test_barge_in_can_be_turned_off(
    db_session, restaurant, vector_db, embedding_provider, monkeypatch
):
    """A line whose audio causes false interruptions needs an off switch
    that doesn't require a code change."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "FEATURE_BARGE_IN", False)
    session, _sender, clearer = await _speaking_session(
        db_session, restaurant, vector_db, embedding_provider
    )

    for _ in range(40):
        await session.handle_media(_payload(6000))

    assert clearer.calls == 0
    assert session._is_speaking() is True


async def test_speaking_stops_at_the_next_sentence_once_interrupted(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    Replies are synthesized and sent a sentence at a time, so an
    interruption must stop the ones not yet sent — and must not pay to
    synthesize them either.
    """

    class _InterruptingTTS(FakeTTSProvider):
        def __init__(self, session_holder):
            super().__init__()
            self.holder = session_holder
            self.synthesized: list[str] = []

        async def synthesize(self, text: str):
            self.synthesized.append(text)
            # The caller starts talking while the first sentence plays.
            self.holder[0]._interrupted = True
            return await super().synthesize(text)

    holder: list = [None]
    llm = ScriptedLLMProvider([], default="FAQ")
    call = await call_service.create_call(
        db_session, restaurant.id, "CA_cut", "+15551234567", restaurant.phone_number
    )
    sender = _RecordingSender()
    tts = _InterruptingTTS(holder)
    session = CallSession(
        db_session, call, restaurant, ScriptedSTTProvider([]), tts, llm,
        embedding_provider, vector_db, sender, None, _ClearRecorder(),
    )
    holder[0] = session

    await session._speak(
        "Here is the first sentence. Here is the second one. And here is a third."
    )

    assert len(tts.synthesized) == 1, "must not synthesize what nobody will hear"
    assert len(sender.sent) == 0, "the interrupted sentence is not sent either"


async def test_a_turn_does_not_block_the_audio_loop(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    handle_media must return without awaiting the turn. Twilio delivers a
    frame every 20ms down the same socket, so a handler that waits for
    the whole turn reads no audio while the assistant speaks — which is
    what made barge-in impossible.
    """
    stt = ScriptedSTTProvider([("What time do you close tonight?", 0.9)])
    session, _sender, _clearer = await _speaking_session(
        db_session, restaurant, vector_db, embedding_provider, stt
    )
    session._speaking_until = 0.0  # idle, listening

    # Speech, then enough silence to end the turn.
    for _ in range(20):
        await session.handle_media(_payload(6000))
    for _ in range(40):
        await session.handle_media(_payload(0))

    assert session._turn_in_flight(), "the turn should still be running in the background"
    await session._turn_task


# ----------------------------------------------------------------------
# The caller hanging up mid-reply
#
# A real call ended with websockets.exceptions.ConnectionClosedOK
# escaping as an unhandled ERROR with a full stack trace. Hanging up
# mid-sentence is how most calls end — reporting it as a fault buries
# the failures that are real.
# ----------------------------------------------------------------------


class _HangingUpSender:
    """The caller is already gone by the time we try to send."""

    def __init__(self):
        self.sent: list[bytes] = []

    async def __call__(self, mulaw_bytes: bytes) -> None:
        from app.voice.session import CallDisconnected

        raise CallDisconnected()


async def test_a_hangup_mid_reply_ends_the_call_without_an_error(
    db_session, restaurant, vector_db, embedding_provider, caplog
):
    import logging

    from app.voice.session import CallDisconnected

    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
        ]
    )
    stt = ScriptedSTTProvider([("What time do you close tonight?", 0.9)])
    call = await call_service.create_call(
        db_session, restaurant.id, "CA_hangup", "+15551234567", restaurant.phone_number
    )
    sender = _HangingUpSender()
    session = CallSession(
        db_session, call, restaurant, stt, FakeTTSProvider(), llm,
        embedding_provider, vector_db, sender,
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    with caplog.at_level(logging.INFO):
        await session._run_turn()

    # The call winds down; nothing is logged as an error.
    assert session.should_close is True
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("hung up" in r.message.lower() for r in caplog.records)

    # And _speak really does propagate it rather than swallowing it.
    session2 = CallSession(
        db_session, call, restaurant, stt, FakeTTSProvider(), llm,
        embedding_provider, vector_db, _HangingUpSender(),
    )
    import pytest

    with pytest.raises(CallDisconnected):
        await session2._speak("One sentence here. And a second one. And a third one too.")


async def test_a_genuine_turn_failure_is_still_reported(
    db_session, restaurant, vector_db, embedding_provider, caplog
):
    """Treating a hangup as routine must not silence real bugs."""
    import logging

    class _BrokenSTT(ScriptedSTTProvider):
        async def transcribe(self, audio, vocabulary=None):
            raise ValueError("something is genuinely wrong")

    llm = ScriptedLLMProvider([], default="FAQ")
    call = await call_service.create_call(
        db_session, restaurant.id, "CA_broken", "+15551234567", restaurant.phone_number
    )
    session = CallSession(
        db_session, call, restaurant, _BrokenSTT([]), FakeTTSProvider(), llm,
        embedding_provider, vector_db, _RecordingSender(),
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()

    with caplog.at_level(logging.INFO):
        await session._run_turn()

    assert [r for r in caplog.records if r.levelno >= logging.ERROR]
    # The line stays open — one bad turn is not a reason to hang up on them.
    assert session.should_close is False
