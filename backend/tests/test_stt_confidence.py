"""
Which transcripts are trusted enough to act on.

Every number here was measured on a real call. The classes overlap in
the wrong direction on avg_logprob-derived confidence, which is why that
signal is a backstop and no_speech_prob does the real work — see
STT_MIN_CONFIDENCE and WHISPER_NO_SPEECH_THRESHOLD in app/core/config.py.
"""

from types import SimpleNamespace

from app.core.config import settings


def _segment(text: str, avg_logprob: float, no_speech_prob: float = 0.05):
    return SimpleNamespace(
        text=text, avg_logprob=avg_logprob, no_speech_prob=no_speech_prob
    )


class _FakeWhisper:
    """Stands in for WhisperModel, returning canned segments."""

    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, *_args, **_kwargs):
        return iter(self._segments), SimpleNamespace()


def _transcribe(segments):
    import math

    from app.providers.stt.faster_whisper_provider import FasterWhisperSTTProvider

    provider = FasterWhisperSTTProvider()
    # math is used by the provider; referenced so the import is obviously
    # intentional if this file is read in isolation.
    assert math
    return provider._transcribe_sync(_FakeWhisper(segments), b"", "")


# ----------------------------------------------------------------------
# Real speech the old threshold rejected
# ----------------------------------------------------------------------


def test_real_short_speech_is_not_thrown_away():
    """
    Live call 2026-09-05. All three of these were intelligible speech and
    all three were rejected by the 0.45 floor. "six." was the caller
    answering "how many of you will there be?" — and being asked to say
    it again.
    """
    import math

    for text, confidence in (("hello.", 0.33), ("tikka, faafel.", 0.35), ("six.", 0.44)):
        segment = _segment(text, math.log(confidence))
        result_text, result_confidence = _transcribe([segment])
        assert result_text == text
        assert result_confidence >= settings.STT_MIN_CONFIDENCE, (
            f"{text!r} at {confidence} would be rejected — a caller saying this "
            "would be asked to repeat themselves"
        )


def test_the_confidence_floor_sits_below_all_observed_real_speech():
    """
    Guards the calibration itself. 0.33 is the lowest confidence any
    genuine utterance scored across two logged calls; a floor at or above
    it starts rejecting people again.
    """
    assert settings.STT_MIN_CONFIDENCE < 0.33


# ----------------------------------------------------------------------
# Non-speech, caught by the signal meant for it
# ----------------------------------------------------------------------


def test_a_segment_whisper_calls_non_speech_is_dropped():
    """
    The filter that avg_logprob could not be. Note the confidence here is
    HIGHER than the real speech above — which is exactly why the job
    moved off that signal.
    """
    import math

    segment = _segment("Fiyopas.", math.log(0.42), no_speech_prob=0.95)
    text, confidence = _transcribe([segment])

    assert text == ""
    assert confidence == 0.0


def test_speech_mixed_with_noise_keeps_only_the_speech():
    import math

    text, _ = _transcribe(
        [
            _segment("A table for six", math.log(0.7), no_speech_prob=0.02),
            _segment(" mmhm", math.log(0.5), no_speech_prob=0.9),
        ]
    )

    assert text == "A table for six"


def test_silence_still_produces_nothing_to_act_on():
    text, confidence = _transcribe([])

    assert text == ""
    assert confidence == 0.0
    assert confidence < settings.STT_MIN_CONFIDENCE
