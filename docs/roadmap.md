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
