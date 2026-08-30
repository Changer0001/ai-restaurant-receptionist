"""
Notification Sending Service

Phase 4's `create_reservation_request` (app/conversation/tools.py)
already queues Notification rows (SMS to the restaurant's own phone,
email to the restaurant's own address) as soon as a reservation request
is created. This module is what actually sends them — called by the
standalone worker (app/worker.py) on a poll loop, not inline during the
live call: notification delivery has nothing to do with a phone call's
latency budget, and a slow or down SMTP server / Twilio outage must
never add delay to what a caller hears.

Retries use capped exponential backoff (see _next_attempt_delay_seconds
below), computed from each row's already-persisted attempt_count and
its own updated_at column, which doubles as "last attempted at" — it's
bumped on every write to the row (TimestampMixin's onupdate=func.now()),
and every send attempt here, success or failure, writes the row.
Exhausting NOTIFICATION_MAX_ATTEMPTS leaves the row unsent with
error_message describing the last failure, for a human to notice —
never silently dropped.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.metrics import notifications_sent_total
from app.db.models import Notification
from app.providers.email.base import EmailProvider
from app.providers.telephony.base import TelephonyProvider
from app.services import restaurant_service

logger = logging.getLogger(__name__)


def _next_attempt_delay_seconds(attempt_count: int) -> float:
    """Exponential backoff after `attempt_count` failed attempts:
    base * 2^(attempt_count-1), capped at the configured maximum."""
    delay = settings.NOTIFICATION_BACKOFF_BASE_SECONDS * (2 ** max(attempt_count - 1, 0))
    return float(min(delay, settings.NOTIFICATION_BACKOFF_MAX_SECONDS))


def _is_due(notification: Notification, now: datetime) -> bool:
    if notification.attempt_count == 0:
        return True
    last_attempt = notification.updated_at
    # SQLite (tests) doesn't round-trip tzinfo the way Postgres's
    # timestamptz does — normalize before comparing, same pattern as
    # call_service.finalize_call's duration calculation.
    if last_attempt.tzinfo is None:
        last_attempt = last_attempt.replace(tzinfo=timezone.utc)
    delay = _next_attempt_delay_seconds(notification.attempt_count)
    return now >= last_attempt + timedelta(seconds=delay)


async def _send_one(
    db: AsyncSession,
    notification: Notification,
    telephony: TelephonyProvider,
    email_provider: EmailProvider,
) -> None:
    notification.attempt_count += 1
    try:
        if notification.notification_type == "sms":
            from_number = await restaurant_service.get_active_phone_number_for_restaurant(
                db, notification.restaurant_id
            )
            if not from_number:
                raise ValueError(
                    f"Restaurant {notification.restaurant_id} has no active Twilio "
                    "number to send SMS from"
                )
            await telephony.send_sms(
                to=notification.recipient, from_=from_number, body=notification.message
            )
        elif notification.notification_type == "email":
            await email_provider.send_email(
                to=notification.recipient,
                subject=notification.subject or "Notification",
                body=notification.message,
            )
        else:
            # Not a transient failure — retrying won't help an
            # unrecognized type, but this still counts against
            # attempt_count/error_message like any other failure rather
            # than needing a separate code path, since it should never
            # happen (every writer of Notification rows uses "sms" or
            # "email") and is worth surfacing exactly the same way.
            raise ValueError(f"Unknown notification_type: {notification.notification_type!r}")
    except Exception as e:
        notification.error_message = str(e)[:2000]
        if notification.attempt_count >= settings.NOTIFICATION_MAX_ATTEMPTS:
            notifications_sent_total.labels(
                channel=notification.notification_type, outcome="permanently_failed"
            ).inc()
            logger.error(
                f"Notification {notification.id} ({notification.notification_type}) "
                f"permanently failed after {notification.attempt_count} attempts: {e}"
            )
        else:
            notifications_sent_total.labels(
                channel=notification.notification_type, outcome="failed"
            ).inc()
            logger.warning(
                f"Notification {notification.id} ({notification.notification_type}) "
                f"attempt {notification.attempt_count} failed: {e}"
            )
    else:
        notification.is_sent = True
        notification.sent_at = datetime.now(timezone.utc)
        notification.error_message = None
        notifications_sent_total.labels(
            channel=notification.notification_type, outcome="sent"
        ).inc()

    await db.flush()


async def process_pending_notifications(
    db: AsyncSession,
    telephony: TelephonyProvider,
    email_provider: EmailProvider,
    *,
    limit: int = 100,
) -> int:
    """
    Send every due, unsent notification (up to `limit`). Returns the
    number of sends attempted (success or failure) — a caller wanting
    to distinguish those should inspect `is_sent` afterward.

    Excludes: rows already sent, rows that have exhausted
    NOTIFICATION_MAX_ATTEMPTS (permanently failed — see _send_one),
    rows still inside their current backoff window, and — respecting
    the FEATURE_SMS_NOTIFICATIONS / FEATURE_EMAIL_NOTIFICATIONS flags —
    a known channel ("sms"/"email") an operator has administratively
    disabled. A disabled channel's rows are left completely untouched
    (not counted as attempts, not marked failed) so flipping the flag
    back on later picks them up exactly as if nothing had happened.

    A row with any *other* notification_type is not something a
    feature flag governs — every writer of Notification rows only ever
    uses "sms" or "email" (see app/conversation/tools.py), so anything
    else is a genuine anomaly. Rather than silently ignore it forever
    the same way a disabled channel is skipped, it's still picked up
    and attempted, so _send_one's "Unknown notification_type" failure
    surfaces it via the normal error_message/attempt_count path instead
    of it going unnoticed.
    """
    disabled_types = set()
    if not settings.FEATURE_SMS_NOTIFICATIONS:
        disabled_types.add("sms")
    if not settings.FEATURE_EMAIL_NOTIFICATIONS:
        disabled_types.add("email")

    result = await db.execute(
        select(Notification)
        .where(
            Notification.is_sent.is_(False),
            Notification.attempt_count < settings.NOTIFICATION_MAX_ATTEMPTS,
        )
        .order_by(Notification.created_at)
        .limit(limit)
    )
    candidates = list(result.scalars().all())

    now = datetime.now(timezone.utc)
    due = [n for n in candidates if n.notification_type not in disabled_types and _is_due(n, now)]

    for notification in due:
        await _send_one(db, notification, telephony, email_provider)

    return len(due)
