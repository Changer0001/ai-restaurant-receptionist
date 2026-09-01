"""
Call Session

Owns one live phone call end-to-end: buffering caller audio, deciding
when they've finished a turn, running STT -> conversation engine -> TTS,
and streaming the response back. One instance per call, created when the
Media Streams WebSocket connects and discarded when it disconnects.

Turn-taking is strictly alternating — the caller speaks, the engine
responds fully, then the caller speaks again. There is no barge-in
(interrupting the AI mid-response): while audio is being played back to
the caller, incoming audio is intentionally ignored rather than treated
as a new utterance, using an estimated "speaking until" timestamp
computed from the outgoing audio's own duration. Twilio's Media Streams
`mark` event is the protocol-native way to get an exact "playback
actually finished" signal from Twilio itself rather than estimating it;
using the estimate is a deliberate, simpler scope-down for this MVP —
see docs/roadmap.md.
"""

import base64
import logging
import re
import time
from typing import Awaitable, Callable

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.audio.codec import mulaw_to_pcm16, pcm16_to_mulaw, pcm16_to_wav_bytes, resample_linear
from app.audio.vad import TurnDetector
from app.conversation.engine import ConversationEngine, TurnResult
from app.conversation.state import ConversationContext, ConversationState
from app.core.config import settings
from app.core.metrics import active_calls
from app.db.models import Call, CallOutcomeEnum, Restaurant
from app.providers.embedding.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.providers.stt.base import STTProvider
from app.providers.tts.base import TTSProvider
from app.rag.vector_db import VectorDB
from app.services import call_service, caller_service
from app.voice.speech_text import to_spoken

logger = logging.getLogger(__name__)

_TWILIO_SAMPLE_RATE = 8000
_WHISPER_SAMPLE_RATE = 16000
# Small buffer added on top of the outgoing audio's own playback
# duration, covering Twilio's own send/jitter buffer latency so we don't
# start listening a beat before the caller has actually heard us finish.
_PLAYBACK_TAIL_BUFFER_S = 0.2

# Spoken immediately after transcribing the caller's utterance, before
# the conversation engine runs — but only when settings.SPEAK_PROCESSING_FILLER
# is True (local Ollama on CPU; see its own docstring in app/core/config.py).
# Without it there, the caller hears total silence for the 10-30+
# seconds local inference can take, which reads exactly like a dropped
# call — observed live to cause the caller (or their carrier's own
# silence detection) to hang up before the real answer is ready. A fast
# hosted provider doesn't need this, and speaking it unconditionally
# would just add a stilted, robotic beat before a reply that was going
# to arrive quickly anyway.
# Deliberately not added to context.history or the DB transcript (see
# _process_utterance) — it's a UX filler, not part of the actual
# conversational exchange the engine or a human reviewer should see.
_PROCESSING_FILLER = "One moment, let me check on that for you."

SendAudio = Callable[[bytes], Awaitable[None]]


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
# Below this, a fragment isn't worth its own synthesis pass — the
# per-call overhead and the audible seam cost more than the head start
# it buys. "Yes." merges into the sentence after it.
_MIN_CHUNK_CHARS = 25


def _split_into_speakable_chunks(text: str) -> list[str]:
    """
    Split a reply into sentence-sized pieces for streaming synthesis.

    Short leading fragments are merged forward so the first chunk is a
    real phrase rather than a single word — the point is to start
    speaking sooner, not to chop the delivery into pieces.
    """
    chunks: list[str] = []
    for sentence in _SENTENCE_BOUNDARY.split(text.strip()):
        if not sentence:
            continue
        if chunks and len(chunks[-1]) < _MIN_CHUNK_CHARS:
            chunks[-1] = f"{chunks[-1]} {sentence}"
        else:
            chunks.append(sentence)
    return chunks


def _is_prompt_echo(text: str) -> bool:
    """
    Whether Whisper transcribed its own vocabulary hint instead of the
    caller.

    STT_INITIAL_PROMPT is fed to Whisper as preceding context to bias it
    toward this restaurant's dish names, and Whisper's job is to continue
    the text it was given — so on short or unclear audio it sometimes
    continues the prompt rather than transcribing the caller. A real call
    logged the caller as saying "We serve halal Syrian and Mediterranean
    food." That went into the transcript, the conversation history, and
    the LLM's view of what the caller wanted.

    Detected by word overlap rather than an exact match, since the echo
    comes back reworded and repunctuated.
    """
    prompt_words = {word.strip(",.").lower() for word in settings.STT_INITIAL_PROMPT.split()}
    if not prompt_words:
        return False

    spoken = [word.strip(",.!?").lower() for word in text.split() if word.strip(",.!?")]
    if not spoken:
        return False

    # A caller can legitimately say two or three of these words in a row
    # ("do you have chicken shawarma") — what marks an echo is an
    # utterance made almost entirely of them.
    overlap = sum(1 for word in spoken if word in prompt_words) / len(spoken)
    return overlap >= 0.8 and len(spoken) >= 4


def _has_speech(text: str) -> bool:
    """
    Whether a transcript contains anything a caller actually said.

    Whisper transcribes silence and line noise as bare punctuation —
    a real call produced ".  .  .  ." from a pause, which then ran the
    whole intent/escalation pipeline and had the AI offer to transfer
    the caller because it "couldn't understand" a sound they never made.
    An empty string isn't the only shape "nothing was said" takes.
    """
    return any(char.isalnum() for char in text)


class CallSession:
    def __init__(
        self,
        db: AsyncSession,
        call: Call,
        restaurant: Restaurant,
        stt: STTProvider,
        tts: TTSProvider,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        vector_db: VectorDB,
        send_audio: SendAudio,
    ):
        self.db = db
        self.call = call
        self.restaurant = restaurant
        self.stt = stt
        self.tts = tts
        self.send_audio = send_audio

        self.engine = ConversationEngine(llm, embedder, vector_db, db, restaurant)
        self.context = ConversationContext(restaurant_id=restaurant.id)
        # Populated in start() from past calls and reservations for
        # this caller's number; empty for an unrecognized caller.
        self.caller_profile = caller_service.CallerProfile()
        self.turn_detector = TurnDetector()

        self.final_outcome = CallOutcomeEnum.UNKNOWN
        self.should_close = False  # set True once a transfer is needed
        self._speaking_until = 0.0  # monotonic timestamp
        # Tracks whether this session is the one that incremented
        # active_calls, so end() only ever decrements a gauge this same
        # instance actually raised — see active_calls' own docstring.
        self._counted_active = False

    async def start(self) -> None:
        """Called once the Media Stream is connected — plays the greeting."""
        active_calls.inc()
        self._counted_active = True

        default_greeting = self.restaurant.ai_greeting or (
            f"Thank you for calling {self.restaurant.name}. How can I help you today?"
        )
        # Recognizing a regular is the cheapest warmth available on a
        # phone line, and the data is already in the database. Wrapped
        # in try/except deliberately: a caller-memory lookup failing
        # must never stop a call from being answered — the worst
        # acceptable outcome is a caller who isn't greeted by name.
        # Not inside the try below: the number they're calling from comes
        # from the phone system, not the database lookup, and it's what
        # spares a caller being asked to read out a number we already
        # have.
        self.context.caller_number = self.call.caller_number

        try:
            self.caller_profile = await caller_service.get_caller_profile(
                self.db, self.restaurant.id, self.call.caller_number
            )
            greeting = caller_service.greeting_for(
                self.caller_profile, self.restaurant.name, default_greeting
            )
            self.context.caller_name = self.caller_profile.name
            if self.caller_profile.upcoming_reservation is not None:
                self.context.known_reservation = caller_service.describe_reservation(
                    self.caller_profile.upcoming_reservation
                )
        except Exception as e:
            logger.warning(f"Caller lookup failed, greeting as a new caller: {e}")
            greeting = default_greeting
        # Both records matter here: the DB transcript is the persisted
        # call record; context.history is what the engine's own prompts
        # (intent classification, escalation review) actually read —
        # without this, the model would have no idea a greeting was ever
        # spoken.
        await call_service.append_transcript_turn(self.db, self.call, "assistant", greeting)
        self.context.add_turn("assistant", greeting)
        await self._speak(greeting)

    async def handle_media(self, payload_b64: str) -> None:
        """Handle one inbound `media` event's base64 μ-law payload."""
        if time.monotonic() < self._speaking_until:
            return  # still playing our own response — no barge-in support

        mulaw_bytes = base64.b64decode(payload_b64)
        frame = mulaw_to_pcm16(mulaw_bytes)

        if self.turn_detector.add_frame(frame):
            await self._process_utterance()

    async def _process_utterance(self) -> None:
        pcm_8k = self.turn_detector.pop_utterance()
        if len(pcm_8k) == 0:
            return

        pcm_16k = resample_linear(pcm_8k, _TWILIO_SAMPLE_RATE, _WHISPER_SAMPLE_RATE)
        wav_bytes = pcm16_to_wav_bytes(pcm_16k, _WHISPER_SAMPLE_RATE)

        # Per-stage timing. The caller hears silence for the whole of
        # this method, and "the AI is slow" is unactionable until you
        # know which stage owns the seconds — the answer is rarely the
        # one people assume (moving the LLM to a hosted API doesn't help
        # if STT and TTS are the local CPU work that dominates).
        stage_started = time.perf_counter()

        text, confidence = await self.stt.transcribe(wav_bytes)
        stt_seconds = time.perf_counter() - stage_started
        text = text.strip()
        # TEMPORARY debug logging — remove once it's confirmed FAQ
        # questions (menu/parking/location) aren't being misrouted.
        logger.warning(f"DEBUG STT transcript: text={text!r} confidence={confidence!r}")
        if not _has_speech(text):
            return  # nothing intelligible — keep listening rather than confuse the engine with silence

        if _is_prompt_echo(text):
            logger.warning(f"Discarding STT echo of the vocabulary prompt: {text!r}")
            return

        await call_service.append_transcript_turn(self.db, self.call, "caller", text, confidence)

        if settings.SPEAK_PROCESSING_FILLER:
            await self._speak(_PROCESSING_FILLER)

        engine_started = time.perf_counter()
        result = await self.engine.handle_turn(self.context, text, call_sid=self.call.call_sid)
        engine_seconds = time.perf_counter() - engine_started

        await call_service.append_transcript_turn(
            self.db, self.call, "assistant", result.response_text
        )
        self._update_outcome(result)

        speak_started = time.perf_counter()
        await self._speak(result.response_text)
        tts_seconds = time.perf_counter() - speak_started

        logger.info(
            "Turn timing: stt=%.2fs engine=%.2fs tts=%.2fs total=%.2fs "
            "(caller waited total + ~%dms of end-of-speech detection)",
            stt_seconds,
            engine_seconds,
            tts_seconds,
            time.perf_counter() - stage_started,
            self.turn_detector.config.silence_hangover_ms,
        )

        if result.should_transfer:
            self.should_close = True

    # Transfer reasons that are a routine handoff to what the restaurant
    # itself handles (an order, a reservation with FEATURE_RESERVATION_COLLECTION
    # off) — CALL_TRANSFERRED, not HUMAN_ESCALATION, which implies
    # something went wrong (frustration, repeated misunderstanding).
    _ROUTINE_TRANSFER_REASONS = frozenset({"order_request", "reservation_request"})

    def _update_outcome(self, result: TurnResult) -> None:
        if result.reservation is not None:
            self.final_outcome = CallOutcomeEnum.RESERVATION_CREATED
        elif result.should_transfer:
            self.final_outcome = (
                CallOutcomeEnum.CALL_TRANSFERRED
                if result.transfer_reason in self._ROUTINE_TRANSFER_REASONS
                else CallOutcomeEnum.HUMAN_ESCALATION
            )
        elif self.final_outcome == CallOutcomeEnum.UNKNOWN:
            self.final_outcome = CallOutcomeEnum.FAQ_ANSWERED

    async def _speak(self, text: str) -> None:
        """
        Synthesize and send speech one sentence at a time.

        Kokoro on CPU takes roughly as long as the reply is long —
        measured at 1.6s for "Okay" and 6.2s for a two-sentence answer.
        Synthesizing the whole reply before sending any of it means the
        caller hears nothing for that entire time, on top of STT and the
        LLM. Sending each sentence as it finishes gets the first words
        into their ear while the rest is still being generated, which
        cuts the silence to roughly the first sentence's synthesis.

        The trade is prosody: each sentence is synthesized without
        knowing the next, so the delivery is very slightly flatter
        across a boundary than one continuous pass would be. On a phone
        line that is far less noticeable than six seconds of dead air.
        """
        # Playback is back-to-back, so each chunk starts when the
        # previous one ends — unless synthesis fell behind playback, in
        # which case the next chunk starts when it actually arrives.
        # Tracking this properly keeps _speaking_until honest, which is
        # what stops the caller's own audio being processed as a new
        # utterance while the assistant is still talking.
        playback_ends_at = time.monotonic()

        # Rewrite into spoken form first — before splitting, since this
        # removes the decimal points in prices that would otherwise look
        # like sentence boundaries.
        for sentence in _split_into_speakable_chunks(to_spoken(text)):
            pcm_bytes, native_rate = await self.tts.synthesize(sentence)
            if not pcm_bytes:
                continue

            pcm_array = np.frombuffer(pcm_bytes, dtype=np.int16)
            pcm_8k = resample_linear(pcm_array, native_rate, _TWILIO_SAMPLE_RATE)
            mulaw_bytes = pcm16_to_mulaw(pcm_8k)

            # μ-law is exactly 1 byte per sample at the target rate, so
            # this is the actual playback duration, not an approximation.
            duration_s = len(mulaw_bytes) / _TWILIO_SAMPLE_RATE
            playback_ends_at = max(playback_ends_at, time.monotonic()) + duration_s
            self._speaking_until = playback_ends_at + _PLAYBACK_TAIL_BUFFER_S

            await self.send_audio(mulaw_bytes)

    async def end(self) -> None:
        """Called once the Media Stream disconnects — finalizes the Call record."""
        transcript_text = "\n".join(f"{t.role}: {t.content}" for t in self.context.history)

        outcome = self.final_outcome
        if outcome == CallOutcomeEnum.UNKNOWN:
            # UNKNOWN is a live-call placeholder, never a meaningful
            # terminal state — a call that ends without anything having
            # resolved is, by definition, an abandoned call.
            outcome = CallOutcomeEnum.CALL_ABANDONED

        await call_service.finalize_call(
            self.db,
            self.call,
            outcome,
            was_transferred=self.context.state == ConversationState.TRANSFER_TO_HUMAN,
            was_escalated=self.context.transfer_reason == "escalation",
            transcript_text=transcript_text or None,
        )

        if self._counted_active:
            active_calls.dec()
            self._counted_active = False
