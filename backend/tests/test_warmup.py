"""
Tests for app.voice.warmup — loading the speech models before a caller
needs them.

Whisper and Kokoro load lazily. On a real call the WebSocket opened at
21:36:06, Kokoro began loading immediately, Whisper started at 21:36:19,
and the first transcript came back at 21:36:20 — that caller sat on an
answered line hearing nothing for about fourteen seconds.
"""

import asyncio
import logging

from app.core.config import settings
from app.voice import warmup


class _RecordingProvider:
    def __init__(self):
        self.synthesized: list[str] = []
        self.transcribed: list[bytes] = []

    async def synthesize(self, text: str):
        self.synthesized.append(text)
        return b"\x00\x00", 24000

    async def transcribe(self, audio: bytes, vocabulary=None):
        self.transcribed.append(audio)
        return "", 0.0


async def test_warmup_loads_both_models(monkeypatch):
    tts, stt = _RecordingProvider(), _RecordingProvider()
    monkeypatch.setattr("app.providers.tts.get_tts_provider", lambda: _ready(tts))
    monkeypatch.setattr("app.providers.stt.get_stt_provider", lambda: _ready(stt))

    await warmup.warm_speech_models()

    assert tts.synthesized, "TTS was never exercised, so it isn't warm"
    # Real audio, not an empty buffer: the first decode pays one-off
    # setup beyond loading the weights.
    assert stt.transcribed and len(stt.transcribed[0]) > 0


async def _ready(provider):
    return provider


async def test_a_failing_warmup_never_stops_the_service(monkeypatch, caplog):
    """
    The lazy path still works, so a warmup that can't load a model costs
    the first caller some seconds — it must never cost the service its
    startup.
    """

    async def _explode():
        raise RuntimeError("no model file")

    monkeypatch.setattr("app.providers.tts.get_tts_provider", lambda: _explode())
    monkeypatch.setattr("app.providers.stt.get_stt_provider", lambda: _explode())

    with caplog.at_level(logging.WARNING):
        await warmup.warm_speech_models()  # must not raise

    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2


async def test_warmup_can_be_turned_off(monkeypatch):
    tts = _RecordingProvider()
    monkeypatch.setattr(settings, "WARM_SPEECH_MODELS_ON_STARTUP", False)
    monkeypatch.setattr("app.providers.tts.get_tts_provider", lambda: _ready(tts))

    await warmup.warm_speech_models()

    assert not tts.synthesized


async def test_scheduling_returns_a_cancellable_task(monkeypatch):
    """Startup must not block on it, and shutdown must be able to drop
    it — a warmup still running when the app stops has nobody to serve."""
    monkeypatch.setattr(settings, "WARM_SPEECH_MODELS_ON_STARTUP", False)

    task = warmup.schedule_warmup()
    assert isinstance(task, asyncio.Task)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
