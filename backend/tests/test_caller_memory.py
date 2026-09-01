"""Tests for app.services.caller_service — recognizing returning callers."""

from datetime import datetime, timedelta, timezone

from app.db.models import Reservation, ReservationStatusEnum
from app.services import call_service, caller_service

_CALLER = "+15551234567"
_DEFAULT_GREETING = "Thank you for calling Mal Al Sham. How can I help you today?"


async def _make_reservation(db_session, restaurant, name, when, party_size=2, status=None):
    reservation = Reservation(
        restaurant_id=restaurant.id,
        customer_name=name,
        customer_phone=_CALLER,
        reservation_date=when,
        reservation_time=f"{when.hour:02d}:{when.minute:02d}",
        party_size=party_size,
        status=status or ReservationStatusEnum.PENDING,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


async def test_first_time_caller_is_not_treated_as_returning(db_session, restaurant):
    await call_service.create_call(
        db_session, restaurant.id, "CA_first", _CALLER, restaurant.phone_number
    )

    profile = await caller_service.get_caller_profile(db_session, restaurant.id, _CALLER)

    # The current call's own row already exists by the time the greeting
    # is chosen, so it must not count as a previous call.
    assert profile.previous_call_count == 0
    assert profile.is_returning is False
    assert (
        caller_service.greeting_for(profile, restaurant.name, _DEFAULT_GREETING) == _DEFAULT_GREETING
    )


async def test_returning_caller_is_recognized(db_session, restaurant):
    await call_service.create_call(
        db_session, restaurant.id, "CA_old", _CALLER, restaurant.phone_number
    )
    await call_service.create_call(
        db_session, restaurant.id, "CA_new", _CALLER, restaurant.phone_number
    )

    profile = await caller_service.get_caller_profile(db_session, restaurant.id, _CALLER)

    assert profile.previous_call_count == 1
    assert profile.is_returning is True
    greeting = caller_service.greeting_for(profile, restaurant.name, _DEFAULT_GREETING)
    assert "welcome back" in greeting.lower()


async def test_caller_who_has_booked_before_is_greeted_by_name(db_session, restaurant):
    await call_service.create_call(
        db_session, restaurant.id, "CA_1", _CALLER, restaurant.phone_number
    )
    await _make_reservation(
        db_session, restaurant, "Mike", datetime.now(timezone.utc) + timedelta(days=1)
    )

    profile = await caller_service.get_caller_profile(db_session, restaurant.id, _CALLER)

    assert profile.name == "Mike"
    assert "Mike" in caller_service.greeting_for(profile, restaurant.name, _DEFAULT_GREETING)


async def test_a_different_number_is_not_recognized(db_session, restaurant):
    await call_service.create_call(
        db_session, restaurant.id, "CA_1", _CALLER, restaurant.phone_number
    )
    await _make_reservation(
        db_session, restaurant, "Mike", datetime.now(timezone.utc) + timedelta(days=1)
    )

    profile = await caller_service.get_caller_profile(db_session, restaurant.id, "+15559999999")

    assert profile.is_returning is False
    assert profile.name is None


async def test_upcoming_reservation_is_found_and_past_ones_are_not(db_session, restaurant):
    now = datetime.now(timezone.utc)
    await _make_reservation(db_session, restaurant, "Mike", now - timedelta(days=30))
    upcoming = await _make_reservation(
        db_session, restaurant, "Mike", now + timedelta(days=1), party_size=5
    )

    profile = await caller_service.get_caller_profile(db_session, restaurant.id, _CALLER, now=now)

    assert profile.upcoming_reservation is not None
    assert profile.upcoming_reservation.id == upcoming.id


async def test_cancelled_reservations_are_not_offered_back_to_the_caller(db_session, restaurant):
    now = datetime.now(timezone.utc)
    await _make_reservation(
        db_session,
        restaurant,
        "Mike",
        now + timedelta(days=1),
        status=ReservationStatusEnum.CANCELLED,
    )

    profile = await caller_service.get_caller_profile(db_session, restaurant.id, _CALLER, now=now)

    assert profile.upcoming_reservation is None


async def test_a_caller_from_long_ago_is_not_greeted_as_a_regular(db_session, restaurant):
    """
    Being remembered from eight months back reads as surveillance rather
    than service, so recognition has a window.
    """
    call = await call_service.create_call(
        db_session, restaurant.id, "CA_ancient", _CALLER, restaurant.phone_number
    )
    call.start_time = datetime.now(timezone.utc) - timedelta(days=400)
    await db_session.flush()

    profile = await caller_service.get_caller_profile(db_session, restaurant.id, _CALLER)

    assert profile.previous_call_count == 0


async def test_reservation_is_described_the_way_it_would_be_said_aloud(db_session, restaurant):
    when = datetime(2026, 9, 4, 19, 0, tzinfo=timezone.utc)
    reservation = await _make_reservation(db_session, restaurant, "Mike", when, party_size=5)

    spoken = caller_service.describe_reservation(reservation)

    assert "5 people" in spoken
    assert "7 PM" in spoken  # not 19:00
    assert "Friday, September 4" in spoken  # not 2026-09-04
    assert "Mike" in spoken


async def test_a_table_for_one_is_not_described_as_one_people(db_session, restaurant):
    when = datetime(2026, 9, 4, 19, 0, tzinfo=timezone.utc)
    reservation = await _make_reservation(db_session, restaurant, "Mike", when, party_size=1)

    assert "1 person" in caller_service.describe_reservation(reservation)
