"""
Kokoro TTS Provider

Local speech synthesis via Kokoro (hexgrad/Kokoro-82M), an 82M-parameter
open-weight TTS model. Primary TTS provider per the project spec; Piper
is the CPU-friendly fallback (see piper_provider.py).
"""

import asyncio
import logging

import numpy as np

from app.audio.codec import float32_to_pcm16
from app.core.config import settings
from app.providers.tts.base import TTSProvider

logger = logging.getLogger(__name__)

# Kokoro's vocoder outputs 24kHz mono audio — fixed by the model
# architecture, not configurable.
NATIVE_SAMPLE_RATE = 24000


class KokoroTTSProvider(TTSProvider):
    """
    Kokoro-based TTS provider for local, GPU-accelerated speech synthesis.

    The `kokoro` package's KPipeline does its own model inference
    synchronously (it's a torch model, not an async client) — every
    synthesize() call runs it via asyncio.to_thread so it can't block
    the event loop, per this project's "no blocking CPU-heavy operations
    inside FastAPI request handlers" rule.
    """

    def __init__(
        self,
        voice: str = settings.KOKORO_VOICE,
        lang_code: str = settings.KOKORO_LANG_CODE,
        device: str = settings.KOKORO_DEVICE,
        speed: float = settings.KOKORO_SPEED,
    ):
        self.voice = voice
        self.speed = speed
        self.lang_code = lang_code
        # KPipeline's device param wants 'cuda'/'cpu'/None (auto-detect);
        # this project's KOKORO_DEVICE setting uses 'cuda'/'cpu' directly.
        self.device = device
        self._pipeline = None  # lazy-loaded — see _load_pipeline()

    def _load_pipeline(self):
        if self._pipeline is None:
            from kokoro import KPipeline  # deferred: heavy import (torch, transformers)

            logger.info(
                f"Loading Kokoro pipeline: lang_code={self.lang_code}, device={self.device}"
            )
            self._pipeline = KPipeline(lang_code=self.lang_code, device=self.device)
        return self._pipeline

    async def synthesize(self, text: str, language: str = "en") -> tuple[bytes, int]:
        pcm16 = await asyncio.to_thread(self._synthesize_sync, text)
        return pcm16.tobytes(), NATIVE_SAMPLE_RATE

    def _synthesize_sync(self, text: str) -> np.ndarray:
        pipeline = self._load_pipeline()
        chunks = []
        for result in pipeline(text, voice=self.voice, speed=self.speed):
            if result.audio is not None:
                chunks.append(result.audio.detach().cpu().numpy())

        if not chunks:
            logger.warning(f"Kokoro produced no audio for text: {text[:80]!r}")
            return np.array([], dtype=np.int16)

        audio = np.concatenate(chunks).astype(np.float32)
        return float32_to_pcm16(audio)

    async def health_check(self) -> bool:
        try:
            audio_bytes, _ = await self.synthesize("test")
            return len(audio_bytes) > 0
        except Exception as e:
            logger.error(f"Kokoro health check failed: {e}")
            return False
