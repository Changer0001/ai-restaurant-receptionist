#!/usr/bin/env python3
"""
Measure what speech synthesis actually costs, and what drives it.

On a phone call the caller hears silence for the whole of a turn, and on
a real call TTS was the largest single contributor after transcription —
0.88s for a short reply and 4.85s for a long one. Those two points
suggest cost scales with reply length, but two points are a guess.

This separates the two possibilities, because they have opposite fixes:

  per-call overhead dominates  -> chunking already helps; the answer is
                                  a faster provider or device
  per-character cost dominates -> the answer is shorter replies, and the
                                  answer prompt's "ONE short sentence"
                                  instruction is not being obeyed

Reports seconds per call, seconds per character, and the ratio of
synthesis time to the duration of audio produced (a "real-time factor" —
below 1.0 means synthesis outruns playback).

Usage:
    cd backend && source venv/bin/activate
    python ../scripts/benchmark-tts.py

Nothing is written and no config is changed. This only measures.
"""

import asyncio
import statistics
import sys
import time

# Replies of increasing length, all in the register the assistant
# actually speaks in — a benchmark on lorem ipsum measures the wrong
# phonemes.
SAMPLES = [
    "Yes.",
    "We're open till ten tonight.",
    "We're open till ten tonight, and the kitchen closes at half nine.",
    (
        "We're open till ten tonight, and the kitchen closes at half nine. "
        "There's parking in the small lot behind us, though it fills up on "
        "weekend evenings."
    ),
    (
        "We're open till ten tonight, and the kitchen closes at half nine. "
        "There's parking in the small lot behind us, though it fills up on "
        "weekend evenings. If it's full, there's street parking on Main "
        "Street and the side roads around us, and it's rarely more than a "
        "couple of minutes' walk."
    ),
]

_REPEATS = 3


async def main() -> int:
    from app.core.config import settings
    from app.providers.tts import get_tts_provider

    provider = await get_tts_provider()

    print(f"provider={settings.TTS_PROVIDER} device={settings.KOKORO_DEVICE} "
          f"speed={settings.KOKORO_SPEED}")
    print("warming up...", flush=True)
    await provider.synthesize("Warming up.")
    print()

    print(f"{'chars':>6} {'median s':>9} {'s/char':>8} {'audio s':>8} {'RTF':>6}  text")
    rows = []
    for text in SAMPLES:
        timings, audio_seconds = [], 0.0
        for _ in range(_REPEATS):
            started = time.perf_counter()
            pcm, rate = await provider.synthesize(text)
            timings.append(time.perf_counter() - started)
            # 16-bit samples, so two bytes each.
            audio_seconds = len(pcm) / 2 / rate if rate else 0.0

        median = statistics.median(timings)
        per_char = median / len(text)
        rtf = median / audio_seconds if audio_seconds else float("nan")
        rows.append((len(text), median, per_char, audio_seconds, rtf))
        print(f"{len(text):>6} {median:>9.2f} {per_char:>8.4f} "
              f"{audio_seconds:>8.2f} {rtf:>6.2f}  {text[:40]}...", flush=True)

    print()
    shortest, longest = rows[0], rows[-1]
    extra_chars = longest[0] - shortest[0]
    extra_seconds = longest[1] - shortest[1]
    marginal = extra_seconds / extra_chars if extra_chars else 0.0

    # Fitting cost = overhead + marginal * chars using the two extremes.
    overhead = shortest[1] - marginal * shortest[0]

    print(f"fixed overhead per call : {overhead:.2f}s")
    print(f"marginal cost per char  : {marginal * 1000:.2f}ms "
          f"({marginal * 100:.1f}s per 100 characters)")
    print()
    if overhead > longest[1] / 2:
        print("VERDICT: dominated by per-call overhead. Shortening replies")
        print("will not help much; a faster provider or device will.")
    else:
        print("VERDICT: dominated by reply length. Shortening what the")
        print("assistant says is the cheapest win available.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
