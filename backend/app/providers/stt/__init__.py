"""Speech-to-Text Provider Package"""

from typing import Optional

from app.providers.stt.base import STTProvider
from app.providers.stt.faster_whisper_provider import FasterWhisperSTTProvider

__all__ = ["STTProvider", "FasterWhisperSTTProvider", "get_stt_provider"]

_stt_provider: Optional[STTProvider] = None


async def get_stt_provider() -> STTProvider:
    """Get the (lazily-initialized, process-wide) STT provider.

    A FastAPI dependency — override with `app.dependency_overrides` in
    tests to avoid requiring a real Whisper model.
    """
    global _stt_provider
    if _stt_provider is None:
        _stt_provider = FasterWhisperSTTProvider()
    return _stt_provider
