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
import time
from typing import Awaitable, Callable

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.audio.codec import mulaw_to_pcm16, pcm16_to_mulaw, pcm16_to_wav_bytes, resample_linear
from app.audio.vad import TurnDetector
from app.conversation.engine import ConversationEngine, TurnResult
from app.conversation.state import ConversationContext, ConversationState
from app.core.metrics import active_calls
from app.db.models import Call, CallOutcomeEnum, Restaurant
from app.providers.embedding.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.providers.stt.base import STTProvider
from app.providers.tts.base import TTSProvider
from app.rag.vector_db import VectorDB
from app.services import call_service

_TWILIO_SAMPLE_RATE = 8000
_WHISPER_SAMPLE_RATE = 16000
# Small buffer added on top of the outgoing audio's own playback
# duration, covering Twilio's own send/jitter buffer latency so we don't
# start listening a beat before the caller has actually heard us finish.
_PLAYBACK_TAIL_BUFFER_S = 0.2

# Spoken immediately after transcribing the caller's utterance, before
# the (potentially slow — CPU-only local inference can take 10-30+
# seconds per turn across escalation-check/intent/extraction/generation
# calls) conversation engine runs. Without this, the caller hears
# total silence for that whole window, which reads exactly like a
# dropped call — observed live to cause the caller (or their carrier's
# own silence detection) to hang up before the real answer is ready.
# Deliberately not added to context.history or the DB transcript (see
# _process_utterance) — it's a UX filler, not part of the actual
# conversational exchange the engine or a human reviewer should see.
_PROCESSING_FILLER = "One moment, let me check on that for you."

SendAudio = Callable[[bytes], Awaitable[None]]


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

        greeting = self.restaurant.ai_greeting or (
            f"Thank you for calling {self.restaurant.name}. How can I help you today?"
        )
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

        text, confidence = await self.stt.transcribe(wav_bytes)
        text = text.strip()
        if not text:
            return  # nothing intelligible — keep listening rather than confuse the engine with silence

        await call_service.append_transcript_turn(self.db, self.call, "caller", text, confidence)

        await self._speak(_PROCESSING_FILLER)

        result = await self.engine.handle_turn(self.context, text, call_sid=self.call.call_sid)

        await call_service.append_transcript_turn(
            self.db, self.call, "assistant", result.response_text
        )
        self._update_outcome(result)

        await self._speak(result.response_text)

        if result.should_transfer:
            self.should_close = True

    def _update_outcome(self, result: TurnResult) -> None:
        if result.reservation is not None:
            self.final_outcome = CallOutcomeEnum.RESERVATION_CREATED
        elif result.should_transfer:
            self.final_outcome = (
                CallOutcomeEnum.HUMAN_ESCALATION
                if result.transfer_reason != "order_request"
                else CallOutcomeEnum.CALL_TRANSFERRED
            )
        elif self.final_outcome == CallOutcomeEnum.UNKNOWN:
            self.final_outcome = CallOutcomeEnum.FAQ_ANSWERED

    async def _speak(self, text: str) -> None:
        pcm_bytes, native_rate = await self.tts.synthesize(text)
        if not pcm_bytes:
            return

        pcm_array = np.frombuffer(pcm_bytes, dtype=np.int16)
        pcm_8k = resample_linear(pcm_array, native_rate, _TWILIO_SAMPLE_RATE)
        mulaw_bytes = pcm16_to_mulaw(pcm_8k)

        # μ-law is exactly 1 byte per sample at the target rate, so this
        # is the actual playback duration, not an approximation of it.
        duration_s = len(mulaw_bytes) / _TWILIO_SAMPLE_RATE
        self._speaking_until = time.monotonic() + duration_s + _PLAYBACK_TAIL_BUFFER_S

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
