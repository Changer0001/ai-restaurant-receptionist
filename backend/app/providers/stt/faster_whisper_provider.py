"""
Faster-Whisper STT Provider

Local speech-to-text using Faster-Whisper (OpenAI Whisper optimized)
https://github.com/guillaumekln/faster-whisper
"""

import asyncio
import io
import logging
import math
from typing import Tuple

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
    ):
        """
        Initialize Faster-Whisper provider.

        Args:
            model_size: Model size (tiny, base, small, medium, large, large-v3)
            device: Compute device (cuda, cpu)
        """
        self.model_size = model_size
        self.device = device
        self.model: WhisperModel | None = None

    async def _load_model(self) -> WhisperModel:
        """Lazy load the Whisper model.

        Returns the loaded model directly (rather than callers reading
        self.model afterward) so its type is `WhisperModel`, not
        `WhisperModel | None` — static analysis can't otherwise tell that
        calling this method guarantees self.model is now set.
        """
        if self.model is None:
            logger.info(f"Loading Whisper model: {self.model_size} on {self.device}")
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type="float16" if self.device == "cuda" else "float32",
            )
        return self.model

    async def transcribe(self, audio: bytes) -> Tuple[str, float]:
        """Transcribe audio to text."""
        model = await self._load_model()
        # WhisperModel.transcribe() is synchronous, and the actual model
        # inference happens lazily as its returned generator is iterated
        # — not when transcribe() is first called. Both the call and the
        # iteration must run off the event loop, so the whole thing goes
        # through one asyncio.to_thread() rather than just wrapping the
        # initial call.
        return await asyncio.to_thread(self._transcribe_sync, model, audio)

    def _transcribe_sync(self, model: WhisperModel, audio: bytes) -> Tuple[str, float]:
        try:
            audio_file = io.BytesIO(audio)

            segments, _info = model.transcribe(
                audio_file,
                language="en",
                condition_on_previous_text=True,
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
