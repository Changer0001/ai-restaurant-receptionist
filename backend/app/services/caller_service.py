"""
Caller Memory

What the restaurant already knows about whoever is on the line, looked
up by the number they're calling from.

A regular who gets asked their name every single time is the clearest
sign an automated line isn't really paying attention — and the data to
avoid it is already there: past Call rows carry caller_number, and any
Reservation they've made carries their name and phone. This reads both
rather than adding a customer table, so memory works retroactively for
callers who rang before any of this existed.

Deliberately not an LLM summary of past calls: a name, a call count and
an upcoming booking are facts, and facts a restaurant repeats back to a
customer need to be exactly right. Retrieval keeps them exact.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Call, Reservation, ReservationStatusEnum

# Older than this and "welcome back" starts to sound like surveillance
# rather than service — a caller who rang once eight months ago does not
# expect to be remembered, and being greeted by name would unsettle more
# than it delights.
_RECOGNITION_WINDOW_DAYS = 180


def _as_utc(value: datetime) -> datetime:
    """
    Timestamps come back timezone-aware from Postgres but naive from
    SQLite, even for the same DateTime(timezone=True) column. Comparing
    the two raises, so naive values are read as the UTC they were stored
    as. Without this, deciding whether a booking is still upcoming works
    in production and raises everywhere else.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass
class CallerProfile:
    """What's known about this caller before they've said anything."""

    is_returning: bool = False
    name: Optional[str] = None
    previous_call_count: int = 0
    upcoming_reservation: Optional[Reservation] = None

    @property
    def known_by_name(self) -> bool:
        return bool(self.name)


async def get_caller_profile(
    db: AsyncSession, restaurant_id: str, caller_number: str, now: Optional[datetime] = None
) -> CallerProfile:
    """
    Look up what this restaurant knows about a caller. Never raises and
    never blocks a call: an unknown caller (or a lookup that finds
    nothing) simply produces an empty profile, and the call proceeds
    exactly as it does today.
    """
    now = now or datetime.now(timezone.utc)

    if not caller_number:
        return CallerProfile()

    cutoff = now - timedelta(days=_RECOGNITION_WINDOW_DAYS)

    call_count = await db.scalar(
        select(func.count())
        .select_from(Call)
        .where(
            Call.restaurant_id == restaurant_id,
            Call.caller_number == caller_number,
            Call.start_time >= cutoff,
        )
    )
    # This call's own row is created before the greeting is spoken, so
    # it's already in the table — a first-time caller counts 1 here.
    previous_calls = max((call_count or 0) - 1, 0)

    reservations = (
        (
            await db.execute(
                select(Reservation)
                .where(
                    Reservation.restaurant_id == restaurant_id,
                    Reservation.customer_phone == caller_number,
                )
                .order_by(Reservation.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )

    name = next((r.customer_name for r in reservations if r.customer_name), None)
    upcoming = next(
        (
            r
            for r in reservations
            if _as_utc(r.reservation_date) >= now and r.status != ReservationStatusEnum.CANCELLED
        ),
        None,
    )

    return CallerProfile(
        is_returning=previous_calls > 0 or bool(reservations),
        name=name,
        previous_call_count=previous_calls,
        upcoming_reservation=upcoming,
    )


def greeting_for(profile: CallerProfile, restaurant_name: str, default_greeting: str) -> str:
    """
    The opening line, personalized when there's something real to
    personalize with.

    Falls back to the restaurant's configured greeting whenever the
    caller isn't recognized — an unrecognized caller must never hear
    anything that hints a lookup happened at all.
    """
    if not profile.is_returning:
        return default_greeting

    if profile.known_by_name:
        return (
            f"Thanks for calling {restaurant_name}. "
            f"Good to hear from you again, {profile.name}. What can I do for you?"
        )

    return f"Thanks for calling {restaurant_name}, and welcome back. How can I help you today?"


def describe_reservation(reservation: Reservation) -> str:
    """
    Read a booking back the way a person would say it aloud — spoken by
    TTS, so no ISO dates and no 24-hour clock.
    """
    hour, minute = (int(part) for part in reservation.reservation_time.split(":"))
    period = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12 or 12
    time_phrase = f"{hour_12} {period}" if minute == 0 else f"{hour_12}:{minute:02d} {period}"
    # %-d rather than %d: "September 4th", not "September 04th".
    date_phrase = reservation.reservation_date.strftime("%A, %B %-d")

    people = "person" if reservation.party_size == 1 else "people"
    return (
        f"I have you down for {reservation.party_size} {people} "
        f"on {date_phrase} at {time_phrase}, under {reservation.customer_name}."
    )
