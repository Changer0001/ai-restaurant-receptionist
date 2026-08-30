# Architecture Documentation

## Overview

The AI Restaurant Receptionist is built on a **local-first + cloud-dependent telephony** architecture:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Public Internet                             │
│                                                                     │
│  Twilio Voice (PSTN) ←→ TLS/WebHook ←→ Public Domain/IP           │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
                    ┌─────────────────┐
                    │  Nginx (TLS)    │ ← Reverse Proxy, SSL Termination
                    │  Load Balancer  │
                    └─────────────────┘
                              ↓
        ┌─────────────────────────────────────────┐
        │      Homelab / Private Network          │
        │                                         │
        │  ┌──────────────────────────────────┐  │
        │  │  FastAPI Backend                 │  │
        │  │  - Voice Webhooks                │  │
        │  │  - Restaurant Management         │  │
        │  │  - Reservation System            │  │
        │  │  - Call State Machine            │  │
        │  │  - Tool Orchestration            │  │
        │  └──────────────────────────────────┘  │
        │           ↓      ↓       ↓             │
        │      ┌────────────────────────┐        │
        │      │   AI Inference Stack   │        │
        │      │   (GPU-Accelerated)    │        │
        │      │                        │        │
        │      │ Faster-Whisper (STT)   │        │
        │      │ Ollama + Qwen 3 (LLM)  │        │
        │      │ Kokoro (TTS)           │        │
        │      │ ChromaDB (RAG/Vectors) │        │
        │      │                        │        │
        │      └────────────────────────┘        │
        │           ↓      ↓       ↓             │
        │      ┌────────────────────────┐        │
        │      │  Data & Cache Layer    │        │
        │      │                        │        │
        │      │ PostgreSQL (Primary)   │        │
        │      │ Redis (Cache/State)    │        │
        │      │ Prometheus (Metrics)   │        │
        │      │                        │        │
        │      └────────────────────────┘        │
        │                                         │
        └─────────────────────────────────────────┘
```

## Key Architectural Principles

### 1. Local-First AI Inference

All computationally expensive AI operations run locally:

- **Speech-to-Text (Whisper)**: GPU-accelerated local transcription
- **Language Model (Ollama)**: Local LLM inference, no API calls
- **Text-to-Speech (Kokoro)**: Local voice synthesis
- **RAG/Embeddings (ChromaDB)**: Local vector search

**Why:** Lower latency, privacy, reduced costs, independence from cloud APIs.

### 2. Cloud-Dependent Telephony

Twilio handles what it's best at:

- PSTN connectivity
- Telephone numbers
- Call routing
- SMS delivery
- Compliance/regulatory

**Why:** Reliable, globally available, handles carrier integration.

### 3. Multi-Tenancy by Design

Every resource is scoped to a `restaurant_id`:

```python
restaurant_id → PostgreSQL constraints
            → Vector DB metadata filtering
            → Cache key namespacing
            → Audit logging
```

No trust in frontend filtering. Authorization enforced at every layer.

### 4. Stateless API Servers

FastAPI workers are horizontally scalable:

- Call state stored in Redis/PostgreSQL
- Sticky sessions not required
- Easy to add worker pods later

### 5. Modular Provider Architecture

AI providers behind interfaces:

```
LLMProvider (Interface)
├── OllamaLLMProvider (MVP)
└── Future: OpenAI, Anthropic, etc.

STTProvider (Interface)
├── FasterWhisperSTTProvider (MVP)
└── Future: Google Cloud Speech, etc.

TTSProvider (Interface)
├── KokoroTTSProvider (MVP)
└── Future: ElevenLabs, Google Cloud TTS, etc.

TelephonyProvider (Interface)
├── TwilioTelephonyProvider (MVP)
└── Future: SIP, FreeSWITCH, Asterisk, etc.
```

Easy to swap implementations, test with mocks, migrate providers.

## Call Flow

### 1. Incoming Call

```
Customer Calls → PSTN → Twilio → HTTP/Webhook → Nginx → FastAPI
```

### 2. Within FastAPI

```
1. Receive call
2. Validate Twilio signature
3. Look up restaurant by phone number
4. Create Call record
5. Start call session
6. Return TwiML response
```

### 3. Call Conversation Loop

```
While call is active:
  1. Collect audio chunk from caller
  2. STT (Whisper) → transcribe to text
  3. RAG (ChromaDB) → retrieve relevant docs
  4. LLM (Ollama) → generate response
  5. Tool Execution → update DB, send notifications
  6. TTS (Kokoro) → convert response to speech
  7. Stream audio back to caller
  8. Listen for next input or timeout
```

### 4. Special Cases

**Ordering Request:**
```
AI detects "order" intent → Transfer to human → Update call_outcome
```

**Reservation Workflow:**
```
Detect intent → State machine (collect name, phone, date, time, party size)
→ Validate → Create Reservation → Send SMS/Email → Confirm to caller
```

**Low Confidence:**
```
AI confidence < threshold → Escalate to human → Transfer call
```

## Database Schema

### Core Tenants

- **Restaurant**: Multi-tenant root entity
- **RestaurantPhoneNumber**: Twilio number mapping
- **RestaurantHours**: Operating hours (multi-day support)
- **RestaurantFAQ**: FAQ database
- **RestaurantKnowledgeDocument**: Docs for RAG

### Authentication

- **User**: User accounts (platform admin, restaurant owner, staff)
- **Role**: RBAC (platform_admin, restaurant_owner, restaurant_manager, restaurant_staff)

### Operations

- **Call**: Call metadata (duration, outcome, transcript)
- **CallTranscript**: Turn-by-turn conversation log
- **CallEvent**: State machine events for debugging
- **Reservation**: Reservation requests
- **Notification**: SMS/Email notification history
- **AuditLog**: All user actions for compliance

See [database.md](database.md) for full ERD and schema details.

## Scaling Strategy

### Phase 1: Single GPU Server (MVP)

Current architecture supports:

- **RTX 3090**: 5-10 concurrent calls
- **RTX 4090**: 10-20 concurrent calls

All services on one machine.

### Phase 2: Multi-GPU Cluster

```
Load Balancer
    ↓
┌───┴────┬────────┐
v        v        v
GPU-1   GPU-2   GPU-3
(AI)    (AI)    (AI)
  ↓      ↓      ↓
  └──────┴──────┴─ Shared PostgreSQL
         ↓ ↓
    Shared Redis
```

Redis becomes coordinator for session state.

### Phase 3: Kubernetes SaaS

```
API Deployment (stateless)
AI Inference Deployment (GPU nodes)
PostgreSQL (managed)
Redis (managed)
Vector DB (managed)
```

MVP architecture already supports this transition.

## Security Model

### Authentication & Authorization

1. **JWT tokens** for API access
2. **Role-based access control** (RBAC)
3. **Tenant isolation** at database constraints
4. **Twilio signature validation** for webhooks

### Data Protection

- **TLS/HTTPS** for all external communication
- **Secrets via environment variables** (never in code)
- **SQL injection protection** via SQLAlchemy ORM
- **Input validation** via Pydantic schemas
- **Password hashing** with bcrypt
- **Audit logging** of all user actions

### Privacy

- **No unnecessary call recording** (configurable)
- **GDPR-compatible retention policies** (configurable)
- **No sensitive data in logs** (phone numbers masked)
- **No sensitive data in metrics** (customer info not in labels)

## Performance Considerations

### Latency Budget

For a natural conversation, each round should take < 3 seconds:

- STT (audio chunk → text): 1-2s (Whisper Large V3)
- LLM (prompt → response): 0.5-1s (Qwen 3 8B)
- TTS (text → audio): 0.5-1s (Kokoro)

Total: 2-4 seconds (acceptable for phone)

### Resource Constraints

**GPU VRAM (24GB RTX 3090/4090):**
- Whisper Large V3: 6GB
- Qwen 3 8B: 8-10GB  
- TTS: 2GB
- Buffer: 4-8GB

Total: ~20GB (fits with margin)

**Concurrent Operations:**

Per GPU with 24GB VRAM:
- ~2-3 concurrent STT jobs
- ~2-3 concurrent LLM jobs
- ~3-5 concurrent TTS jobs

Queue non-bottleneck operations (TTS) to avoid blocking.

## Observability

### Logs

- Structured JSON logging
- Request IDs for tracing
- Call IDs for correlation
- Restaurant IDs for multi-tenant debugging

### Metrics

- **Prometheus scrape** from `/metrics`
- **Grafana dashboards** for visualization
- **Key metrics**: call count, latency, GPU usage, errors

### Tracing

- Call tracing from ingestion to completion
- State machine transitions logged
- Tool execution logged
- Errors captured with context

## Future Enhancements

### Not MVP but Architected For

1. **POS Integrations** (Clover, Toast, Square)
   - Order creation in restaurant systems
   - Real-time availability checking

2. **Advanced Scheduling**
   - Availability blocking by time
   - Real reservation inventory
   - Overbooking management

3. **Sentiment Analysis**
   - Customer satisfaction tracking
   - Escalation triggers
   - Quality coaching

4. **Multi-language Support**
   - STT language auto-detection
   - LLM multilingual support
   - Localized prompts

5. **Advanced Analytics**
   - Call outcome trends
   - Peak time analysis
   - Customer segmentation

6. **AI Coaching**
   - Call quality scoring
   - Training recommendations
   - A/B testing prompts

## Decision Log

### Why Ollama + Qwen 3 8B?

- **Local inference**: Full control, privacy, no API costs
- **Qwen 3 8B**: Strong reasoning, good context window, fits in VRAM
- **Ollama**: Simple deployment, good model support
- **Alternative**: Could use Llama 3.1, Mistral later

### Why ChromaDB?

- **Simple**: Deployable in Docker
- **Multi-tenant**: Metadata filtering by restaurant_id
- **Production-ready**: Used in production systems
- **Scalable**: Can migrate to Qdrant later

Implementation notes from actually building it (Phase 3):

- **Embeddings are computed by the app, not ChromaDB.** ChromaDB's
  default embedding function silently downloads a small ONNX model from
  the internet on first use — contrary to this project's local-first,
  Ollama-centric design. Instead, `EmbeddingProvider` (same abstraction
  pattern as `LLMProvider`/`STTProvider`) wraps Ollama's
  `/api/embeddings` endpoint with a separate, smaller model
  (`nomic-embed-text` by default, configurable via `EMBEDDING_MODEL`) —
  deliberately not the chat model, since embedding models are
  purpose-built and much smaller.
- **Single shared collection, not one per restaurant.** Every chunk
  carries `restaurant_id` in its metadata, and every query/delete filters
  on it server-side via Chroma's `where` clause — never in application
  code after the fact. One collection is simpler to operate (no
  proliferating per-tenant collections as restaurants are added) and
  matches how the spec describes tenant isolation for RAG (metadata
  filtering, not physical separation).
- **Cosine distance**, set via `metadata={"hnsw:space": "cosine"}` at
  collection creation — bounded to `[0, 2]` with a clean similarity
  conversion (`similarity = 1 - distance`), which is what
  `RAG_RELEVANCE_THRESHOLD` filtering is built on.
- **Multi-condition `where` filters need an explicit `$and`.** ChromaDB
  0.4.x rejects `{"restaurant_id": x, "document_id": y}` (implicit AND
  across dict keys) with "Expected where to have exactly one operator" —
  it must be `{"$and": [{"restaurant_id": x}, {"document_id": y}]}`.
- **`EphemeralClient()` instances share backing state within a process**
  when given the same collection name — a real gotcha hit while writing
  tests (two "isolated" test clients were silently reading and writing
  the same in-memory collection). The test suite works around this by
  giving each test a uniquely-named collection; production only ever
  runs one `HttpClient` per process, so this doesn't affect it.

### Why PostgreSQL?

- **ACID**: Reservations must be transactional
- **Proven**: Most reliable database
- **Extensible**: Can add new tables easily
- **Migrations**: Alembic for schema versioning

### Why Twilio?

- **Proven**: Industry standard for voice
- **Reliable**: 99.99% uptime SLA
- **Simple**: Easy webhook integration
- **Future**: Not locked in (TelephonyProvider interface)

### Why the conversation engine doesn't use LLM-driven free-form tool calls

The spec's tool-call architecture (section 18) describes "the LLM
requests an action, the application validates it, the application
executes it" — commonly implemented by having the model emit a
structured directive (native function-calling, or a JSON block in its
own output) that the application then parses and dispatches to whichever
tool the model named.

`app/conversation/engine.py` implements the same safety property —
the LLM never writes to the database, every value it produces is
validated before use — but the *dispatch* decision (which tool runs,
and when) is made by deterministic Python state-machine logic, not by
the model choosing freely each turn. The LLM's role is narrowed to
in-state natural language understanding (classify intent, extract
reservation fields) and generation (phrase a grounded FAQ answer);
`app/conversation/tools.py`'s `create_reservation_request` and
`app/conversation/hours_answer.py`'s structured lookup are the only two
tools with a state that decides to invoke them, and that decision is
always the engine's, never the model's.

This was a deliberate scope-down from a more general design, weighed
against this project's actual constraints:

- **Reliability with a smaller local model.** Free-form tool-calling
  protocols (native or JSON-in-text) are meaningfully less reliable with
  an 8B open model than with a large hosted one — a malformed or
  missing tool call mid-call degrades the caller's experience directly,
  with no easy retry inside a live phone conversation.
- **A phone call has less room for a wrong turn than a chat app.** A
  chatbot can recover from a bad tool call in the next message; a phone
  caller has already heard the (possibly wrong) result by the time
  anyone notices.
- **The full tool surface here is small and known in advance.** With
  only a handful of tools (reservation creation, hours lookup, RAG
  search), a state machine that decides when each applies is not meaningfully
  less flexible than a model choosing among the same handful of options
  — it's just more predictable.

This is a call worth revisiting once a phase actually needs an LLM
choosing among many tools dynamically (e.g. POS integration's menu
lookup, availability check, and order creation all being live options in
the same turn) — at that point, native function-calling (which recent
Ollama versions and many models support) may earn its added complexity.
For the tool surface Phases 4-7 need, it doesn't yet.

### Why Media Streams (`<Connect><Stream>`), not `<Gather input="speech">`

Twilio offers two ways to get a caller's speech into an application:
`<Gather input="speech">`, which runs Twilio's own cloud STT and hands
back the transcript, or `<Connect><Stream>` (Media Streams), which
opens a raw bidirectional audio WebSocket and leaves STT entirely to
the application. This project uses only Media Streams — `<Gather>`
would route every caller's speech through Twilio's cloud, directly
contradicting the "local-first AI inference" principle this whole
system is built around (see Key Architectural Principle #1). Twilio's
role here is PSTN connectivity only: getting audio bytes on and off
the phone network, never doing anything with their content.

`<Connect>`, not `<Start>`, matters too: `<Start><Stream>` is
inbound-only (it can tap a call's audio for logging/analytics without
taking control of it), while `<Connect><Stream>` hands the whole call
over to the WebSocket, which is required to play synthesized speech
back to the caller at all.

### Why a hand-written μ-law codec, not `audioop`

Twilio's Media Streams protocol carries audio as G.711 μ-law, 8kHz,
base64-encoded inside each `media` event. Python's stdlib `audioop`
module can decode/encode this, but it's deprecated as of Python 3.11
and removed entirely in 3.13 (PEP 594) — building a new system against
it in 2025+ would mean either pinning to an aging Python version or
inheriting a removal deadline on day one. `app/audio/codec.py`
implements the encode/decode/resample logic directly with numpy
instead: it's a well-documented, standardized codec (ITU-T G.711) with
no ambiguity in the transform, and a vectorized numpy implementation
processes a frame in the same handful of array operations `audioop`
would have used internally.

### Why call-transfer timing is an estimate, not an exact signal

See docs/roadmap.md's "No barge-in" entry for the full reasoning —
noted here because it's a call-flow design decision, not just a gap:
`CallSession` decides when it's safe to start listening again after
speaking using the outgoing audio's own computed duration plus a fixed
tail buffer, rather than waiting for Twilio's Media Streams `mark`
event (which echoes back once audio has actually finished playing on
the caller's device). The estimate is simpler to reason about for an
MVP with no barge-in support at all — there's nothing to interrupt, so
exact timing only affects how promptly listening resumes, not
correctness of what's said.

### Why webhook signature validation is the entire auth boundary for voice

Every other endpoint in this API sits behind the JWT + tenant-isolation
dependencies described above. `app/api/endpoints/twilio_webhooks.py`
cannot use them — an inbound caller has no account, and Twilio itself
isn't a tenant user — so `X-Twilio-Signature` validation (via Twilio's
own `RequestValidator`, computed over the exact URL and form params of
the request) is the only thing standing between this router and a
forged webhook that could create fictitious calls, trigger a transfer
to an arbitrary number, or manipulate a call record. This is why an
invalid or missing signature is treated as seriously as it is (403,
logged, request never touches the database) and why it's covered by a
dedicated test file (`tests/test_twilio_signature.py`) built
specifically to catch a validator that accepts more than it should —
which is exactly what shipped in Phase 1 before this was fixed (see
DEVELOPMENT_STATUS.md).

### Why the notification worker is a separate process, not inline in the call

Phase 4's `create_reservation_request` queues `Notification` rows the
instant a reservation is created; Phase 6's `app/worker.py` is a
completely separate long-running process (`docker-compose.yml`'s
`worker` service) that polls for and sends them, rather than the live
call's own code path sending them immediately. This mirrors the same
reasoning as local-first AI inference generally: a live phone call has
a tight latency budget (see "Performance Considerations" below), and
sending an SMS/email involves a synchronous round trip to an external
service (Twilio's REST API, an SMTP server) that has no bearing on the
call itself — a caller who just asked for a reservation shouldn't wait
an extra few hundred milliseconds (or, if SMTP is down and retrying,
much longer) for the AI to speak its next line just because the owner
notification happens to be slow.

The tradeoff is that a notification lags real time by up to
`NOTIFICATION_POLL_INTERVAL_SECONDS` (15s by default) — acceptable
here since these are best-effort owner-facing notifications about a
*request*, not anything the caller is waiting on synchronously. Retry
state (`attempt_count`, backoff computed from `updated_at`) lives on
the `Notification` row itself rather than in the worker process, so
the worker is fully stateless and can be restarted, scaled to multiple
replicas, or moved to a different host without losing track of what
still needs sending or re-sending a row mid-backoff.

### Why SMS notifications are sent "from" the restaurant's own Twilio number

`notification_service._send_one` resolves the outbound SMS "from"
number via `restaurant_service.get_active_phone_number_for_restaurant`
— the same Twilio number the restaurant's AI receptionist answers
calls on — rather than a single system-wide sending number. Two
reasons: it's a number this Twilio account already owns and is
authorized to send from (no separate SMS-sending number needs to be
provisioned per restaurant), and the restaurant owner receiving "New
reservation request..." recognizes it as coming from their own AI
receptionist's number rather than an unfamiliar shared one — relevant
for a multi-tenant deployment where many unrelated restaurants' owners
would otherwise all see texts from the exact same sender.

### Why the dashboard talks to a relative `/api`, not a configured base URL

`frontend/src/api/client.ts`'s axios instance always calls `/api/...`,
never an absolute URL read from an environment variable. In every real
deployment (`docker-compose.yml`'s `nginx` service) the frontend and
API share one origin — Nginx serves the built frontend at `/` and
proxies `/api/` to the backend — so a relative path is not just
simpler, it avoids a whole class of CORS configuration that a
cross-origin setup would otherwise need. `vite.config.ts`'s dev-server
proxy (`VITE_API_PROXY_TARGET`, defaulting to `http://localhost:8000`)
makes the exact same relative path work against a locally-running
backend during `npm run dev`, so the frontend code never needs to know
or care which environment it's running in.

### Why JWTs live in `localStorage`, not an httpOnly cookie

The usual argument for httpOnly cookies over `localStorage` is that
JavaScript (and thus a successful XSS payload) can read `localStorage`
but not an httpOnly cookie. That protection only matters if the app
plausibly runs attacker-controlled script in the first place — this is
an internal admin dashboard for restaurant staff with no third-party
content, user-generated HTML rendering, or plugin surface anywhere in
it, not a public-facing app. The backend is also a pure bearer-token
JSON API (`app/api/deps.py` reads `Authorization: Bearer ...`
exclusively) that never sets cookies, so httpOnly cookie auth would
need CSRF protection added on the backend for a benefit this
particular frontend doesn't have much use for. Revisit if this
dashboard ever embeds untrusted content (e.g. rendering caller-supplied
text as HTML rather than plain text, which it does not do today).

### Why Calls/Reservations are read/status-update-only from the admin API

`GET /api/restaurants/{id}/calls` and `.../reservations` have no
corresponding `POST` — both resources are created exclusively by the
voice pipeline during a live call (`app/voice/session.py` for calls,
`app/conversation/tools.py.create_reservation_request` for
reservations), and the admin API only ever reads them or (for
reservations) updates a status field. This mirrors the same "controlled
tool" principle used throughout `app/conversation/`: a `Call` row
without a real Twilio `call_sid` or a `Reservation` without a real
conversation behind it would be fabricated data with nothing to back
it, so the dashboard doesn't offer a way to create either by hand. See
docs/roadmap.md's "No manual reservation creation" entry for the one
legitimate case (a walk-in, or a call the AI didn't handle) this
currently can't cover.

---

For implementation details, see:
- [database.md](database.md) - Schema and models
- [deployment.md](deployment.md) - Infrastructure and cloud
- [capacity-planning.md](capacity-planning.md) - Resource analysis
