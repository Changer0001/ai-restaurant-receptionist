"""Text-to-Speech Provider Package"""

import logging
from typing import Optional

from app.core.config import settings
from app.providers.tts.base import TTSProvider

logger = logging.getLogger(__name__)

__all__ = ["TTSProvider", "get_tts_provider"]

_tts_provider: Optional[TTSProvider] = None


async def get_tts_provider() -> TTSProvider:
    """
    Get the (lazily-initialized, process-wide) TTS provider, selected by
    TTS_PROVIDER ("kokoro" or "piper"). A FastAPI dependency — override
    with `app.dependency_overrides` in tests.
    """
    global _tts_provider
    if _tts_provider is None:
        if settings.TTS_PROVIDER == "piper":
            from app.providers.tts.piper_provider import PiperTTSProvider

            _tts_provider = PiperTTSProvider()
        else:
            from app.providers.tts.kokoro_provider import KokoroTTSProvider

            _tts_provider = KokoroTTSProvider()
        logger.info(f"TTS provider initialized: {settings.TTS_PROVIDER}")
    return _tts_provider
