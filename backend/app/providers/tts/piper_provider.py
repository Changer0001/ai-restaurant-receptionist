"""
Piper TTS Provider

Local speech synthesis via Piper (rhasspy/piper), an ONNX-based TTS
engine — the CPU-friendly fallback when Kokoro (the primary provider)
is unavailable or a GPU isn't free for TTS. Runs entirely on CPU at
reasonable speed for phone-call-length utterances.
"""

import asyncio
import logging
from pathlib import Path

from app.core.config import settings
from app.providers.tts.base import TTSProvider

logger = logging.getLogger(__name__)


class PiperTTSProvider(TTSProvider):
    """
    Piper-based TTS provider.

    Requires a downloaded voice model (.onnx + .onnx.json) — Piper
    itself is a Python/ONNX runtime library, not a model; voices must be
    fetched separately (see PIPER_VOICE_MODEL_PATH in .env.example).
    Piper's own synthesis call is synchronous (an ONNX Runtime session),
    so it runs via asyncio.to_thread like KokoroTTSProvider.
    """

    def __init__(self, model_path: str = settings.PIPER_VOICE_MODEL_PATH, use_cuda: bool = False):
        self.model_path = model_path
        self.use_cuda = use_cuda
        self._voice = None  # lazy-loaded — see _load_voice()

    def _load_voice(self):
        if self._voice is None:
            from piper import PiperVoice  # deferred: pulls in onnxruntime

            if not Path(self.model_path).is_file():
                raise FileNotFoundError(
                    f"Piper voice model not found at {self.model_path!r}. "
                    "Download one from https://github.com/rhasspy/piper/blob/master/VOICES.md "
                    "and set PIPER_VOICE_MODEL_PATH."
                )
            logger.info(f"Loading Piper voice: {self.model_path}")
            self._voice = PiperVoice.load(self.model_path, use_cuda=self.use_cuda)
        return self._voice

    async def synthesize(self, text: str, language: str = "en") -> tuple[bytes, int]:
        return await asyncio.to_thread(self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> tuple[bytes, int]:
        voice = self._load_voice()
        pcm_chunks = []
        sample_rate = voice.config.sample_rate

        for chunk in voice.synthesize(text):
            pcm_chunks.append(chunk.audio_int16_bytes)

        return b"".join(pcm_chunks), sample_rate

    async def health_check(self) -> bool:
        try:
            audio_bytes, _ = await self.synthesize("test")
            return len(audio_bytes) > 0
        except Exception as e:
            logger.error(f"Piper health check failed: {e}")
            return False
