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

---

For implementation details, see:
- [database.md](database.md) - Schema and models
- [deployment.md](deployment.md) - Infrastructure and cloud
- [capacity-planning.md](capacity-planning.md) - Resource analysis
