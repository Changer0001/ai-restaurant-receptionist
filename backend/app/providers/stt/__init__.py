"""Speech-to-Text Provider Package"""

from app.providers.stt.base import STTProvider
from app.providers.stt.faster_whisper_provider import FasterWhisperSTTProvider

__all__ = ["STTProvider", "FasterWhisperSTTProvider"]
