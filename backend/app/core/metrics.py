"""
Prometheus Business Metrics

Phase 1 only ever mounted /metrics (app/main.py) — that exposes
prometheus_client's own auto-registered process/platform metrics
(GC stats, memory, CPU), but nothing about what this application
actually does. Every metric defined here has a real call site that
increments/observes it — see each docstring — verified by tests that
read the metric's own current value via prometheus_client's public
`.collect()` API, not just "the line runs without raising."

Cardinality: deliberately no restaurant_id label anywhere. Prometheus
expects low-cardinality label values; in a real multi-tenant deployment
a restaurant_id label would make every metric's series count grow
without bound as tenants are added — the classic Prometheus cardinality
trap. Per-restaurant numbers belong in the database, queryable through
the admin API/dashboard (already built in Phase 8), not as Prometheus
label values. See docs/architecture.md's decision log for the full
rationale.
"""

from prometheus_client import Counter, Gauge, Histogram

# Incremented once per call, in call_service.finalize_call() — the
# single place every call (successful or abandoned) is finalized,
# regardless of which code path got it there.
calls_total = Counter(
    "calls_total",
    "Total calls finalized, by final outcome",
    ["outcome"],
)

# Observed alongside calls_total, in the same call to finalize_call().
call_duration_seconds = Histogram(
    "call_duration_seconds",
    "Call duration in seconds, start to finalization",
    buckets=(5, 15, 30, 60, 120, 300, 600),
)

# Incremented in CallSession.start() (Media Stream connected and the
# greeting has been queued), decremented in CallSession.end() (Media
# Stream disconnected, Call row finalized) — a live count of calls
# currently in progress. CallSession tracks whether it actually
# incremented this before decrementing, so a connection that never
# reaches start() (e.g. an unknown call_sid, rejected before a
# CallSession is even constructed) can never make this go negative.
active_calls = Gauge(
    "active_calls",
    "Calls currently connected (Media Stream open, not yet finalized)",
)

# Incremented once per status a reservation ever holds: PENDING at
# creation (app/conversation/tools.py.create_reservation_request) and
# again on every subsequent transition
# (app/services/reservation_service.py.update_reservation_status) — so
# summing this by status over a time window answers "how many
# reservations were created vs. confirmed vs. declined" without needing
# a restaurant_id label.
reservation_status_changes_total = Counter(
    "reservation_status_changes_total",
    "Reservation status transitions, including the initial PENDING at creation",
    ["status"],
)

# Incremented once per send attempt in
# app/services/notification_service.py._send_one() — "sent" on success,
# "failed" on a retryable failure, "permanently_failed" once a
# notification has exhausted NOTIFICATION_MAX_ATTEMPTS on that attempt.
notifications_sent_total = Counter(
    "notifications_sent_total",
    "Notification send attempts, by channel (sms/email) and outcome",
    ["channel", "outcome"],
)

# Incremented in app/api/endpoints/twilio_webhooks.py._validated_form()
# whenever a webhook's X-Twilio-Signature fails validation — this is
# the entire authorization boundary for that router (see its own
# module docstring), so a nonzero rate here in production is worth
# alerting on, not just logging.
twilio_signature_failures_total = Counter(
    "twilio_signature_failures_total",
    "Twilio webhook requests rejected for an invalid or missing signature",
)
