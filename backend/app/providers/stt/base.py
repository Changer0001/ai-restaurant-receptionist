"""
Base Speech-to-Text Provider

Abstract interface for STT providers.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple


class STTProvider(ABC):
    """
    Abstract base class for speech-to-text providers.
    """

    @abstractmethod
    async def transcribe(
        self, audio: bytes, vocabulary: Optional[str] = None
    ) -> Tuple[str, float]:
        """
        Transcribe audio to text.

        Args:
            audio: Audio bytes (WAV, MP3, etc.)
            vocabulary: Words this particular caller is likely to say —
                one restaurant's dish names. Passed per call rather than
                set on the provider because a single process serves every
                restaurant, and one cuisine's vocabulary actively harms
                another's (biasing toward "shawarma" when the caller said
                "carbonara"). None falls back to the provider's default.

        Returns:
            Tuple of (transcribed_text, confidence_score)
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is healthy."""
        pass
