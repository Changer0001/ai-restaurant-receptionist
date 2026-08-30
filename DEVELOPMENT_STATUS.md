# Development Status

**Phases 1–4 complete.** Foundation, restaurant management API, RAG
knowledge base, and the AI conversation engine are built, tested, and
verified. Phase 5 (voice: Twilio + STT/TTS wiring) is next.

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

## Test Suite

**96 passing** (`backend/tests/`), zero `ruff`/`mypy` findings across
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

## Not Yet Built (By Design — Later Phases)

- Voice call handling: Twilio webhooks, STT/TTS wired into a live call,
  the call session that feeds transcripts into the Phase 4 engine and
  speaks its responses back (Phase 5)
- Actually sending the SMS/email notifications Phase 4 already queues,
  plus a proper background worker for them (Phase 6)
- Actually transferring a call via Twilio when the engine signals
  `should_transfer` (Phase 7) — the signal exists now, the phone action
  doesn't yet
- React admin dashboard beyond the Phase 1 skeleton (Phase 8)
- Prometheus business metrics, Grafana dashboards beyond the Phase 1
  scaffolding (Phase 9)
- Production hardening: backups, rate limiting, secret rotation,
  disaster recovery docs (Phase 10)

## Quick Start

```bash
cd ai-restaurant-receptionist
docker compose up -d
docker compose exec ollama ollama pull qwen3:8b
docker compose exec ollama ollama pull nomic-embed-text
# API docs: http://localhost/docs
```

Running the test suite locally (no Docker required — everything runs
against in-memory fakes):

```bash
cd backend
pip install -e ".[dev]"
pytest tests/ -v
ruff check app/ tests/
mypy app/
```

## Key Files

- `backend/app/db/models.py` — all 12 models
- `backend/app/api/deps.py` — tenant isolation enforcement
- `backend/app/rag/vector_db.py` — ChromaDB integration
- `backend/app/services/knowledge_service.py` — RAG ingestion/retrieval
- `backend/app/conversation/engine.py` — the AI conversation state machine
- `backend/app/prompts/` — versioned prompt templates
- `docker-compose.yml` — full local stack
- `docs/architecture.md` — system design and decision log
- `docs/roadmap.md` — documented gaps and future work
