#!/usr/bin/env python3
"""
Benchmark Whisper model sizes on THIS machine, with real call audio.

Transcription is the largest single cost in a turn — measured at ~3s of
a 4.5s turn — and the config currently asks for `large-v3`, the biggest
model there is. Whether a smaller one is good enough is not a question
anyone can answer from a spec sheet: it depends on this CPU, and on
whether the accuracy loss shows up on YOUR callers, on 8kHz phone audio,
in the accents that actually ring the restaurant.

So this prints time AND transcript for each model, side by side. The
decision is not "which is fastest" — it's "which is the fastest one that
still gets the dish names right".

Usage:
    cd backend && source venv/bin/activate
    python ../scripts/benchmark-stt.py recording1.wav [recording2.wav ...]

    # or pick the models yourself
    MODELS=tiny.en,base.en,small.en python ../scripts/benchmark-stt.py *.wav

Get real audio: FEATURE_CALL_RECORDING is on, so completed calls have a
recording_path. Failing that, record yourself over a phone — NOT a
laptop mic. Laptop audio is 16kHz+ and clean; a phone line is 8kHz and
compressed, which is the case Whisper finds hardest and the only one
that matters here.

Nothing is written and no config is changed. This only measures.
"""

import os
import statistics
import sys
import time
from pathlib import Path

# Ordered smallest to largest. distil-large-v3 is the interesting one:
# distilled from large-v3, so it keeps most of the accuracy on English
# at a fraction of the decode cost. large-v3 is included as the baseline
# to beat, since it's what the config asks for today.
DEFAULT_MODELS = [
    "base.en",
    "small.en",
    "distil-small.en",
    "distil-large-v3",
    "large-v3",
]

# Matches what the running app uses, so these numbers mean something for
# the app rather than for a benchmark's own settings.
BEAM_SIZE = int(os.environ.get("WHISPER_BEAM_SIZE", "1"))
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "") or (
    "float16" if DEVICE == "cuda" else "int8"
)
VOCABULARY = os.environ.get("STT_VOCABULARY", "")


def main() -> int:
    audio_paths = [Path(p) for p in sys.argv[1:]]
    if not audio_paths:
        print(__doc__)
        return 1

    missing = [p for p in audio_paths if not p.is_file()]
    if missing:
        print(f"ERROR: no such file: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 1

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "ERROR: faster_whisper not importable. Activate the backend venv first:\n"
            "  cd backend && source venv/bin/activate",
            file=sys.stderr,
        )
        return 1

    models = os.environ.get("MODELS")
    model_names = [m.strip() for m in models.split(",")] if models else DEFAULT_MODELS

    print(f"device={DEVICE} compute_type={COMPUTE_TYPE} beam_size={BEAM_SIZE}")
    print(f"{len(audio_paths)} clip(s), {len(model_names)} model(s)")
    if not VOCABULARY:
        print("no STT_VOCABULARY set — set it to test with the restaurant's dish names")
    print()

    results: dict[str, list[float]] = {}

    for name in model_names:
        print(f"=== {name} " + "=" * max(0, 60 - len(name)))
        try:
            load_started = time.perf_counter()
            model = WhisperModel(name, device=DEVICE, compute_type=COMPUTE_TYPE)
            print(f"    (loaded in {time.perf_counter() - load_started:.1f}s)")
        except Exception as exc:
            print(f"    SKIPPED — could not load: {exc}\n")
            continue

        # The first transcription on a fresh model pays one-off warmup
        # that a live call never pays, so it's run and discarded.
        try:
            list(model.transcribe(str(audio_paths[0]), language="en", beam_size=BEAM_SIZE)[0])
        except Exception:
            pass

        times = []
        for path in audio_paths:
            started = time.perf_counter()
            segments, _info = model.transcribe(
                str(path),
                language="en",
                initial_prompt=VOCABULARY or None,
                condition_on_previous_text=False,
                vad_filter=True,
                beam_size=BEAM_SIZE,
                without_timestamps=True,
            )
            text = " ".join(s.text for s in segments).strip()
            elapsed = time.perf_counter() - started
            times.append(elapsed)
            print(f"    {elapsed:5.2f}s  {path.name}: {text!r}")

        results[name] = times
        print(f"    median {statistics.median(times):.2f}s\n")
        del model

    if not results:
        print("No models ran.", file=sys.stderr)
        return 1

    print("=" * 64)
    print(f"{'model':<20} {'median':>8} {'vs large-v3':>14}")
    baseline = statistics.median(results["large-v3"]) if "large-v3" in results else None
    for name, times in results.items():
        median = statistics.median(times)
        speedup = f"{baseline / median:.1f}x faster" if baseline and median else "—"
        print(f"{name:<20} {median:>7.2f}s {speedup:>14}")

    print()
    print("Read the transcripts, not just the times. The fastest model that")
    print("still gets the dish names right is the one to use — set it as")
    print("WHISPER_MODEL in backend/.env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
