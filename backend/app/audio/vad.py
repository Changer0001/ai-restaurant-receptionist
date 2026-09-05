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
    #
    # This is dead time on every single turn, before any work starts.
    # 500ms still clears the natural pauses inside a sentence on a phone
    # line while taking a fifth of a second off each exchange. Push it
    # lower and the detector starts cutting people off mid-sentence,
    # which costs far more than it saves.
    silence_hangover_ms: int = 500
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


@dataclass
class BargeInConfig:
    sample_rate: int = 8000
    # Deliberately higher than TurnDetectorConfig.energy_threshold.
    # This runs while the assistant is talking, when the inbound leg can
    # carry acoustic echo of our own voice from a speakerphone or a
    # handset held loosely. Interrupting the assistant over its own echo
    # is worse than not interrupting at all, so the bar to cut it off is
    # higher than the bar to hear someone in silence.
    energy_threshold: float = 900.0
    # Sustained speech required before it counts as an interruption.
    # A cough, a door, a burst of line noise are all short; someone
    # actually starting to talk is not. This is the single most important
    # number here — too low and the assistant gets cut off constantly by
    # nothing, which is a worse call than having no barge-in at all.
    speech_ms: int = 300


class BargeInDetector:
    """
    Whether the caller has started talking over the assistant.

    Separate from TurnDetector, and stricter, because the two questions
    are genuinely different. TurnDetector asks "has the caller finished?"
    in silence, where being generous costs nothing. This asks "should I
    stop talking?" during playback, where a false positive cuts the
    assistant off mid-sentence for a noise nobody made.

    Frames are held rather than discarded: the words that prove someone
    is speaking are the first words of what they're saying, and throwing
    them away means the caller's "actually, can you..." arrives at
    transcription with its opening missing.
    """

    def __init__(self, config: BargeInConfig | None = None):
        self.config = config or BargeInConfig()
        self._frames: list[np.ndarray] = []
        self._speech_ms: float = 0.0

    def reset(self) -> None:
        self._frames = []
        self._speech_ms = 0.0

    def add_frame(self, frame: np.ndarray) -> bool:
        """
        Feed one frame captured while the assistant is speaking. Returns
        True once the caller has been talking long enough to count.
        """
        if not len(frame):
            return False

        frame_ms = len(frame) / self.config.sample_rate * 1000
        energy = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))

        if energy >= self.config.energy_threshold:
            self._frames.append(frame)
            self._speech_ms += frame_ms
        else:
            # Must be CONTINUOUS. A run broken by quiet is noise, not
            # someone talking — without this, scattered clicks across a
            # long reply would eventually add up to a false interruption.
            self.reset()

        return self._speech_ms >= self.config.speech_ms

    def pop_frames(self) -> list[np.ndarray]:
        """The held frames, to be replayed into the turn detector."""
        frames = self._frames
        self.reset()
        return frames
