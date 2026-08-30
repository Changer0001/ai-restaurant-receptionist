# Development Status

**Phases 1–6 and 8–9 complete.** Foundation, restaurant management API,
RAG knowledge base, the AI conversation engine, voice (Twilio + local
STT/TTS wired into a live call), notification delivery (a standalone
worker that actually sends the SMS/email Phase 4 already queues), the
React admin dashboard, and now real Prometheus business metrics +
provisioned Grafana dashboards are built, tested, and verified. Phase 7
(live-call transfer) was already completed as part of Phase 5 — see
that section below. Phase 10 (production hardening: backups, rate
limiting, secret rotation, disaster recovery docs) is next.

## ✅ Phase 1 — Foundation

- FastAPI application, Pydantic configuration, async SQLAlchemy ORM
- 12 database models with real multi-tenant FK constraints
  (`TenantMixin.restaurant_id` → `restaurants.id`, `ondelete="CASCADE"`)
- Provider abstractions: `LLMProvider` (Ollama), `STTProvider`
  (Faster-Whisper), `TTSProvider` (interface only — implementation is
  Phase 5), `TelephonyProvider` (Twilio)
- Docker Compose stack: PostgreSQL, Redis, ChromaDB, Ollama, Nginx,
  Prometheus, Grafana
- `/health` and `/ready` — `/ready` genuinely checks Postgres, Redis,
  Ollama, and the vector DB, and returns a real 503 when any are down

## ✅ Phase 2 — Restaurant Management API

- JWT auth: `POST /api/auth/{register,login,refresh}`, `GET /api/auth/me`
  — access/refresh tokens are separately typed (a refresh token can't be
  replayed as an access token), and role/tenant claims are re-read from
  the database on every request rather than trusted from the token
- Restaurant CRUD, weekly hours (full-week PUT replace), FAQ CRUD
- Tenant isolation (`app/api/deps.py`): a restaurant-scoped request whose
  path `restaurant_id` doesn't match the caller's own returns 404 (never
  403 — doesn't confirm the ID exists to a caller who doesn't own it),
  enforced independently of anything the frontend sends
- Alembic migrations, generated and verified (upgrade / downgrade /
  zero-drift re-check)

## ✅ Phase 3 — RAG Knowledge Base

- `EmbeddingProvider` abstraction + `OllamaEmbeddingProvider`
  (`nomic-embed-text` by default, configurable via `EMBEDDING_MODEL`) —
  a separate, smaller model from the chat LLM
- Real ChromaDB-backed `VectorDB` (`app/rag/vector_db.py`): cosine
  distance, restaurant_id-filtered `where` on every query and delete,
  embeddings computed by the app (not Chroma's own default model, which
  would silently pull from the internet)
- Sentence-aware chunking (`app/rag/chunking.py`) with configurable
  `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP`
- `app/services/knowledge_service.py`: ingest (chunk → embed → store →
  persist DB row with `vector_ids`), list, delete, reindex, and
  `search_knowledge()` — the function Phase 4's AI layer will call to
  ground its answers. Results below `RAG_RELEVANCE_THRESHOLD` are
  dropped: an ungrounded question must come back with **zero** results,
  not the least-bad match, so the AI layer knows to say "I don't have
  that information" rather than improvise
- Endpoints: `GET/POST .../knowledge/upload`, `DELETE
  .../knowledge/{id}`, `POST .../knowledge/{id}/reindex` — upload accepts
  UTF-8 plain text (`.txt`/`.md`); PDF/DOCX parsing is not implemented
  (see docs/roadmap.md)

## ✅ Phase 4 — AI Conversation System

- Prompts (`backend/app/prompts/`): a system prompt plus versioned
  templates for intent classification, reservation-field extraction,
  RAG answer generation, and escalation — loaded from files, not inline
  strings, via `app/prompts/loader.py`
- `app/conversation/` — the state machine
  (`GREETING → IDENTIFY_INTENT → {RESERVATION_COLLECTING →
  RESERVATION_CONFIRMING} / TRANSFER_TO_HUMAN`), intent classification,
  reservation slot extraction (every extracted field — name, phone,
  date, time, party size — is validated before merging; an invalid
  value is dropped, never silently accepted), RAG-grounded FAQ answering
  that never calls the LLM at all when nothing relevant was retrieved,
  and a deterministic (non-LLM) hours-question path for "what time do
  you close" — see docs/architecture.md for why tool dispatch is
  state-machine-driven rather than LLM-emitted free-form calls
- `create_reservation_request` (`app/conversation/tools.py`) creates a
  real `Reservation` row (status=PENDING, never claims "confirmed") and
  queues real `Notification` rows for the restaurant's phone/email —
  actually *sending* those is Phase 6; this creates the outbox Phase 6's
  worker will send
- Ordering intent and explicit "let me speak to a person" requests
  transfer immediately without the AI attempting to take an order

## ✅ Phase 5 — Voice: Twilio + Local STT/TTS

- `app/audio/codec.py` — a from-scratch, numpy-vectorized G.711 μ-law
  codec (encode/decode), linear resampling, and WAV wrapping. Not
  stdlib `audioop`, which is deprecated and removed in Python 3.13
- `app/audio/vad.py` — `TurnDetector`: energy-threshold silence
  detection for turn-taking (a documented, deliberate simplification
  vs. a trained VAD model — see docs/roadmap.md), with a
  `max_utterance_ms` safety cap so a caller who never stops talking
  can't hold the buffer open forever
- Real Twilio webhook signature validation
  (`app/providers/telephony/twilio_provider.py`, using Twilio's own
  `RequestValidator`) — Phase 1's version was fully fake (see Bugs
  Fixed below)
- `app/providers/telephony/twiml.py` — TwiML built with Twilio's own
  SDK (`VoiceResponse`/`Connect`), not string concatenation, to avoid
  escaping bugs; uses `<Connect><Stream>` (bidirectional Media
  Streams), not `<Gather input="speech">`, so STT stays local rather
  than going through Twilio's own cloud speech recognition
- `app/providers/tts/kokoro_provider.py` and `piper_provider.py` —
  real local TTS providers behind the existing `TTSProvider`
  interface (widened to return `(pcm_bytes, sample_rate)`, since a
  caller can't resample without knowing the native rate)
- `app/voice/session.py` — `CallSession`, the per-call orchestrator:
  buffers caller audio, runs STT → the Phase 4 conversation engine →
  TTS on each detected turn, and streams the response back. No
  barge-in: while the AI's own response is playing, inbound audio is
  ignored until an estimated "speaking until" timestamp (computed from
  the outgoing audio's actual duration) elapses — Twilio's Media
  Streams `mark` event would give an exact signal instead of an
  estimate; using the estimate is a deliberate MVP scope-down (see
  docs/roadmap.md)
- `app/api/endpoints/twilio_webhooks.py` — `POST /voice` (looks up the
  restaurant by the dialed Twilio number, creates the `Call` row,
  returns Media Streams TwiML), `POST /status` (finalizes the call as
  a backstop if the WebSocket ever disconnects abnormally),
  `POST /recording`, `POST /transfer/{call_sid}`, and the
  `WEBSOCKET /media-stream/{call_sid}` handler itself — mounted outside
  `/api` (Twilio calls these, not the dashboard), every POST validated
  against its real Twilio signature
- `app/services/restaurant_service.get_restaurant_by_phone_number()` —
  the "Twilio number → restaurant_id" lookup at the center of this
  system's multi-tenancy for voice, which Phase 2 never actually built
- `app/services/call_service.py` — `Call`/`CallTranscript`/`CallEvent`
  persistence, including `ensure_call_finalized_from_status()`, an
  idempotent backstop so a call is never left open forever if the
  WebSocket disconnects without `CallSession.end()` running
- Live-call transfer is fully wired end-to-end, not just the data flag
  that was in place after Phase 4: when the engine signals
  `should_transfer`, `CallSession` closes the Media Stream, which ends
  the TwiML `<Connect>` verb and lets Twilio fall through to the
  `<Redirect>` already queued to `/transfer/{call_sid}` — which dials
  the restaurant's transfer number or hangs up based on what the `Call`
  row's `was_transferred` flag says happened. What was tracked as a
  separate future phase in Phase 4's status is complete as of this phase.
- `docker-compose.yml`/`Dockerfile` — removed the API's direct
  host port mapping (it bypassed Nginx and could let a caller spoof
  `X-Forwarded-Proto` to defeat signature validation) and added
  uvicorn's `--proxy-headers` so `request.url` reports the `https://`
  scheme Twilio actually signed against rather than Nginx's internal
  `http://` connection to the API

## ✅ Phase 6 — Notification Delivery

- `app/worker.py` — a standalone process (`docker-compose.yml`'s new
  `worker` service, `python -m app.worker`) that polls the
  `notifications` table and sends due, unsent rows. Runs out-of-process
  from the API server on purpose: notification delivery has nothing to
  do with a phone call's latency budget, and a slow/down SMTP server or
  Twilio outage must never add delay to what a caller hears
- `app/services/notification_service.py` — the actual send/retry logic
  the worker loops on: dispatches by `notification_type` ("sms"/"email"),
  and on failure retries with capped exponential backoff
  (`NOTIFICATION_BACKOFF_BASE_SECONDS`/`_MAX_SECONDS`) up to
  `NOTIFICATION_MAX_ATTEMPTS`, after which a row is left permanently
  unsent with `error_message` set — for a human to notice, never
  silently dropped. Respects the (previously dead, never-wired)
  `FEATURE_SMS_NOTIFICATIONS`/`FEATURE_EMAIL_NOTIFICATIONS` flags: a
  disabled channel's rows are left completely untouched, not counted as
  failed attempts, so re-enabling it later picks them up unchanged
- `TelephonyProvider.send_sms()` (new interface method) /
  `TwilioTelephonyProvider.send_sms()` — real SMS sending via Twilio's
  REST API (`client.messages.create`), run in a worker thread since the
  Twilio SDK's client is synchronous, not the async pattern the rest of
  this codebase uses
- `app/providers/email/` (new provider abstraction) — `EmailProvider` +
  `SMTPEmailProvider`, real SMTP sending via `aiosmtplib` (a genuinely
  async SMTP client), configured from the SMTP_* settings that already
  existed but were never wired to anything. Handles both STARTTLS
  (port 587, the default) and implicit TLS (port 465)
- `restaurant_service.get_active_phone_number_for_restaurant()` — an
  outbound SMS notification is sent "from" the restaurant's own active
  Twilio number, so it arrives from the same number the AI receptionist
  answers calls on, not a generic system-wide sender
- `/ready` now also checks SMTP reachability (skipped entirely if
  `FEATURE_EMAIL_NOTIFICATIONS` is off, so an operator who hasn't
  configured email notifications doesn't get a flapping readiness check
  for a server they never set up)
- New `Notification.attempt_count` column (migration
  `a1b2c3d4e5f6`, verified upgrade → downgrade → re-upgrade against a
  throwaway SQLite database — no live Postgres was reachable in this
  sandbox to run it against directly, the same verification Phase 2's
  migration got) — bounds the retry loop; `updated_at`
  (already bumped on every write by `TimestampMixin`) doubles as "last
  attempted at" for computing backoff, so no second timestamp column
  was needed

## ✅ Phase 8 — React Admin Dashboard

Backend additions (the dashboard needed read/status-update access to
data that had no API surface at all before this phase):

- `GET /api/restaurants/{id}/calls`, `GET .../calls/{call_id}` — call
  history and full per-call transcript. Read-only: calls are created
  and updated entirely by the voice pipeline, never through this API
- `GET /api/restaurants/{id}/reservations`, `GET .../reservations/{id}`,
  `PATCH .../reservations/{id}` — the reservation queue staff actually
  work from day to day: list (optionally filtered by status), view one,
  and confirm/decline a pending request. Read access is open to any
  authenticated user at the restaurant (including staff); the status
  update is too — unlike editing the restaurant's profile/hours/FAQs
  (owner/manager only), this is front-of-house's routine job
- `app/services/call_service.list_calls_for_restaurant`/`get_call_or_404`
  and the new `app/services/reservation_service.py` back these

Frontend (`frontend/`, previously an unstyled placeholder page — see
Bugs Fixed below): a real single-page app —
`AuthContext`/`ProtectedRoute` (JWT stored in `localStorage`; an axios
response interceptor transparently refreshes an expired access token
once and retries the original request, redirecting to `/login` only if
the refresh itself fails), a sidebar `Layout`, and one page per
resource: Dashboard (recent calls + pending reservations at a glance),
Calls (list + transcript detail), Reservations (filterable list,
confirm/decline actions), FAQs (create/edit/delete), Knowledge Base
(upload/reindex/delete), Hours (a full weekly editor, PUT-replace to
match the backend's semantics), and Restaurant Profile.

Verified with a live end-to-end pass, not just `npm run build`:
started the real FastAPI app and the Vite dev server together and
drove the whole UI with Playwright — register, every nav page, FAQ
creation, hours save, profile save, logout — confirming the actual
HTTP contracts match what the frontend code expects and catching the
`.gitignore` and `app/db/session.py` bugs below that a build alone
would not have surfaced.

## Bugs Fixed in Phase 8

The frontend's Phase 1 scaffolding didn't actually work at all, on any
of the three fronts a working frontend needs: `npm run build` and
`npm run type-check` both failed immediately (an unused `React` import
in `App.tsx` — real, current React with the JSX transform never
references `React` directly); `npm run lint` didn't run at all (no
ESLint config file existed anywhere in the project); and `App.tsx` used
Tailwind utility classes (`bg-gradient-to-br`, `text-4xl`, ...) with no
Tailwind installed, no `tailwind.config.js`/`postcss.config.js`, and no
`@tailwind` directives in `index.css` at all — every one of those
classes would have rendered as nothing. All three fixed: the unused
import, a real `.eslintrc.cjs`, and a genuine Tailwind v3 + PostCSS
setup, verified end-to-end (see above) rather than just by a clean
build.

Also found: a bare `lib/` entry in the root `.gitignore` (standard
Python-venv boilerplate) was silently excluding this phase's own
`frontend/src/lib/` from `git status`/`git add` entirely — an unscoped
pattern in a `.gitignore` shared by a Python backend and a Node
frontend matches same-named directories in both. Scoped every
Python-packaging-specific entry (`lib/`, `build/`, `env/`, `var/`,
etc.) to `backend/` so this can't recur for any future same-named
frontend directory.

And: `app/db/session.py` passed asyncpg-specific `connect_args`
(`server_settings`) to `create_async_engine` unconditionally. Against
the real Postgres `DATABASE_URL` this is harmless, but pointing
`DATABASE_URL` at anything else (found while standing up a throwaway
SQLite backend for the Playwright smoke test above) raises
`TypeError: 'server_settings' is an invalid keyword argument` during
table creation — caught and merely logged by `app.main`'s lifespan, so
the app starts, reports healthy, and silently has zero tables, with
every real request then failing on "no such table" with no obvious
link back to the actual cause. Now only added when `DATABASE_URL`
is actually a `postgresql` URL.

Found immediately after, from a real user's first `pip install -e
".[dev]"` on their own machine (Python 3.12, a genuinely fresh clone —
exactly the scenario none of the above had actually been tried
against): three more packaging bugs, all in `backend/pyproject.toml`.
`readme = "README.md"` pointed at a file that never existed —
`backend/README.md` was never created, so every install printed a
`SetuptoolsWarning` (added a real one). No `[tool.setuptools.packages.
find]` was configured, so a modern setuptools sees two top-level
directories that look like packages (`app/`, `alembic/`) and refuses
to guess which is the actual distribution — a hard, immediate failure
("Multiple top-level packages discovered in a flat-layout") on install
number one, before a single dependency downloads; scoped discovery to
`app*` (`alembic/` is invoked via its own CLI/config, never imported;
`tests/` should never ship in a wheel regardless). And `torch==2.1.1`
— pinned in Phase 5 alongside the exact Kokoro/faster-whisper/piper-tts
versions it was verified against — has no Python 3.12 wheel at all;
pip's resolver failed many dependencies deep with a confusing "no
matching distribution" error rather than a clear one. `requires-python`
narrowed to `>=3.11,<3.12` so this now fails immediately and legibly
instead. All three verified by reproducing the exact failure in a
throwaway Python 3.12 venv, then confirming a real, complete
`pip install -e ".[dev]"` (not just its metadata step) succeeds
end-to-end on Python 3.11 and the full test suite still passes against
that fresh install.

## ✅ Phase 9 — Observability: Business Metrics + Grafana

- `app/core/metrics.py` — real Prometheus metrics with actual call
  sites, on top of the process/platform metrics Phase 1's `/metrics`
  mount already exposed for free: `calls_total{outcome}` and
  `call_duration_seconds` (`call_service.finalize_call`, so both the
  normal end-of-call path and the abnormal-disconnect status-webhook
  backstop are covered by the one function both funnel through);
  `active_calls` (`CallSession.start()`/`end()` — a live count of
  in-progress calls, guarded against ever going negative if `end()`
  runs without a matching `start()`); `reservation_status_changes_total
  {status}` (reservation creation and every later status update);
  `notifications_sent_total{channel,outcome}` (sent / failed /
  permanently_failed, from the notification worker); and
  `twilio_signature_failures_total` (the entire auth boundary for the
  Twilio webhook router — worth graphing, not just logging)
- Deliberately no `restaurant_id` label anywhere — a documented
  cardinality decision (see docs/architecture.md): per-restaurant
  numbers belong in the database/admin dashboard, not as unbounded
  Prometheus label values in a multi-tenant deployment
- `infrastructure/grafana/provisioning/datasources/datasource.yml`
  (new) — Grafana had no datasource provisioned at all before this;
  Phase 1's dashboard *provider* config existed but pointed at an
  empty folder with nothing to render
- `infrastructure/grafana/provisioning/dashboards/ai-receptionist-
  overview.json` (new) — a real 7-panel dashboard (active calls, call
  volume by outcome, call duration percentiles, reservation status
  changes, notification outcomes, signature failures) querying the
  metrics above
- `infrastructure/prometheus/prometheus.yml` — removed the `node`/
  `postgres` exporter scrape jobs: no such exporter containers exist in
  `docker-compose.yml`, and `targets: ['localhost:9100']` inside the
  Prometheus container's own network namespace never resolved to
  anything real — those jobs would sit permanently "down" forever,
  which is worse than not scraping them at all. See docs/roadmap.md.

**Not independently verified in this sandbox**: actually rendering the
provisioned Grafana dashboard. Docker image pulls are blocked here (the
same constraint noted for Phase 5's docker-compose verification), so
this wasn't checked in a live Grafana instance — only that the JSON is
syntactically valid and structurally consistent (`python -m json.tool`,
a grid-position/panel-count check) and that the metrics it queries are
real, tested, application-level Prometheus metrics with the exact names
and label sets the dashboard's queries assume. The business-metrics
instrumentation itself (the part that can be tested without Docker) is
fully covered by `tests/test_metrics.py`.

## Test Suite

**206 passing** (`backend/tests/`), zero `ruff`/`mypy` findings across
`app/` and `tests/`. Runs entirely against in-memory SQLite (via
`StaticPool`), an isolated in-memory ChromaDB per test (unique
collection name per test — see the note in `conftest.py`'s `vector_db`
fixture about `EphemeralClient` sharing backing state across instances
in the same process), a deterministic fake embedding provider, and a
scripted fake LLM provider (`tests/fakes.py`) — never the real Postgres,
Redis, ChromaDB, or Ollama.

Coverage: password hashing/JWT correctness, auth flows, restaurant/hours/
FAQ CRUD, cross-tenant isolation (explicitly proving restaurant A cannot
read, write, or leak restaurant B's data through any endpoint), knowledge
ingestion/deletion/reindexing, RAG retrieval safety (tenant filtering
under search, relevance-threshold cutoff, `top_k` limiting, empty results
for an empty knowledge base), and the full conversation engine — hours
questions answered deterministically, FAQ answers grounded in retrieved
knowledge (and never hallucinated when nothing is retrieved), a complete
multi-turn reservation flow ending in a real database row, denial/retry
during reservation confirmation, order requests transferring without the
AI attempting to take the order, and escalation (both explicit "human"
requests and sentiment-based) short-circuiting before intent
classification even runs.

Phase 5 additionally covers: μ-law codec round-tripping (all 256 byte
values, modulo the universal, benign dual-zero-representation quirk),
resampling and WAV wrapping, turn detection (silence hangover, the
`max_utterance_ms` safety cap), Twilio signature validation with real
computed signatures (and rejection of a missing/bad one — the exact
class of bug Phase 1 shipped), TwiML generation including XML escaping,
`Call` persistence and finalization (including the abnormal-disconnect
backstop), the full `CallSession` turn loop (greeting, no-barge-in,
FAQ answering, a complete reservation flow, order-request transfer,
outcome tracking) driven directly against scripted STT/LLM/TTS fakes,
and an end-to-end test that drives the actual
`/media-stream/{call_sid}` WebSocket protocol (connect → start → real
μ-law audio frames → stop) and verifies both the audio returned over
the wire and the `Call` row's final state in the database.

Phase 6 additionally covers: sending a due SMS/email notification,
already-sent rows being skipped, a failed send recording its error and
incrementing `attempt_count`, backoff timing (a row still inside its
window is left alone; one past it is retried), permanent failure after
`NOTIFICATION_MAX_ATTEMPTS` (and no further attempts after that),
resolving the right "from" number for SMS (including the case where a
restaurant has none configured), each disabled-channel feature flag
leaving its rows completely untouched, an unrecognized
`notification_type` failing visibly rather than crashing the sweep,
processing several due notifications in one pass, `TwilioTelephonyProvider.
send_sms()` against a mocked Twilio client (success and failure),
`SMTPEmailProvider` (message construction, STARTTLS vs. implicit-TLS
port selection, credential-less sending, health check), and the
worker's `run_once()` end to end against the real notification-service
wiring with fake providers substituted in.

Phase 8 additionally covers (backend): listing calls most-recent-first,
call detail with its full transcript, tenant isolation on both (a
second restaurant's owner gets 404, not the data), listing/filtering/
updating reservations by status, and 404s for an unknown or
cross-tenant reservation. The frontend has no automated test suite
(no test runner is configured in `package.json` — see docs/roadmap.md)
— `tsc --noEmit`, `eslint`, and `vite build` all passing cleanly is
the frontend's equivalent gate, backed by the one-time Playwright
walkthrough described above for actual runtime behavior.

Phase 9 additionally covers: every business metric's real call site
actually updates it — `calls_total`/`call_duration_seconds` via
`finalize_call`, `active_calls` incrementing on `start()` and
decrementing on `end()` (and never going negative when `end()` runs
without a matching `start()`), reservation creation and status updates
each landing in `reservation_status_changes_total` under the right
label, notification success/failure/permanent-failure each landing in
`notifications_sent_total` under the right outcome, and an invalid
Twilio signature incrementing `twilio_signature_failures_total`. Every
assertion reads the metric's own value via `prometheus_client`'s public
`.collect()` API as a *delta* (before vs. after the operation under
test) rather than an absolute value, since the metrics registry is a
process-wide singleton shared across the whole test run.

## Bugs Fixed Along the Way

Phase 1's foundation had several defects that would have surfaced the
first time each code path actually ran (see `git log` for full detail on
each fix commit): invalid class-definition syntax in every model,
`Call.metadata` colliding with SQLAlchemy's reserved attribute, missing
FK constraints, a `DATABASE_URL` scheme incompatible with the async
engine, `aioredis` (crashes on import under Python 3.11), two nonexistent
pinned packages (`psycopg==3.17.0`, `wave-stream==0.1.0`) that would have
broken `pip install` outright, a `/ready` endpoint that computed but
never applied its 503 status code, and Redis never being initialized at
all. Also fixed during Phase 3: `docker-compose.yml` referenced a
`./infrastructure/ollama/Modelfile` that was never created — Docker
refuses to start a container with a nonexistent bind-mount source, which
would have broken `docker compose up` outright. Found during Phase 4:
`RestaurantHolidayHours` was never built despite being in the original
model list — a holiday question (see docs/roadmap.md) is deliberately
excluded from the deterministic hours path rather than silently
answered with regular weekly hours that may not apply that day.

Found during Phase 5 — the most serious of the session so far:
**Twilio webhook signature validation was completely fake**
(`return signature is not None`, i.e. it accepted literally any
non-empty string as a valid signature). Rebuilt against Twilio's real
`RequestValidator`, and the `TelephonyProvider.validate_webhook_signature`
interface itself was fixed alongside it — its original shape,
`(signature, request_body)`, doesn't even match how Twilio signs
requests (URL + form params, not the body). Also found: `faster-whisper`'s
`Segment` object has no `.confidence` attribute at all — Phase 1's STT
code read `segment.confidence` and would have raised `AttributeError`
on every real transcription, never having been exercised end-to-end;
fixed using `math.exp(segment.avg_logprob)` as a confidence proxy, and
its `model.transcribe()` call (synchronous, with a generator that does
lazy inference on iteration) was never wrapped in `asyncio.to_thread`,
so it would have blocked the event loop on every real utterance — fixed
alongside it. `pyproject.toml` pinned `faster-whisper==0.10.0` (fails to
build at all — an old `av` dependency version with no prebuilt wheel)
and `piper-tts==1.2.0` (a version with a completely different,
incompatible API from what any code could reasonably be written
against); both verified against real downloaded wheels and bumped.
`kokoro` was never added to dependencies despite `KokoroTTSProvider`
needing it, and its config used `KOKORO_LANGUAGE="en"` where Kokoro
actually requires single-letter codes (`"a"` for American English) plus
a named voice, which has no default. `docker-compose.yml` exposed the
API's port directly to the host, bypassing Nginx entirely — besides
contradicting the "AI services aren't directly exposed" requirement,
this would let a caller spoof `X-Forwarded-Proto` to defeat signature
validation; removed, with `--proxy-headers` added to uvicorn so
`request.url` reports the scheme Twilio actually signed against.
`CallSession.start()` persisted the greeting to the DB transcript but
never added it to the engine's own in-memory conversation history,
meaning the model's own history-aware prompts had no idea a greeting
had been spoken; found via a failing test, fixed by recording it in
both places.

Found during Phase 6: `aiosqlite` — the async SQLite driver every
test's `db_engine` fixture actually depends on
(`sqlite+aiosqlite:///:memory:`) — was never declared as a dependency
anywhere in `pyproject.toml`, in the main list or the `dev` extra. It
only "worked" because some earlier ad hoc `pip install` had left it
sitting in this project's dev environment; a genuinely clean
`pip install -e ".[dev]"` on a fresh machine would have failed to even
import the test suite's own fixtures. Added to the `dev` extra, pinned
to the version already verified working. Also found:
`FEATURE_SMS_NOTIFICATIONS`/`FEATURE_EMAIL_NOTIFICATIONS` and
`TelephonyProvider.health_check()` all existed since Phase 1 but were
never referenced by any code path — the feature flags are now honored
by `notification_service.process_pending_notifications()`, and an
analogous SMTP health check was added to `/ready` for the new email
provider (Twilio's own `health_check()` remains unused — see
docs/roadmap.md).

## Not Yet Built (By Design — Later Phases)

- Production hardening: backups, rate limiting, secret rotation,
  disaster recovery docs (Phase 10)

## Quick Start

```bash
cd ai-restaurant-receptionist
docker compose up -d
docker compose exec ollama ollama pull qwen3:8b
docker compose exec ollama ollama pull nomic-embed-text
# API docs: http://localhost/docs
# Admin dashboard: http://localhost (served by nginx, proxying /api to the backend)
```

Running the test suite locally (no Docker required — everything runs
against in-memory fakes). **Requires Python 3.11** specifically (not
3.12+): `torch==2.1.1`, pinned together with the exact Kokoro/faster-
whisper/piper-tts versions it was verified against, has no Python 3.12
wheel — `pyproject.toml`'s `requires-python = ">=3.11,<3.12"` enforces
this with a clear error rather than a confusing deep pip-resolver
failure. Also requires a virtual environment on Debian/Ubuntu (PEP
668's "externally managed environment" blocks a plain `pip install`
outside one):

```bash
cd backend
python3.11 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
ruff check app/ tests/
mypy app/
```

Running the frontend locally against a backend of your own (no Docker
required — `VITE_API_PROXY_TARGET` defaults to `http://localhost:8000`):

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
npm run type-check
npm run lint
npm run build
```

## Key Files

- `backend/app/db/models.py` — all 12 models
- `backend/app/api/deps.py` — tenant isolation enforcement
- `backend/app/rag/vector_db.py` — ChromaDB integration
- `backend/app/services/knowledge_service.py` — RAG ingestion/retrieval
- `backend/app/conversation/engine.py` — the AI conversation state machine
- `backend/app/prompts/` — versioned prompt templates
- `backend/app/voice/session.py` — the per-call voice orchestrator
- `backend/app/api/endpoints/twilio_webhooks.py` — Twilio HTTP webhooks
  and the Media Streams WebSocket
- `backend/app/audio/codec.py` — the G.711 μ-law codec
- `backend/app/worker.py` — the standalone notification-sending worker
- `backend/app/services/notification_service.py` — notification
  dispatch, retry, and backoff logic
- `frontend/src/App.tsx` — the dashboard's routes
- `frontend/src/api/client.ts` — axios instance, auth-refresh
  interceptor
- `frontend/src/auth/AuthContext.tsx` — login/register/session state
- `backend/app/core/metrics.py` — Prometheus business metrics
- `infrastructure/grafana/provisioning/dashboards/ai-receptionist-
  overview.json` — the provisioned Grafana dashboard
- `docker-compose.yml` — full local stack
- `docs/architecture.md` — system design and decision log
- `docs/roadmap.md` — documented gaps and future work
