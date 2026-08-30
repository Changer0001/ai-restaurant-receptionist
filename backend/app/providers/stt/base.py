"""
Base Speech-to-Text Provider

Abstract interface for STT providers.
"""

from abc import ABC, abstractmethod
from typing import Tuple


class STTProvider(ABC):
    """
    Abstract base class for speech-to-text providers.
    """

    @abstractmethod
    async def transcribe(self, audio: bytes) -> Tuple[str, float]:
        """
        Transcribe audio to text.

        Args:
            audio: Audio bytes (WAV, MP3, etc.)

        Returns:
            Tuple of (transcribed_text, confidence_score)
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is healthy."""
        pass
