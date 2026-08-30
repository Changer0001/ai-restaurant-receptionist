"""
Turn-Taking (Silence-Based Voice Activity Detection)

A minimal energy-threshold detector: once speech is detected, a
sustained run of low-energy audio signals "the caller has stopped
talking" and the buffered utterance should be transcribed.

This is deliberately not a trained VAD model (e.g. Silero VAD,
WebRTC VAD) — those give materially better accuracy in noisy
environments, but add a binary/model dependency this MVP doesn't need
yet for typical phone-line audio (which is already band-limited and
fairly clean). A real VAD model is a reasonable upgrade path; this
detector is documented as the simpler thing that works, not a
placeholder pretending to be more than it is.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class TurnDetectorConfig:
    sample_rate: int = 8000
    frame_ms: int = 20
    # RMS energy threshold (PCM16 scale) above which a frame counts as
    # speech. Phone-line background noise floor is typically well under
    # this; a caller's voice is well over it.
    energy_threshold: float = 400.0
    # How much continuous silence (ms) after speech has been heard
    # before the utterance is considered complete.
    silence_hangover_ms: int = 700
    # Safety cap: transcribe even without silence after this much
    # continuous speech, so a caller who never pauses doesn't leave the
    # engine waiting forever.
    max_utterance_ms: int = 15000


class TurnDetector:
    """
    Stateful, one instance per call. Feed it PCM16 frames; it reports
    when an utterance is ready to transcribe.
    """

    def __init__(self, config: TurnDetectorConfig | None = None):
        self.config = config or TurnDetectorConfig()
        self._buffer: list[np.ndarray] = []
        self._heard_speech = False
        self._silence_ms: float = 0.0
        self._speech_ms: float = 0.0

    def reset(self) -> None:
        self._buffer = []
        self._heard_speech = False
        self._silence_ms = 0.0
        self._speech_ms = 0.0

    def add_frame(self, frame: np.ndarray) -> bool:
        """
        Feed one frame of PCM16 audio. Returns True if an utterance is
        now complete and ready for `pop_utterance()`.
        """
        frame_ms = len(frame) / self.config.sample_rate * 1000
        energy = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2))) if len(frame) else 0.0
        is_speech = energy >= self.config.energy_threshold

        if is_speech:
            self._buffer.append(frame)
            self._heard_speech = True
            self._silence_ms = 0.0
            self._speech_ms += frame_ms
        elif self._heard_speech:
            # Keep buffering brief silence — it's part of natural speech
            # (pauses between words), not a signal to cut the utterance.
            self._buffer.append(frame)
            self._silence_ms += frame_ms
            self._speech_ms += frame_ms

        if not self._heard_speech:
            return False

        return self._silence_ms >= self.config.silence_hangover_ms or self._speech_ms >= self.config.max_utterance_ms

    def pop_utterance(self) -> np.ndarray:
        """Return the buffered utterance audio and reset for the next one."""
        audio: np.ndarray = (
            np.concatenate(self._buffer) if self._buffer else np.array([], dtype=np.int16)
        )
        self.reset()
        return audio
