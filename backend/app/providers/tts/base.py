"""
Base Text-to-Speech Provider

Abstract interface for TTS providers.
"""

from abc import ABC, abstractmethod


class TTSProvider(ABC):
    """
    Abstract base class for text-to-speech providers.
    """

    @abstractmethod
    async def synthesize(self, text: str, language: str = "en") -> bytes:
        """
        Synthesize text to speech audio.

        Args:
            text: Text to convert to speech
            language: Language code (e.g., "en", "es")

        Returns:
            Audio bytes (WAV, PCM, etc.)
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is healthy."""
        pass
