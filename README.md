# AI Restaurant Receptionist

A production-ready, local-first AI phone receptionist system designed for restaurants, architected to run on local homelab hardware with an NVIDIA GPU, while maintaining a clear path to multi-tenant SaaS commercialization.

## What It Does

The AI Restaurant Receptionist answers incoming restaurant phone calls and:

- **Answers questions** using restaurant-specific knowledge and FAQ
- **Handles reservations** by collecting party size, date, time, and customer info
- **Detects ordering requests** and seamlessly transfers to human staff
- **Provides information** about hours, location, parking, policies, etc.
- **Escalates intelligently** to humans when uncertain or when customers request it
- **Supports multiple restaurants** with complete tenant isolation
- **Records transcripts** for quality assurance and training
- **Notifies owners** via SMS and email when reservations are requested
- **Operates completely locally** with open-source models on consumer-grade GPUs

## Architecture Overview

```
                    Internet / PSTN
                           |
                        Twilio Voice
                           |
                    ┌───────┴────────┐
                    |                |
                  HTTPS          Webhook
                    |                |
            Load Balancer            |
                    |                |
                    v                v
              Nginx Reverse ────────── FastAPI
              Proxy (TLS)             Backend
                    |
        ┌───────────┼───────────┬──────────┐
        |           |           |          |
    PostgreSQL   Redis      Vector DB   Ollama
    (Primary)  (Caching)   (ChromaDB)  (LLM)
                                 |
                          Faster-Whisper (STT)
                          Kokoro TTS
```

**Local-First + Cloud-Dependent Telephony:**

- **Local:** All AI inference (STT, LLM, TTS, RAG) runs on your GPU
- **Cloud:** Twilio handles telephone numbers and PSTN connectivity
- **Architecture:** Designed to migrate services to cloud/datacenter without major refactoring

## Hardware Requirements

### Minimum (5 concurrent calls)

- **GPU:** NVIDIA RTX 3090 (24 GB VRAM)
- **CPU:** 8+ cores
- **RAM:** 64 GB system RAM
- **Storage:** 500 GB SSD (for models and database)
- **OS:** Ubuntu Server 24.04 LTS

### Recommended (10+ concurrent calls)

- **GPU:** NVIDIA RTX 4090 (24 GB VRAM)
- **CPU:** 16+ cores
- **RAM:** 128 GB system RAM
- **Storage:** 1 TB NVMe SSD
- **OS:** Ubuntu Server 24.04 LTS

See [docs/capacity-planning.md](docs/capacity-planning.md) for detailed resource analysis.

## Technology Stack

### Backend
- **Framework:** FastAPI with async/await
- **Database:** PostgreSQL (primary)
- **Cache:** Redis
- **ORM:** SQLAlchemy + Alembic migrations
- **Language:** Python 3.11+

### AI & Speech
- **LLM:** Ollama + Qwen 3 8B (configurable)
- **STT:** Faster-Whisper Large V3
- **TTS:** Kokoro (primary) / Piper (fallback)
- **RAG:** ChromaDB for vector search

### Frontend
- **Framework:** React 18+ with TypeScript
- **Build:** Vite
- **State:** React Context + modern hooks
- **Styling:** Modern CSS/Tailwind-compatible

### Telephony
- **Provider:** Twilio Voice
- **Integration:** WebHooks + TwiML

### Deployment
- **Containerization:** Docker & Docker Compose
- **Orchestration:** Docker Compose (MVP) → Kubernetes-ready (Future)
- **Reverse Proxy:** Nginx (SSL/TLS termination)

### Observability
- **Metrics:** Prometheus
- **Visualization:** Grafana
- **Logging:** Structured logging (JSON)

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Git
- NVIDIA drivers & Container Toolkit (for GPU support)
- Twilio account (free tier acceptable for testing)

### Local Development (5 minutes)

```bash
# Clone the repository
git clone https://github.com/changer0001/ai-restaurant-receptionist.git
cd ai-restaurant-receptionist

# Copy environment template
cp .env.example .env

# Edit .env with your Twilio credentials and local settings
# nano .env

# Start all services (Docker Compose handles dependencies)
docker compose up -d

# Wait ~30-60s for services to come up, then pull the models Ollama
# needs (it starts with none installed — this is a one-time step per
# ollama_data volume, ~5.3GB total):
docker compose exec ollama ollama pull qwen3:8b
docker compose exec ollama ollama pull nomic-embed-text

# Access the application
# - Dashboard: http://localhost
# - API Docs: http://localhost/docs
# - Prometheus: http://localhost/prometheus
# - Grafana: http://localhost/grafana
```

### First Restaurant Setup

1. **Open admin dashboard:** http://localhost
2. **Create account** (initial setup creates first restaurant owner)
3. **Create restaurant:**
   - Name, address, phone number
   - Twilio number (link purchased number)
   - Hours of operation
   - Transfer number (for escalations)
4. **Add FAQ/Knowledge:** Upload documents or manually add FAQs
5. **Configure Twilio webhook:** Point to your public IP/domain with webhook URL
6. **Test with a call!**

See [docs/setup.md](docs/setup.md) for detailed walkthrough.

## Project Structure

```
ai-restaurant-receptionist/
├── backend/                    # Python FastAPI backend
│   ├── app/
│   │   ├── api/               # REST endpoints
│   │   ├── core/              # Configuration, constants
│   │   ├── db/                # Database, migrations
│   │   ├── models/            # SQLAlchemy ORM models
│   │   ├── schemas/           # Pydantic request/response schemas
│   │   ├── services/          # Business logic
│   │   ├── providers/         # AI/LLM/STT/TTS abstractions
│   │   ├── rag/               # Vector search, embeddings
│   │   ├── prompts/           # System prompts
│   │   └── main.py            # FastAPI app entry point
│   ├── tests/                 # Unit & integration tests
│   ├── Dockerfile
│   └── pyproject.toml
│
├── frontend/                  # React TypeScript dashboard
│   ├── src/
│   │   ├── components/        # React components
│   │   ├── pages/             # Page components
│   │   ├── services/          # API clients
│   │   ├── types/             # TypeScript types
│   │   └── App.tsx
│   ├── Dockerfile
│   └── package.json
│
├── infrastructure/
│   ├── nginx/                 # Nginx config
│   ├── postgres/              # PostgreSQL init scripts
│   ├── prometheus/            # Prometheus config
│   └── grafana/               # Grafana dashboards
│
├── docs/                      # Documentation
│   ├── architecture.md        # Deep dive into architecture
│   ├── database.md            # Schema, ERD, migrations
│   ├── setup.md               # Local & production setup
│   ├── deployment.md          # Docker, scaling, cloud
│   ├── capacity-planning.md   # Resource analysis
│   ├── security.md            # Security guidelines
│   ├── production-hardening.md
│   ├── business-model.md      # SaaS pricing model
│   └── roadmap.md             # Future POS integrations
│
├── docker-compose.yml         # Local development stack
├── docker-compose.prod.yml    # Production-ready stack
├── .env.example               # Environment template
├── .gitignore
├── LICENSE
└── README.md
```

## Key Features

### Multi-Tenancy
- Complete restaurant isolation at database level
- Per-restaurant knowledge bases
- Per-restaurant Twilio number mapping
- Role-based access control (owner, manager, staff, admin)

### Voice Conversation
- Natural, conversational responses optimized for phones
- Silence detection and timeout handling
- Call transfer with seamless handoff
- Reservation state machine for structured collection
- Ordering detection and escalation

### Knowledge Management
- Upload documents (menus, policies, etc.)
- FAQ management interface
- RAG-powered grounded responses
- Prevents AI hallucination of restaurant info
- Configurable knowledge categories

### Reservations
- Collects: name, phone, date, time, party size, notes
- Stores requests in PostgreSQL
- SMS + email notifications to owner
- Confirmation to caller
- Reservation status tracking

### Admin Dashboard
- Call history with transcripts
- Reservation management
- Restaurant settings
- Knowledge base management
- User & role management
- Metrics & analytics

### Observability
- Prometheus metrics (calls, latency, GPU usage, etc.)
- Grafana dashboards
- Structured JSON logging
- Request tracing with IDs

## Configuration

All configuration via `.env` file. See `.env.example` for all options.

**Critical settings:**
- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` — Twilio credentials
- `DATABASE_URL` — PostgreSQL connection string
- `OLLAMA_BASE_URL` — Ollama server address
- `OLLAMA_MODEL` — LLM model (default: qwen3:8b)
- `WHISPER_MODEL` — STT model (default: large-v3)
- `JWT_SECRET` — JWT signing key (generate: `openssl rand -hex 32`)
- `PUBLIC_BASE_URL` — Your public domain (for Twilio webhooks)

## Development Workflow

### Running Tests
```bash
cd backend
pytest tests/ -v --cov
```

### Database Migrations
```bash
cd backend
# Create a migration after model changes
alembic revision --autogenerate -m "Add new column"

# Apply migrations
alembic upgrade head

# Downgrade if needed
alembic downgrade -1
```

### Type Checking
```bash
cd backend
mypy app --strict
```

### Linting
```bash
cd backend
ruff check app/
ruff format app/
```

## API Endpoints (Sample)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | User login |
| GET | `/api/restaurants` | List restaurants (authed) |
| GET | `/api/restaurants/{id}` | Get restaurant details |
| PATCH | `/api/restaurants/{id}` | Update restaurant settings |
| GET | `/api/restaurants/{id}/faqs` | List FAQs |
| POST | `/api/restaurants/{id}/faqs` | Create FAQ |
| GET | `/api/restaurants/{id}/reservations` | List reservations |
| POST | `/api/restaurants/{id}/reservations` | Create reservation |
| GET | `/api/restaurants/{id}/calls` | Call history |
| GET | `/api/calls/{id}/transcript` | Get call transcript |
| POST | `/webhooks/twilio/voice` | Twilio incoming call |
| POST | `/webhooks/twilio/status` | Call status updates |

See [docs/api.md](docs/api.md) for complete specification.

## Deployment

### Local (Development)
```bash
docker compose up -d
# Access on http://localhost
```

### Production
```bash
docker compose -f docker-compose.prod.yml up -d
# Behind firewall, with HTTPS, backups, monitoring
```

See [docs/deployment.md](docs/deployment.md) for:
- SSL/TLS setup
- Firewall configuration
- Backups and recovery
- Scaling to multiple GPU servers
- Cloud migration path

## Security

- ✅ HTTPS/TLS only in production
- ✅ JWT authentication
- ✅ Role-based authorization
- ✅ Tenant isolation at database level
- ✅ Twilio webhook validation
- ✅ No secrets in Git
- ✅ SQL injection protection (SQLAlchemy)
- ✅ Input validation (Pydantic)
- ✅ Rate limiting
- ✅ Secure password hashing (bcrypt)
- ✅ Audit logging

See [docs/security.md](docs/security.md) for detailed security model.

## Observability

**Prometheus metrics:**
- `calls_total` — Total calls received
- `calls_active` — Active concurrent calls
- `calls_transferred` — Calls escalated to humans
- `reservations_created` — Reservation requests created
- `ai_response_latency_ms` — Response time (STT→LLM→TTS)
- `stt_latency_ms` — Speech-to-text latency
- `llm_latency_ms` — LLM inference latency
- `tts_latency_ms` — Text-to-speech latency
- `gpu_utilization_percent` — GPU usage
- `gpu_memory_used_mb` — VRAM in use

**Grafana dashboards:**
- System (CPU, RAM, disk, network)
- GPU (utilization, VRAM, temperature)
- AI (latencies, model throughput)
- Business (calls, reservations, transfers)

Access Grafana at http://localhost/grafana (default: admin/admin)

## Troubleshooting

### GPU not detected
```bash
docker run --rm --gpus all nvidia/cuda:12.0-runtime nvidia-smi
docker compose exec backend nvidia-smi
```

### Ollama errors
```bash
docker compose logs ollama
# Check if model is downloaded: curl http://localhost:11434/api/tags
```

### Twilio webhook not working
- Verify `PUBLIC_BASE_URL` is publicly accessible
- Check firewall allows inbound HTTPS
- Verify Twilio webhook URL is set correctly
- Check logs: `docker compose logs api`

### Slow responses
- Monitor GPU: `nvidia-smi -l 1`
- Check CPU: `docker stats`
- Profile: `docker compose exec backend python -m cProfile`

See [docs/troubleshooting.md](docs/troubleshooting.md) for more.

## SaaS Roadmap

This MVP runs locally, but is designed for SaaS:

**Phase 1 (Current):** Local-first deployment
**Phase 2:** Multi-host GPU cluster support
**Phase 3:** Kubernetes-based SaaS platform
**Phase 4:** POS integrations (Clover, Toast, Square)
**Phase 5:** Advanced analytics & coaching

See [docs/roadmap.md](docs/roadmap.md) for detailed roadmap.

## License

MIT License — See LICENSE file

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for your changes
4. Submit a pull request

## Support

- **Issues:** GitHub Issues
- **Discussions:** GitHub Discussions
- **Documentation:** See `/docs` folder

## Author

Built by Burak Yilmaz

---

**Status:** MVP Foundation Phase (Active Development)

For the latest updates, visit the [GitHub repository](https://github.com/changer0001/ai-restaurant-receptionist)
