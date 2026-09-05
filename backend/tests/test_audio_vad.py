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


# ----------------------------------------------------------------------
# Barge-in: deciding the caller has started talking over the assistant
#
# Stricter than TurnDetector on purpose. A false positive here cuts the
# assistant off mid-sentence for a noise nobody made, which makes for a
# worse call than not being interruptible at all.
# ----------------------------------------------------------------------


def _frame(amplitude: int, samples: int = 160):
    """One 20ms frame at 8kHz."""
    return np.full(samples, amplitude, dtype=np.int16)


def test_sustained_speech_over_the_assistant_counts_as_an_interruption():
    from app.audio.vad import BargeInDetector

    detector = BargeInDetector()
    # 300ms of speech = 15 frames of 20ms.
    triggered = [detector.add_frame(_frame(5000)) for _ in range(15)]

    assert triggered[-1] is True
    assert not any(triggered[:-1]), "should not fire before the sustained threshold"


def test_a_short_burst_is_not_an_interruption():
    """A cough, a door, a click. Short and loud is not someone talking."""
    from app.audio.vad import BargeInDetector

    detector = BargeInDetector()
    assert not any(detector.add_frame(_frame(6000)) for _ in range(5))  # 100ms


def test_quiet_audio_never_interrupts():
    """Line noise and room tone under the threshold, for a long time."""
    from app.audio.vad import BargeInDetector

    detector = BargeInDetector()
    assert not any(detector.add_frame(_frame(200)) for _ in range(100))  # 2 seconds


def test_scattered_noise_does_not_accumulate_into_an_interruption():
    """
    The run has to be continuous. Without that, isolated clicks spread
    across a long reply would eventually add up and cut the assistant off
    for nothing.
    """
    from app.audio.vad import BargeInDetector

    detector = BargeInDetector()
    fired = False
    for _ in range(40):
        fired |= detector.add_frame(_frame(6000))   # loud
        fired |= detector.add_frame(_frame(50))     # quiet, resets the run
    assert not fired


def test_the_frames_that_triggered_it_are_kept():
    """
    They're the opening of what the caller is saying. Dropping them means
    "actually, can you..." reaches transcription with its first word
    missing.
    """
    from app.audio.vad import BargeInDetector

    detector = BargeInDetector()
    for _ in range(15):
        detector.add_frame(_frame(5000))

    frames = detector.pop_frames()
    assert len(frames) == 15
    # And popping resets it, so the next reply starts from scratch.
    assert detector.pop_frames() == []


def test_the_bar_is_higher_than_for_ordinary_turn_taking():
    """
    Speech loud enough to hear in silence should not necessarily cut off
    the assistant — during playback the inbound leg can carry echo of our
    own voice.
    """
    from app.audio.vad import BargeInConfig, TurnDetectorConfig

    assert BargeInConfig().energy_threshold > TurnDetectorConfig().energy_threshold
