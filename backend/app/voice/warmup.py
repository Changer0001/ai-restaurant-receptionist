"""
Loading the speech models before a caller needs them.

Whisper and Kokoro are both loaded lazily, on first use. On a web
service that is the right default; on a phone line it means the first
caller after every restart pays for it, and they pay in the worst
possible currency — silence on an answered call, before the greeting.

Measured on a real call: the WebSocket opened at 21:36:06 and Kokoro
began loading immediately. Whisper started loading at 21:36:19. The
first transcript came back at 21:36:20. That caller sat on an open line
hearing nothing for about fourteen seconds. Every subsequent call that
day was fine, which is exactly what makes it easy to miss in testing and
guarantees a real customer finds it.

Warming runs in the background rather than blocking startup. Blocking
would be the stricter choice — no call could arrive before the models
were ready — but it also adds those seconds to every deploy and every
dev restart, and a call landing inside the warmup window is no worse off
than it is today. Failures are logged and swallowed: a warmup that
cannot load a model must never stop the service from starting, because
the lazy path it is trying to pre-empt still works.
"""

import asyncio
import logging
import time

from app.core.config import settings

logger = logging.getLogger(__name__)

# Short and unremarkable: this exists to make the model allocate its
# weights and run once, not to produce anything anyone hears.
_WARMUP_PHRASE = "Hello."


async def _warm_tts() -> None:
    from app.providers.tts import get_tts_provider

    provider = await get_tts_provider()
    await provider.synthesize(_WARMUP_PHRASE)


async def _warm_stt() -> None:
    """
    Load the recognizer, and transcribe a moment of silence.

    The silence matters: loading the model is most of the cost but not
    all of it, and the first real decode also pays one-off setup that a
    caller would otherwise wait through.
    """
    import numpy as np

    from app.audio.codec import pcm16_to_wav_bytes
    from app.providers.stt import get_stt_provider

    provider = await get_stt_provider()
    silence = np.zeros(16000, dtype=np.int16)  # one second at 16kHz
    await provider.transcribe(pcm16_to_wav_bytes(silence, 16000))


async def warm_speech_models() -> None:
    """Load STT and TTS so the first caller doesn't wait for them."""
    if not settings.WARM_SPEECH_MODELS_ON_STARTUP:
        logger.info("Speech-model warmup disabled; the first call will load them")
        return

    for name, warm in (("TTS", _warm_tts), ("STT", _warm_stt)):
        started = time.perf_counter()
        try:
            await warm()
            logger.info(f"{name} warm in {time.perf_counter() - started:.1f}s")
        except Exception as exc:
            # Deliberately not re-raised. The lazy path still works, so a
            # failed warmup costs the first caller some seconds — never
            # the service.
            logger.warning(f"{name} warmup failed ({exc}); the first call will load it")


def schedule_warmup() -> asyncio.Task:
    """Start warming in the background and hand back the task."""
    return asyncio.create_task(warm_speech_models())
