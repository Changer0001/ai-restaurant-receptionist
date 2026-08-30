"""Tests for app.audio.vad — the silence-based turn detector."""

import numpy as np

from app.audio.vad import TurnDetector, TurnDetectorConfig

_CONFIG = TurnDetectorConfig(
    sample_rate=8000,
    frame_ms=20,
    energy_threshold=400,
    silence_hangover_ms=100,
    max_utterance_ms=5000,
)


def _silence_frame():
    return np.zeros(160, dtype=np.int16)  # 20ms @ 8kHz


def _speech_frame():
    # Fixed (not random) so tests are deterministic — a constant tone
    # well above the energy threshold.
    t = np.linspace(0, 0.02, 160, endpoint=False)
    return (np.sin(2 * np.pi * 300 * t) * 5000).astype(np.int16)


def test_silence_only_never_triggers():
    detector = TurnDetector(_CONFIG)
    for _ in range(50):
        assert detector.add_frame(_silence_frame()) is False


def test_speech_then_sufficient_silence_triggers():
    detector = TurnDetector(_CONFIG)
    for _ in range(5):
        assert detector.add_frame(_speech_frame()) is False

    triggered = False
    for _ in range(10):
        if detector.add_frame(_silence_frame()):
            triggered = True
            break

    assert triggered


def test_brief_silence_mid_speech_does_not_trigger():
    """A single short pause between words shouldn't cut the utterance —
    only silence_hangover_ms of *continuous* silence should."""
    detector = TurnDetector(_CONFIG)
    for _ in range(3):
        detector.add_frame(_speech_frame())

    # 40ms of silence (2 frames) is under the 100ms hangover threshold
    assert detector.add_frame(_silence_frame()) is False
    assert detector.add_frame(_silence_frame()) is False

    # Resume speech — should not have been cut
    assert detector.add_frame(_speech_frame()) is False


def test_max_utterance_safety_cap():
    detector = TurnDetector(
        TurnDetectorConfig(sample_rate=8000, energy_threshold=400, max_utterance_ms=200)
    )
    triggered = False
    for _ in range(50):  # 50 * 20ms = 1000ms, well past the 200ms cap
        if detector.add_frame(_speech_frame()):
            triggered = True
            break
    assert triggered


def test_pop_utterance_returns_buffered_audio_and_resets():
    detector = TurnDetector(_CONFIG)
    for _ in range(5):
        detector.add_frame(_speech_frame())
    for _ in range(10):
        if detector.add_frame(_silence_frame()):
            break

    utterance = detector.pop_utterance()
    assert len(utterance) > 0

    # State is reset — a fresh instance's worth of silence shouldn't
    # immediately re-trigger.
    assert detector.add_frame(_silence_frame()) is False


def test_pop_utterance_before_any_speech_is_empty():
    detector = TurnDetector(_CONFIG)
    assert len(detector.pop_utterance()) == 0


def test_empty_frame_does_not_crash():
    detector = TurnDetector(_CONFIG)
    assert detector.add_frame(np.array([], dtype=np.int16)) is False
