"""
Audio Codec Utilities

Twilio Media Streams sends and expects G.711 μ-law audio at 8kHz mono.
Whisper expects 16kHz mono PCM float32. TTS models (Kokoro: 24kHz,
Piper: ~22kHz depending on voice) produce their own native sample
rates. Everything that crosses one of those boundaries goes through
this module.

Implemented as a plain numpy-vectorized version of the standard ITU-T
G.711 μ-law algorithm, rather than the stdlib `audioop` module: `audioop`
is deprecated (PEP 594) and removed outright in Python 3.13, so relying
on it would be a dependency on something already scheduled for removal
upstream — not a good foundation for code meant to keep running.
"""

import numpy as np

_MULAW_BIAS = 0x84  # 132
_MULAW_CLIP = 32635


def mulaw_to_pcm16(mulaw_bytes: bytes) -> np.ndarray:
    """Decode G.711 μ-law bytes to a PCM16 numpy array (int16)."""
    mu = np.frombuffer(mulaw_bytes, dtype=np.uint8).astype(np.int32)
    mu = ~mu & 0xFF

    sign = mu & 0x80
    exponent = (mu >> 4) & 0x07
    mantissa = mu & 0x0F

    sample = ((mantissa << 3) + _MULAW_BIAS) << exponent
    sample = sample - _MULAW_BIAS
    sample = np.where(sign != 0, -sample, sample)

    return sample.astype(np.int16)


def pcm16_to_mulaw(pcm16: np.ndarray) -> bytes:
    """Encode a PCM16 numpy array (int16) to G.711 μ-law bytes.

    Derived as the exact algebraic inverse of mulaw_to_pcm16's formula
    (rather than an independently-reimplemented "segment search," which
    is easy to get subtly wrong): decode computes
    `sample = ((mantissa << 3) + BIAS) << exponent - BIAS`, so encode
    must find, for each magnitude, the exponent for which
    `(magnitude + BIAS) >> exponent` lands in the representable window
    `[BIAS, BIAS + 15*8]` — i.e. the smallest exponent that brings the
    shifted value at or under that window's top.
    """
    samples = pcm16.astype(np.int32)

    sign = np.where(samples < 0, 0x80, 0x00).astype(np.int32)
    magnitude = np.clip(np.abs(samples), 0, _MULAW_CLIP) + _MULAW_BIAS

    exponent = np.zeros_like(magnitude)
    found = np.zeros_like(magnitude, dtype=bool)
    for exp in range(8):
        fits = (magnitude >> exp) <= (_MULAW_BIAS + (15 << 3))
        take = fits & ~found
        exponent = np.where(take, exp, exponent)
        found = found | take
    exponent = np.clip(exponent, 0, 7)

    mantissa = np.clip((magnitude >> exponent) - _MULAW_BIAS, 0, 15 << 3) >> 3
    mu_byte = ~(sign | (exponent << 4) | mantissa) & 0xFF

    return bytes(mu_byte.astype(np.uint8).tobytes())


def resample_linear(pcm16: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """
    Resample a PCM16 array between sample rates via linear interpolation.

    Telephone audio is already band-limited to ~3.4kHz by G.711 itself
    (that's the PSTN's own bandwidth, not a limitation this codec adds),
    well under both 8kHz and 16kHz Nyquist limits — so simple linear
    interpolation doesn't discard anything a more expensive sinc-based
    resampler would have preserved for this specific signal. That
    tradeoff would not hold for resampling music or full-bandwidth audio.
    """
    if from_rate == to_rate or len(pcm16) == 0:
        return pcm16

    duration = len(pcm16) / from_rate
    old_indices = np.arange(len(pcm16))
    new_length = int(round(duration * to_rate))
    new_indices = np.linspace(0, len(pcm16) - 1, new_length)

    resampled = np.interp(new_indices, old_indices, pcm16.astype(np.float64))
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def pcm16_to_wav_bytes(pcm16: np.ndarray, sample_rate: int) -> bytes:
    """Wrap raw PCM16 mono samples in a minimal WAV container in memory."""
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16.astype(np.int16).tobytes())
    return buffer.getvalue()


def float32_to_pcm16(audio: np.ndarray) -> np.ndarray:
    """Convert float32 samples in [-1, 1] (typical model output) to PCM16."""
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)
