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
    async def synthesize(self, text: str, language: str = "en") -> tuple[bytes, int]:
        """
        Synthesize text to speech audio.

        Args:
            text: Text to convert to speech
            language: Language code (e.g., "en", "es")

        Returns:
            (audio_bytes, sample_rate) — audio_bytes is raw PCM16 mono
            (no WAV/container header), at the provider's native sample
            rate. A single well-defined format rather than "WAV, PCM,
            etc." — callers that need a different rate (e.g. 8kHz for
            Twilio) resample explicitly using the returned sample_rate,
            rather than guessing it.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is healthy."""
        pass
