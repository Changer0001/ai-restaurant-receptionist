"""Tests for app.audio.codec — G.711 μ-law codec and resampling."""

import numpy as np

from app.audio.codec import (
    float32_to_pcm16,
    mulaw_to_pcm16,
    pcm16_to_mulaw,
    pcm16_to_wav_bytes,
    resample_linear,
)


def test_mulaw_roundtrip_all_byte_values():
    """Every one of the 256 possible μ-law bytes should decode->encode
    back to itself, except the well-known dual "positive/negative zero"
    representation (0x7F and 0xFF both decode to 0 — re-encoding 0
    necessarily picks one canonical form). This is a universal, benign
    property of every μ-law codec, not a bug in this implementation."""
    all_bytes = bytes(range(256))
    decoded = mulaw_to_pcm16(all_bytes)
    re_encoded = pcm16_to_mulaw(decoded)

    mismatches = [(a, b) for a, b in zip(all_bytes, re_encoded, strict=True) if a != b]
    assert mismatches == [(0x7F, 0xFF)]


def test_mulaw_silence_decodes_near_zero():
    assert mulaw_to_pcm16(bytes([0xFF]))[0] == 0


def test_mulaw_encode_decode_reasonable_fidelity_on_tone():
    t = np.linspace(0, 1, 8000)
    sine = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)

    decoded = mulaw_to_pcm16(pcm16_to_mulaw(sine))
    error = np.abs(sine.astype(np.int64) - decoded.astype(np.int64))

    # μ-law is lossy by design (8-bit companded encoding of a 16-bit
    # signal) — some quantization error is expected and correct, but it
    # must stay small relative to the signal amplitude (10000), not
    # dominate it.
    assert error.max() < 1000
    assert error.mean() < 300


def test_pcm16_to_mulaw_handles_negative_and_positive_extremes():
    extremes = np.array([32767, -32768, 0], dtype=np.int16)
    encoded = pcm16_to_mulaw(extremes)
    assert len(encoded) == 3  # doesn't raise, doesn't clip to zero length


def test_resample_linear_scales_length_correctly():
    pcm_8k = np.zeros(160, dtype=np.int16)  # 20ms @ 8kHz
    resampled = resample_linear(pcm_8k, 8000, 16000)
    assert len(resampled) == 320  # 20ms @ 16kHz


def test_resample_linear_downsampling():
    pcm_16k = np.zeros(320, dtype=np.int16)
    resampled = resample_linear(pcm_16k, 16000, 8000)
    assert len(resampled) == 160


def test_resample_linear_noop_when_rates_match():
    pcm = np.array([1, 2, 3], dtype=np.int16)
    assert list(resample_linear(pcm, 8000, 8000)) == [1, 2, 3]


def test_resample_linear_empty_input():
    assert len(resample_linear(np.array([], dtype=np.int16), 8000, 16000)) == 0


def test_resample_linear_preserves_approximate_waveform():
    t = np.linspace(0, 1, 8000, endpoint=False)
    sine_8k = (np.sin(2 * np.pi * 200 * t) * 10000).astype(np.int16)
    resampled = resample_linear(sine_8k, 8000, 16000)

    # Spot-check: the resampled signal's peak amplitude should be close
    # to the original's — a badly broken resampler would produce noise
    # or near-silence instead.
    assert abs(int(np.max(np.abs(resampled))) - 10000) < 1000


def test_pcm16_to_wav_bytes_produces_valid_riff_header():
    pcm = np.array([100, -100, 200, -200], dtype=np.int16)
    wav_bytes = pcm16_to_wav_bytes(pcm, 8000)
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"


def test_pcm16_to_wav_bytes_is_decodable():
    import io
    import wave

    pcm = np.array([100, -100, 200, -200], dtype=np.int16)
    wav_bytes = pcm16_to_wav_bytes(pcm, 16000)

    with wave.open(io.BytesIO(wav_bytes)) as wav_file:
        assert wav_file.getframerate() == 16000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        frames = wav_file.readframes(wav_file.getnframes())
        assert np.frombuffer(frames, dtype=np.int16).tolist() == [100, -100, 200, -200]


def test_float32_to_pcm16_scales_and_clips():
    values = np.array([0.5, -0.5, 1.0, -1.0, 2.0, -2.0], dtype=np.float32)
    pcm = float32_to_pcm16(values)

    assert pcm[2] == 32767  # 1.0 -> max positive int16
    assert pcm[3] == -32767  # -1.0
    assert pcm[4] == 32767  # 2.0 clipped to 1.0 -> same as max
    assert pcm[5] == -32767  # -2.0 clipped
