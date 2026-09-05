# Engineering Log

Persistent memory for the autonomous engineering loop on this AI phone
receptionist. **Read this file first** after any context loss, then
continue from `## Next Autonomous Action` — do not restart the
investigation.

Evidence in this log comes from real calls placed through Twilio to a
live backend, not from the test suite alone. Where a number appears, it
was measured.

---

# Engineering Objective

Take an existing, working AI phone receptionist to the point where a
caller cannot easily tell it is not a competent human receptionist:
natural turn-taking, interruptible, context-aware, low latency, honest
about what it doesn't know, and never inventing business outcomes.

Secondary objective, stated by the owner: onboarding another restaurant
must be a **data** change only — no code edits per client.

---

# Current System State

_As of 2026-09-05, commit `ccae4ed`, verified against a live call at
01:17–01:22._

**Stack.** FastAPI + SQLAlchemy async + Postgres; ChromaDB for RAG;
Ollama for embeddings (`nomic-embed-text`); Groq for the LLM
(`openai/gpt-oss-120b` for answers, `openai/gpt-oss-20b` for the two
classification calls); faster-whisper `small` int8 on CPU for STT;
Kokoro on CPU for TTS; Twilio Media Streams over WebSocket for
telephony. React/Vite dashboard.

**Entry points.** `backend/app/main.py` (lifespan warms the speech
models); `app/api/endpoints/twilio_webhooks.py` (voice webhook,
media-stream WebSocket, transfer webhook); `app/voice/session.py`
(per-call orchestrator); `app/conversation/engine.py` (the state
machine).

**Confirmed working on a live call (01:17–01:22):**
- Barge-in fires: `Caller started talking over the assistant — stopping
  playback` at 01:22:38.
- Model warmup: `TTS warm in 5.2s`, `STT warm in 1.3s`, both complete
  13s before the call arrived. No cold-start silence.
- Clean call teardown, no stack traces.
- Per-turn DEBUG noise gone; `Turn timing:` still at INFO.

**Test suite:** 363 passing, 0 failing, stable across 3 consecutive
full runs and 15 consecutive runs of the websocket end-to-end test.

---

# Target State

1. P0/P1/P2 conversation defects: none known.
2. Caller-perceived latency: median turn under 3s, from end of caller
   speech to first audio. **Currently ~4.5s median, ~8s worst.**
3. Interruption works and does not false-trigger.
4. Onboarding a restaurant touches only `restaurants/<name>/` and the
   restaurant's own DB row.
5. Every defect found on a real call has a regression test.

---

# Active Problems

See `## Remaining Gaps` — that section is authoritative.

---

# Completed Work

Chronological, most recent first. Each entry links a real-call symptom
to the commit that fixed it.

| Commit | What it fixed | Evidence it came from |
|---|---|---|
| `ccae4ed` | Bare "yes" loop; `"no, seven thirty"` losing the correction; hangup mid-turn losing the call record | 4 consecutive "yes" turns in the 21:44 call; websocket test 1-in-5 failure |
| `cff0385` | ~14s of silence on the first call after restart (lazy model loading) | 21:36 call: WebSocket open 21:36:06, first transcript 21:36:20 |
| `28b5325` | Hangup reported as an unhandled ERROR; websocket E2E test permanently red | `ConnectionClosedOK` traceback in the 21:40 call |
| `e7b8d8c` | Barge-in (turn decoupled from the read loop, Twilio `clear`, strict interrupt detector) | Owner request |
| `9f58f41` | Questions and farewells mid-booking swallowed by the slot extractor; `"hang up"` not a farewell | 5 consecutive ignored turns in the 21:25 call |
| `c752689` | Garbled audio answered as speech; booking made on the call forgotten; cancelling started a second booking | `'Fiyopas.'` (0.42) answered; 3× "remind me my booking" ignored |
| `9696ef4` | Yes/no word list replaced with fast path + classifier fallback | 4th instance of the same word-list bug |
| `663b072` | `"no, please don't"` booking a table; `"yes, but make it 8"` booking the old time; `"cancellation policy"` discarding a booking | Engine audit |
| `d199f4a` | Restaurant content moved out of the seeding script into `restaurants/<name>/` | Owner: "give it to another business" |
| `80c2cfa` | Twilio lookup failing on the `+` in E.164 → webhook silently never updated | `full-restart.sh` output contradicting itself |

---

# Tests Performed

- Full suite: **368 passed, 0 failed**, 2 consecutive runs (GAP-001 fix).
- Full suite: 363 passed, 0 failed, 3 consecutive runs (`ccae4ed`).
- Websocket end-to-end: 15 consecutive clean runs after the
  shared-session fix.
- Live call 2026-09-05 01:17–01:22 (~20 turns) on `ccae4ed`.

# Test Failures

None outstanding in the suite. Live-call defects are tracked as gaps.

---

# Remaining Gaps

### GAP-001 — Confidence gate rejects clear short speech — **RESOLVED**
- **Severity:** P2 (conversation-breaking; caller asked to repeat
  themselves for no reason)
- **Evidence:** live call 2026-09-05 —
  `'hello.' (0.33 < 0.45)`, `'six.' (0.44 < 0.45)`,
  `'tikka, faafel.' (0.35 < 0.45)`. All three were real, intelligible
  speech. `'six.'` was the caller answering "how many of you?".
- **Root cause:** `STT_MIN_CONFIDENCE` gates on
  `exp(segment.avg_logprob)`, which is systematically low for one- and
  two-word utterances. It does not separate the classes: good `'six.'`
  scored 0.44 while garbage `'Fiyopas.'` scored 0.42. **The provider
  discards `segment.no_speech_prob`** — the signal Whisper produces
  specifically for this decision.
- **Status:** RESOLVED, awaiting live confirmation.
- **Fix:** the provider now drops segments on `segment.no_speech_prob`
  (`WHISPER_NO_SPEECH_THRESHOLD`, 0.6 — faster-whisper's own default),
  and `STT_MIN_CONFIDENCE` drops 0.45 -> 0.25 to be a backstop against
  near-zero confidence only. Each signal now does the job it exists for.
- **Why a threshold could never have worked:** the classes invert on
  this signal. Sorted by confidence: `'hello.'` 0.33 (speech),
  `'tikka, faafel.'` 0.35 (speech), `'free of us'` 0.41 (noise),
  `'Fiyopas.'` 0.42 (noise), `'six.'` 0.44 (speech). Any cut that keeps
  "six" also keeps "Fiyopas". Tuning was not an option; the signal was.
- **Regression tests:** `backend/tests/test_stt_confidence.py`, using the
  measured values above. 4 of its 5 tests fail on `ccae4ed`, confirming
  they reproduce the defect rather than describe the fix.
- **Residual risk:** `no_speech_prob` thresholds are set to
  faster-whisper's default, not calibrated against this line's audio,
  because no call has yet logged those values. The provider now logs
  them at DEBUG so the next call produces the data.

### GAP-005 — Non-speech filtering is uncalibrated for this phone line
- **Severity:** P4
- **Evidence:** `WHISPER_NO_SPEECH_THRESHOLD` is faster-whisper's
  default (0.6), not a value measured against 8kHz Twilio audio.
- **Status:** OPEN
- **Next action:** on the next live call, read the
  `Dropping non-speech segment: ... (no_speech_prob=...)` DEBUG lines
  and check nothing intelligible appears among them.

### GAP-002 — TTS is now the largest latency contributor
- **Severity:** P3
- **Evidence:** live call turn breakdown — STT is flat at 2.1–2.4s,
  engine 0.0–1.3s, **TTS 0.9–4.9s**. Worst turns (7.7–8.1s total) are
  TTS-dominated.
- **Status:** OPEN
- **Next action:** measure Kokoro synthesis cost per character to
  confirm it scales with reply length, then decide between shortening
  answers and a faster voice/provider.

### GAP-003 — STT flat ~2.2s/turn regardless of utterance length
- **Severity:** P3
- **Evidence:** 0.82s of audio → 2.2s; 4.7s of audio → 2.3s. Whisper's
  encoder runs a fixed 30s window.
- **Status:** OPEN — `scripts/benchmark-stt.py` exists and is unrun.
- **Next action:** owner to run the benchmark on their hardware; decide
  `small` vs `distil-small.en` vs a streaming hosted provider.

### GAP-004 — No barge-in threshold calibration from real audio
- **Severity:** P3
- **Evidence:** barge-in fired exactly once in a ~20-turn call. Not
  enough samples to know whether it is too strict.
- **Status:** OPEN
- **Next action:** collect more interruption attempts on the next call.

---

# Root Causes

- **Word lists cannot represent natural yes/no.** Four separate bugs
  (`"no"` in `"not"`, `"please"` in a refusal, `"cancel"` in
  `"cancellation"`, `"stop"` in `"non-stop"`) were one wrong
  representation. Fixed structurally in `9696ef4`, not patched again.
- **One AsyncSession shared between a detached turn task and the
  connection lifecycle.** Cancelling mid-commit corrupted it. Fixed by
  shielding the commit (`ccae4ed`).
- **Confidence from `avg_logprob` is length-dependent** and was being
  asked to do a job Whisper has a dedicated output for (GAP-001).

---

# Performance Measurements

See `.claude/latency.log` for the time series.

---

# Conversation Quality Findings

Working on the 2026-09-05 call: interruption, warm start, low-confidence
recovery (mechanism fired correctly — it was the threshold that was
wrong), no repeated questions, no invented information.

Not yet exercised on a live call: yes-to-an-offer, the sign-off path,
cancel-offers-a-human, mid-booking questions.

---

# Blocked Items

None. Everything outstanding is actionable without the owner, except
GAP-003, which needs a benchmark run on their hardware.

---

# Completion Criteria

- No open P0/P1/P2 gaps.
- Median live-call turn under 3s.
- Every live-call defect has a regression test.
- Full suite green across 3 consecutive runs.
- A second restaurant can be onboarded with no code change.

---

# Next Autonomous Action

GAP-001 is fixed and the suite is green (368, twice). The next action is
**GAP-002: establish whether Kokoro synthesis time scales with reply
length, and by how much.**

Concretely: write `scripts/benchmark-tts.py` that synthesizes a set of
replies of known character counts (one clause, one sentence, two
sentences, three) through the configured TTS provider, reporting seconds
per call and seconds per character. Run it in this container to get a
shape, and record the numbers in `.claude/latency.log`.

This decides between two very different fixes: if cost is dominated by
per-call overhead, chunking is already doing the work and the answer is
a faster provider; if it scales with characters, the answer is shorter
answers, and the RAG prompt's "ONE short sentence" instruction is not
being obeyed. The live call shows 0.88s for a short reply and 4.85s for
a long one, which suggests the latter — but that is an inference from
two data points, not a measurement.
