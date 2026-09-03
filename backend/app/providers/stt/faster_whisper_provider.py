"""
Faster-Whisper STT Provider

Local speech-to-text using Faster-Whisper (OpenAI Whisper optimized)
https://github.com/guillaumekln/faster-whisper
"""

import asyncio
import io
import logging
import math
from typing import Optional, Tuple

from faster_whisper import WhisperModel

from app.core.config import settings
from app.providers.stt.base import STTProvider

logger = logging.getLogger(__name__)


class FasterWhisperSTTProvider(STTProvider):
    """
    Speech-to-text using Faster-Whisper for local inference.

    Supports GPU acceleration and quantized models.
    """

    def __init__(
        self,
        model_size: str = settings.WHISPER_MODEL,
        device: str = settings.WHISPER_DEVICE,
        compute_type: str = settings.WHISPER_COMPUTE_TYPE,
        initial_prompt: str = settings.STT_INITIAL_PROMPT,
        beam_size: int = settings.WHISPER_BEAM_SIZE,
        cpu_threads: int = settings.WHISPER_CPU_THREADS,
    ):
        """
        Initialize Faster-Whisper provider.

        Args:
            model_size: Model size (tiny, base, small, medium, large, large-v3)
            device: Compute device (cuda, cpu)
            compute_type: Quantization (float16, int8, float32). Empty
                picks by device — see WHISPER_COMPUTE_TYPE in config.
            initial_prompt: Vocabulary hint biasing the decoder toward
                this restaurant's dish names — see STT_INITIAL_PROMPT.
            beam_size: Decode beam width; 1 is greedy and much faster.
            cpu_threads: 0 lets CTranslate2 pick.
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.initial_prompt = initial_prompt
        self.beam_size = beam_size
        self.cpu_threads = cpu_threads
        self.model: WhisperModel | None = None

    async def _load_model(self) -> WhisperModel:
        """Lazy load the Whisper model.

        Returns the loaded model directly (rather than callers reading
        self.model afterward) so its type is `WhisperModel`, not
        `WhisperModel | None` — static analysis can't otherwise tell that
        calling this method guarantees self.model is now set.
        """
        if self.model is None:
            compute_type = self.compute_type or ("float16" if self.device == "cuda" else "int8")
            logger.info(
                f"Loading Whisper model: {self.model_size} on {self.device} ({compute_type})"
            )
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=compute_type,
                cpu_threads=self.cpu_threads,
            )
        return self.model

    async def transcribe(
        self, audio: bytes, vocabulary: Optional[str] = None
    ) -> Tuple[str, float]:
        """Transcribe audio to text. See STTProvider.transcribe."""
        model = await self._load_model()
        # WhisperModel.transcribe() is synchronous, and the actual model
        # inference happens lazily as its returned generator is iterated
        # — not when transcribe() is first called. Both the call and the
        # iteration must run off the event loop, so the whole thing goes
        # through one asyncio.to_thread() rather than just wrapping the
        # initial call.
        return await asyncio.to_thread(
            self._transcribe_sync, model, audio, vocabulary or self.initial_prompt
        )

    def _transcribe_sync(
        self, model: WhisperModel, audio: bytes, vocabulary: str
    ) -> Tuple[str, float]:
        try:
            audio_file = io.BytesIO(audio)

            segments, _info = model.transcribe(
                audio_file,
                language="en",
                # Biases the decoder toward this restaurant's vocabulary.
                # Telephone audio is 8kHz and callers say dish names that
                # aren't everyday English, which is exactly the case
                # Whisper gets wrong without a hint: real calls produced
                # "hollow options" for "halal options" and "chicken show,
                # Emma" for "chicken shawarma".
                initial_prompt=vocabulary or None,
                # False, despite the name sounding helpful: each caller
                # utterance is transcribed as its own independent audio
                # buffer, so there is no genuine prior context to carry —
                # what this actually does here is let a mistake in one
                # segment condition the next one, which is how Whisper
                # gets into repetition loops on short, noisy phone audio.
                condition_on_previous_text=False,
                # Drops non-speech audio before decoding. Without it,
                # silence and line noise get "transcribed" as filler —
                # a real call produced ".  .  .  ." from a pause, which
                # then went through the whole intent/escalation pipeline
                # as if the caller had said something.
                vad_filter=True,
                # Greedy by default — see WHISPER_BEAM_SIZE. On a phone
                # call the decode is a real share of a turn the caller
                # spends in silence.
                beam_size=self.beam_size,
                # Nothing downstream uses per-word timing, and asking for
                # it makes the decoder do extra work on every utterance.
                without_timestamps=True,
            )

            text_parts = []
            confidences = []

            for segment in segments:
                text_parts.append(segment.text)
                # Segment has no .confidence attribute — avg_logprob is
                # the average per-token log-probability faster-whisper
                # actually exposes. exp() converts it back to a
                # roughly-[0,1]-scaled confidence proxy (a standard
                # approach for Whisper-family models, not an exact
                # calibrated probability).
                confidences.append(math.exp(segment.avg_logprob))

            transcribed_text = " ".join(text_parts).strip()
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            logger.debug(
                f"Transcribed: {transcribed_text[:100]}... (confidence: {avg_confidence:.2f})"
            )

            return transcribed_text, avg_confidence
        except Exception as e:
            logger.error(f"Whisper transcription error: {e}")
            raise

    async def health_check(self) -> bool:
        """Check if Whisper is ready."""
        try:
            await self._load_model()
            return self.model is not None
        except Exception as e:
            logger.error(f"Whisper health check failed: {e}")
            return False
