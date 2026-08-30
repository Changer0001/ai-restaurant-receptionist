"""
Tests for app.services.notification_service — the Phase 6 worker logic
that actually sends the SMS/email Notification rows Phase 4's
create_reservation_request() queues.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db.models import Notification, RestaurantPhoneNumber
from app.services import notification_service
from tests.fakes import FakeEmailProvider, FakeTelephonyProvider

_TWILIO_NUMBER = "+15559876543"


async def _add_twilio_number(db_session, restaurant, number: str = _TWILIO_NUMBER):
    db_session.add(
        RestaurantPhoneNumber(restaurant_id=restaurant.id, phone_number=number, is_active=True)
    )
    await db_session.commit()


async def test_sends_a_due_sms_notification(db_session, restaurant):
    await _add_twilio_number(db_session, restaurant)
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="sms",
        recipient=restaurant.phone_number,
        message="New reservation request for Test Bistro",
        is_sent=False,
    )
    db_session.add(notification)
    await db_session.commit()

    telephony = FakeTelephonyProvider()
    email_provider = FakeEmailProvider()

    attempted = await notification_service.process_pending_notifications(
        db_session, telephony, email_provider
    )
    await db_session.commit()

    assert attempted == 1
    assert telephony.sent_sms == [(restaurant.phone_number, _TWILIO_NUMBER, notification.message)]
    await db_session.refresh(notification)
    assert notification.is_sent is True
    assert notification.sent_at is not None
    assert notification.attempt_count == 1
    assert notification.error_message is None


async def test_sends_a_due_email_notification(db_session, restaurant):
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="email",
        recipient=restaurant.email,
        subject="New reservation request",
        message="Party of 4 at 7pm",
        is_sent=False,
    )
    db_session.add(notification)
    await db_session.commit()

    telephony = FakeTelephonyProvider()
    email_provider = FakeEmailProvider()

    attempted = await notification_service.process_pending_notifications(
        db_session, telephony, email_provider
    )
    await db_session.commit()

    assert attempted == 1
    assert email_provider.sent == [
        (restaurant.email, "New reservation request", notification.message)
    ]
    await db_session.refresh(notification)
    assert notification.is_sent is True


async def test_already_sent_notifications_are_skipped(db_session, restaurant):
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="email",
        recipient=restaurant.email,
        message="already handled",
        is_sent=True,
        sent_at=datetime.now(timezone.utc),
    )
    db_session.add(notification)
    await db_session.commit()

    attempted = await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), FakeEmailProvider()
    )

    assert attempted == 0


async def test_a_failed_send_records_the_error_and_increments_attempt_count(db_session, restaurant):
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="email",
        recipient="bad@example.com",
        message="hello",
        is_sent=False,
    )
    db_session.add(notification)
    await db_session.commit()

    email_provider = FakeEmailProvider(fail_for={"bad@example.com"})

    attempted = await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), email_provider
    )
    await db_session.commit()

    assert attempted == 1
    await db_session.refresh(notification)
    assert notification.is_sent is False
    assert notification.attempt_count == 1
    assert "simulated SMTP failure" in notification.error_message


async def test_a_notification_still_in_its_backoff_window_is_not_retried_yet(
    db_session, restaurant
):
    """A failed attempt one second ago, with a base backoff of 60s,
    must not be retried immediately on the next sweep."""
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="email",
        recipient="bad@example.com",
        message="hello",
        is_sent=False,
        attempt_count=1,
        error_message="previous failure",
    )
    db_session.add(notification)
    await db_session.commit()
    await db_session.refresh(notification)  # populate the DB-generated updated_at

    attempted = await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), FakeEmailProvider()
    )

    assert attempted == 0
    await db_session.refresh(notification)
    assert notification.attempt_count == 1  # untouched — not due yet


async def test_a_notification_past_its_backoff_window_is_retried(
    db_session, restaurant, monkeypatch
):
    monkeypatch.setattr(settings, "NOTIFICATION_BACKOFF_BASE_SECONDS", 1)
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="email",
        recipient=restaurant.email,
        message="hello",
        is_sent=False,
        attempt_count=1,
        error_message="previous failure",
    )
    db_session.add(notification)
    await db_session.commit()

    # Backdate updated_at past the (now 1-second) backoff window without
    # waiting in real time.
    notification.updated_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    await db_session.commit()

    email_provider = FakeEmailProvider()
    attempted = await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), email_provider
    )
    await db_session.commit()

    assert attempted == 1
    await db_session.refresh(notification)
    assert notification.is_sent is True
    assert notification.attempt_count == 2


async def test_notification_permanently_fails_after_max_attempts(
    db_session, restaurant, monkeypatch
):
    monkeypatch.setattr(settings, "NOTIFICATION_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "NOTIFICATION_BACKOFF_BASE_SECONDS", 0)
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="email",
        recipient="bad@example.com",
        message="hello",
        is_sent=False,
    )
    db_session.add(notification)
    await db_session.commit()

    email_provider = FakeEmailProvider(fail_for={"bad@example.com"})

    # Attempt 1: fails, attempt_count -> 1, still under the cap of 2.
    await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), email_provider
    )
    await db_session.commit()
    await db_session.refresh(notification)
    assert notification.attempt_count == 1

    # Attempt 2: fails, attempt_count -> 2, now at the cap.
    await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), email_provider
    )
    await db_session.commit()
    await db_session.refresh(notification)
    assert notification.attempt_count == 2

    # A third sweep must not attempt it again — it has exhausted its retries.
    attempted = await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), email_provider
    )
    assert attempted == 0
    await db_session.refresh(notification)
    assert notification.attempt_count == 2  # untouched
    assert notification.is_sent is False


async def test_sms_without_an_active_restaurant_number_fails_gracefully(db_session, restaurant):
    """No RestaurantPhoneNumber configured at all for this restaurant —
    there's nothing to send SMS "from"."""
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="sms",
        recipient=restaurant.phone_number,
        message="hello",
        is_sent=False,
    )
    db_session.add(notification)
    await db_session.commit()

    attempted = await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), FakeEmailProvider()
    )
    await db_session.commit()

    assert attempted == 1
    await db_session.refresh(notification)
    assert notification.is_sent is False
    assert "no active Twilio number" in notification.error_message


async def test_disabled_sms_channel_is_left_completely_untouched(
    db_session, restaurant, monkeypatch
):
    monkeypatch.setattr(settings, "FEATURE_SMS_NOTIFICATIONS", False)
    await _add_twilio_number(db_session, restaurant)
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="sms",
        recipient=restaurant.phone_number,
        message="hello",
        is_sent=False,
    )
    db_session.add(notification)
    await db_session.commit()

    attempted = await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), FakeEmailProvider()
    )

    assert attempted == 0
    await db_session.refresh(notification)
    assert notification.attempt_count == 0  # never even attempted
    assert notification.is_sent is False


async def test_disabled_email_channel_is_left_completely_untouched(
    db_session, restaurant, monkeypatch
):
    monkeypatch.setattr(settings, "FEATURE_EMAIL_NOTIFICATIONS", False)
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="email",
        recipient=restaurant.email,
        message="hello",
        is_sent=False,
    )
    db_session.add(notification)
    await db_session.commit()

    attempted = await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), FakeEmailProvider()
    )

    assert attempted == 0
    await db_session.refresh(notification)
    assert notification.attempt_count == 0


async def test_unknown_notification_type_fails_instead_of_crashing_the_sweep(
    db_session, restaurant
):
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="carrier_pigeon",
        recipient="n/a",
        message="hello",
        is_sent=False,
    )
    db_session.add(notification)
    await db_session.commit()

    attempted = await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), FakeEmailProvider()
    )
    await db_session.commit()

    assert attempted == 1
    await db_session.refresh(notification)
    assert notification.is_sent is False
    assert "Unknown notification_type" in notification.error_message


async def test_processes_multiple_due_notifications_in_one_sweep(db_session, restaurant):
    await _add_twilio_number(db_session, restaurant)
    db_session.add_all(
        [
            Notification(
                restaurant_id=restaurant.id,
                notification_type="sms",
                recipient=restaurant.phone_number,
                message="one",
                is_sent=False,
            ),
            Notification(
                restaurant_id=restaurant.id,
                notification_type="email",
                recipient=restaurant.email,
                message="two",
                is_sent=False,
            ),
        ]
    )
    await db_session.commit()

    telephony = FakeTelephonyProvider()
    email_provider = FakeEmailProvider()
    attempted = await notification_service.process_pending_notifications(
        db_session, telephony, email_provider
    )

    assert attempted == 2
    assert len(telephony.sent_sms) == 1
    assert len(email_provider.sent) == 1


@pytest.mark.parametrize("attempt_count,expected", [(1, 60), (2, 120), (3, 240), (10, 3600)])
def test_backoff_delay_is_exponential_and_capped(attempt_count, expected):
    assert notification_service._next_attempt_delay_seconds(attempt_count) == expected
