# Roadmap

## Near-Term Gaps (found while building later phases)

These are honest, documented gaps — not implemented, not faked — found
while building on top of earlier phases. Listed here rather than left as
silent omissions.

### Structured holiday hours

There is no `RestaurantHolidayHours` model, despite being listed as a
model to design in the original spec. Only the regular weekly schedule
(`RestaurantHours`) exists.

**Current behavior:** a question naming a holiday (Christmas,
Thanksgiving, etc.) is deliberately excluded from the deterministic
hours-answering path (`app/conversation/hours_answer.py`'s
`looks_like_hours_question`) and instead routes to RAG. If a restaurant
has documented its holiday hours as a knowledge-base entry, RAG answers
it correctly; if not, RAG's grounding rule correctly says "I don't have
that information" rather than reciting regular hours that may not apply
that day. This is safe (never wrong), just not as precise as a dedicated
model would allow.

**To close the gap:** add `RestaurantHolidayHours` (restaurant_id, date,
is_closed, opening_time, closing_time, label) alongside `RestaurantHours`,
extend `hours_answer.py` to check it first for a given date, and add the
CRUD endpoints/UI for restaurant owners to manage it.

### Richer knowledge-document formats

`POST /api/restaurants/{id}/knowledge/upload` only accepts UTF-8 plain
text (`.txt`, `.md`) — no PDF or DOCX parsing. A restaurant with a PDF
menu or policy document has to convert it to plain text before
uploading. Adding real parsing (e.g. `pypdf` for PDF, `python-docx` for
DOCX) is straightforward to slot into
`app/api/endpoints/knowledge.py`'s upload handler without touching the
chunking/embedding/storage pipeline downstream of it.

### Energy-threshold voice activity detection

`app/audio/vad.py`'s `TurnDetector` decides a caller has finished
speaking using a simple energy threshold plus a silence hangover
window, not a trained VAD model (e.g. Silero VAD). It's a real,
working implementation — not a stub — but it will trigger falsely on
a caller pausing mid-sentence, background noise crossing the
threshold, or a quiet talker never crossing it at all.

**To close the gap:** swap `TurnDetector.add_frame()`'s energy
comparison for a small trained VAD model's frame-level speech
probability; the rest of `CallSession` (which only depends on
`add_frame() -> bool` and `pop_utterance() -> np.ndarray`) would not
need to change.

### No barge-in (estimated, not exact, playback-end timing)

`CallSession` has no interruption support: while the AI's response is
playing, inbound audio is ignored until an estimated "speaking until"
timestamp — computed from the outgoing audio's own duration — elapses.
Twilio's Media Streams protocol has a `mark` event that echoes back
once Twilio has actually finished playing a named chunk of audio,
which would give an exact signal instead of an estimate (and would be
the basis for real barge-in: stop synthesizing/playing as soon as
inbound speech is detected mid-response). Using the estimate is a
deliberate MVP scope-down — implementing it is straightforward
(send a `mark` after each outbound audio chunk, wait for the matching
event instead of a timestamp) but barge-in itself (interrupting speech
that's already mid-flight) is a larger feature.

### No visibility into permanently-failed notifications

Once a `Notification` row exhausts `NOTIFICATION_MAX_ATTEMPTS` (see
app/services/notification_service.py), it's left unsent with
`error_message` describing the last failure — safe (nothing is
silently dropped or endlessly retried), but there's no admin-facing way
to see that a restaurant owner never actually got told about a
reservation request short of querying the database directly. A restaurant
whose SMTP credentials expire, or whose Twilio number gets deactivated,
would have every notification quietly pile up unsent with no one
notified about the notifications themselves.

**To close the gap:** a `GET /api/restaurants/{id}/notifications`
endpoint (or a section of the Phase 8 admin dashboard) surfacing
`is_sent=False AND attempt_count >= NOTIFICATION_MAX_ATTEMPTS` rows,
and/or an operator-facing alert (e.g. a periodic count of permanently-
failed notifications fed into Prometheus/Grafana, Phase 9) rather than
requiring someone to think to look.

### Twilio's own call-control methods are unused

`TwilioTelephonyProvider.transfer_call()`, `end_call()`, `send_digits()`,
`record_call()`, and `health_check()` (all from Phase 1) are never
actually called anywhere in this codebase — live-call transfer works
entirely through TwiML (`CallSession` closes the Media Stream, Twilio's
own `<Connect>` → `<Redirect>` → `<Dial>` flow takes over; see
docs/architecture.md), not through Twilio's REST API. These methods are
also still synchronous Twilio SDK calls not wrapped in
`asyncio.to_thread` the way the new `send_sms()` is — the same blocking-
the-event-loop bug class Phase 5 fixed in `FasterWhisperSTTProvider`,
just never triggered because nothing calls them. Not fixed now because
fixing untested, unreachable code adds risk without a way to verify the
fix; worth cleaning up (or removing, if genuinely never needed) the
next time any of them gains a real caller.

### No automated frontend test suite

`frontend/package.json` has no test runner configured (no Vitest,
Jest, or React Testing Library) — `npm run type-check`, `npm run lint`,
and `npm run build` all passing cleanly is the quality gate for this
phase, backed by a one-time manual Playwright walkthrough of every page
(see DEVELOPMENT_STATUS.md's Phase 8 section) rather than a suite that
re-runs on every future change. Fine for the amount of UI logic this
dashboard currently has (mostly thin CRUD forms over the already
thoroughly-tested backend API), but a real gap once the frontend grows
meaningfully more interactive logic of its own.

**To close the gap:** add Vitest + React Testing Library, starting with
`AuthContext`'s token-refresh interceptor (`src/api/client.ts`) — the
single piece of frontend logic with real, non-trivial behavior (retry-
once-then-redirect) worth a unit test independent of the backend.

### No platform-admin view in the dashboard

The backend already distinguishes `platform_admin` from restaurant
roles (`list_restaurants_for_platform_admin`, `require_restaurant_*`
allowing admins through every tenant check), but the dashboard's UI
has no multi-restaurant switcher or platform-wide view — `AuthContext`
assumes a single `user.restaurant_id` throughout. A platform admin can
still authenticate and hit any restaurant's API directly, just not
through this UI.

### No manual reservation creation from the dashboard

Staff can list, view, and confirm/decline reservation requests, but
can't create one by hand for a walk-in or a phone call the AI didn't
handle (see `app/schemas/reservation.py`'s docstring) — every
reservation in this system still originates from a live AI-handled
call. Adding a `POST /api/restaurants/{id}/reservations` plus a "New
Reservation" form would close this without touching the conversation
engine's own reservation-creation path.

### No infrastructure-level metrics (host, PostgreSQL)

`app/core/metrics.py` covers application/business metrics (calls,
reservations, notifications, signature failures), but there's no
`node_exporter` (host CPU/memory/disk) or `postgres_exporter`
(connection pool, query latency, replication lag) container in
`docker-compose.yml` — `infrastructure/prometheus/prometheus.yml`'s
scrape config for both was removed in Phase 9 rather than left pointing
at nonexistent targets (see that phase's notes in
DEVELOPMENT_STATUS.md). Both are standard, well-documented images
(`prom/node-exporter`, `prometheuscommunity/postgres-exporter`) with a
small, well-known configuration surface — adding them is a
docker-compose service + a `DATA_SOURCE_NAME` connection string for
Postgres, plus re-adding their scrape jobs to `prometheus.yml` pointing
at the real service names.

### Grafana dashboard not rendered in a live instance

`infrastructure/grafana/provisioning/dashboards/ai-receptionist-
overview.json` was written to Grafana's documented dashboard-JSON
schema and validated for syntactic correctness and internally
consistent panel/grid layout, but never actually loaded into a running
Grafana to confirm it renders as intended — Docker image pulls aren't
reachable in the sandbox this was built in (see Phase 5's/Phase 9's
notes on the same constraint). The metrics it queries are real and
covered by `tests/test_metrics.py`; what's unverified is Grafana's own
rendering of the dashboard JSON. Worth a quick visual check
(`docker compose up -d prometheus grafana`, http://localhost:3000,
default login admin/admin) the first time this actually runs somewhere
with registry access.

### Reservation availability

Reservations created by this system are *requests*, not confirmed
bookings against real table inventory — there is no availability check.
This is intentional for the MVP (see docs/architecture.md and the spec)
but is worth tracking as a real product gap: a restaurant that fills up
still has this system accept every request, and it becomes the
restaurant staff's job to decline overbooked ones. A future phase could
integrate actual table-management/inventory data to reject or flag
requests that exceed capacity at checkout time.

## Future POS Integrations

Planned integrations, not yet started: **Clover**, **Toast**, **Square**.

None of this is implemented. It's documented here so the core AI
receptionist is architected in a way that doesn't have to be reworked
when it is.

### Target architecture

```
AI Conversation Engine
        |
   Order Service
        |
   POS Adapter (interface)
        |
   +----+----+----+
   |    |    |    |
Clover Toast Square (future)
```

The `Order Service` and `POS Adapter` interface don't exist yet — there
is no order-taking capability in this MVP at all (an ordering call is
detected and transferred to a human, per `app/conversation/engine.py`,
never handled by the AI). When POS integration is built:

- **POS-specific logic must never leak into the conversation engine.**
  `app/conversation/` should only ever call a generic `POSAdapter`
  interface (menu retrieval, item availability, prices, modifiers, order
  creation, order status) — the same abstraction pattern already used for
  `LLMProvider`, `STTProvider`, `TTSProvider`, `TelephonyProvider`, and
  `EmbeddingProvider` in this codebase. A Clover-specific quirk belongs in
  `app/providers/pos/clover_provider.py`, not in the engine.
- Menu data retrieved from a POS should likely flow into the same RAG
  knowledge base already built in Phase 3 (`app/rag/`), rather than a
  parallel retrieval path — a caller asking "what's on the menu" and a
  caller asking "do you have outdoor seating" should be answered through
  the same grounding mechanism.
- Order creation is a write operation with real financial consequences —
  it should go through the same "controlled tool, application validates,
  application executes" pattern as `create_reservation_request` in
  `app/conversation/tools.py`, never a free-form LLM-to-POS call.

## SaaS Evolution

See docs/architecture.md's "Scaling Strategy" section — this MVP's
provider-abstraction pattern and stateless API design are already built
with a multi-tenant SaaS deployment in mind, not just the local homelab
target. Concrete SaaS work (billing/metering, self-serve tenant
provisioning beyond the current `/api/auth/register` flow, per-tenant
usage limits) is out of scope until there's a second real deployment
target to design against.
