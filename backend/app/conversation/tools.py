"""
Controlled Application Tools

The LLM never writes to the database directly. Its output (an intent
label, extracted reservation fields) is a *request*; these functions are
what actually validate and execute an action, per the spec's tool-call
architecture. Kept here rather than inline in engine.py so each is
independently testable and so the engine's state-machine logic — which
*decides* when a tool runs — stays separate from the tools themselves.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.state import ReservationDraft
from app.core.metrics import reservation_status_changes_total
from app.db.models import Notification, Reservation, ReservationStatusEnum, Restaurant


async def create_reservation_request(
    db: AsyncSession,
    restaurant: Restaurant,
    draft: ReservationDraft,
    call_sid: str | None,
) -> Reservation:
    """
    Persist a reservation *request* (status=PENDING — never CONFIRMED;
    this system has no table-inventory integration, so it cannot
    guarantee availability) and queue owner notifications.

    Actually sending those notifications (SMS via Twilio, email via SMTP)
    is Phase 6 — this creates the outbox rows a Phase 6 worker will pick
    up and send, which is a real, persisted side effect, not a stub.
    """
    if not draft.is_complete():
        raise ValueError(
            f"Cannot create a reservation with missing fields: {draft.missing_fields()}"
        )
    # draft.is_complete() guarantees these are set — assert narrows the
    # type for the type checker and fails loudly if that invariant is
    # ever violated, rather than passing None through to strptime.
    assert draft.reservation_date is not None
    assert draft.reservation_time is not None

    reservation_date = datetime.strptime(draft.reservation_date, "%Y-%m-%d").replace(
        tzinfo=ZoneInfo(restaurant.timezone)
    )

    reservation = Reservation(
        restaurant_id=restaurant.id,
        customer_name=draft.customer_name,
        customer_phone=draft.customer_phone,
        reservation_date=reservation_date,
        reservation_time=draft.reservation_time,
        party_size=draft.party_size,
        special_notes=draft.special_notes,
        status=ReservationStatusEnum.PENDING,
        call_sid=call_sid,
    )
    db.add(reservation)
    await db.flush()
    await db.refresh(reservation)
    reservation_status_changes_total.labels(status=reservation.status.value).inc()

    message = (
        f"New reservation request for {restaurant.name}: {draft.customer_name}, "
        f"party of {draft.party_size}, {draft.reservation_date} at {draft.reservation_time}. "
        f"Phone: {draft.customer_phone}."
        + (f" Notes: {draft.special_notes}" if draft.special_notes else "")
    )

    if restaurant.phone_number:
        db.add(
            Notification(
                restaurant_id=restaurant.id,
                notification_type="sms",
                recipient=restaurant.phone_number,
                message=message,
                is_sent=False,
            )
        )
    if restaurant.email:
        db.add(
            Notification(
                restaurant_id=restaurant.id,
                notification_type="email",
                recipient=restaurant.email,
                subject=f"New reservation request — {restaurant.name}",
                message=message,
                is_sent=False,
            )
        )
    await db.flush()

    return reservation
