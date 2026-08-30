"""
Tests for app.core.metrics — verifies each business metric's real call
site actually updates it, reading the metric's own current value via
prometheus_client's public `.collect()` API rather than trusting that
the instrumented line merely runs without raising.

prometheus_client's default registry is a process-wide singleton, so
every metric here can carry state left over from other tests in the
same run (they all live in the same pytest process). Every assertion
below is therefore a *delta* — captured before the operation under
test, compared to after — rather than an assertion on an absolute
value, so these are correct regardless of what else already ran.
"""

from app.conversation.state import ReservationDraft
from app.conversation.tools import create_reservation_request
from app.core.metrics import (
    active_calls,
    call_duration_seconds,
    calls_total,
    notifications_sent_total,
    reservation_status_changes_total,
    twilio_signature_failures_total,
)
from app.db.models import CallOutcomeEnum, Notification, ReservationStatusEnum
from app.services import call_service, notification_service, reservation_service
from tests.fakes import FakeEmailProvider, FakeTelephonyProvider, ScriptedLLMProvider
from tests.test_call_session import _make_session
from tests.test_voice_webhooks import _use_test_telephony_provider


def _counter_value(counter, **labels) -> float:
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == labels:
                return sample.value
    return 0.0


def _gauge_value(gauge) -> float:
    for metric in gauge.collect():
        for sample in metric.samples:
            if sample.name == gauge._name:
                return sample.value
    return 0.0


def _histogram_count(histogram) -> float:
    for metric in histogram.collect():
        for sample in metric.samples:
            if sample.name.endswith("_count"):
                return sample.value
    return 0.0


async def test_finalize_call_increments_calls_total_and_duration(db_session, restaurant):
    before = _counter_value(calls_total, outcome=CallOutcomeEnum.FAQ_ANSWERED.value)
    before_hist = _histogram_count(call_duration_seconds)

    call = await call_service.create_call(db_session, restaurant.id, "CA_metrics_1", "+1", "+2")
    await call_service.finalize_call(db_session, call, CallOutcomeEnum.FAQ_ANSWERED)

    after = _counter_value(calls_total, outcome=CallOutcomeEnum.FAQ_ANSWERED.value)
    after_hist = _histogram_count(call_duration_seconds)
    assert after == before + 1
    assert after_hist == before_hist + 1


async def test_call_session_start_and_end_track_active_calls(
    db_session, restaurant, vector_db, embedding_provider
):
    before = _gauge_value(active_calls)

    llm = ScriptedLLMProvider([], default="FAQ")
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm
    )

    await session.start()
    assert _gauge_value(active_calls) == before + 1

    await session.end()
    assert _gauge_value(active_calls) == before


async def test_call_session_end_without_start_does_not_go_negative(
    db_session, restaurant, vector_db, embedding_provider
):
    before = _gauge_value(active_calls)

    llm = ScriptedLLMProvider([], default="FAQ")
    session, _sender = await _make_session(
        db_session, restaurant, vector_db, embedding_provider, llm
    )

    # end() without a preceding start() — e.g. a connection that never
    # got a "start" event before disconnecting.
    await session.end()

    assert _gauge_value(active_calls) == before


async def test_create_reservation_request_increments_pending_status(db_session, restaurant):
    before = _counter_value(reservation_status_changes_total, status="pending")

    draft = ReservationDraft(
        customer_name="Jane Diner",
        customer_phone="+15551234567",
        reservation_date="2026-09-04",
        reservation_time="19:00",
        party_size=4,
    )
    await create_reservation_request(db_session, restaurant, draft, call_sid="CA_metrics_2")

    after = _counter_value(reservation_status_changes_total, status="pending")
    assert after == before + 1


async def test_update_reservation_status_increments_new_status(db_session, restaurant):
    draft = ReservationDraft(
        customer_name="Jane Diner",
        customer_phone="+15551234567",
        reservation_date="2026-09-04",
        reservation_time="19:00",
        party_size=4,
    )
    reservation = await create_reservation_request(db_session, restaurant, draft, call_sid=None)
    await db_session.commit()

    before = _counter_value(reservation_status_changes_total, status="confirmed")

    await reservation_service.update_reservation_status(
        db_session, restaurant.id, reservation.id, ReservationStatusEnum.CONFIRMED
    )

    after = _counter_value(reservation_status_changes_total, status="confirmed")
    assert after == before + 1


async def test_notification_sent_increments_sent_outcome(db_session, restaurant):
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="email",
        recipient=restaurant.email,
        message="hello",
        is_sent=False,
    )
    db_session.add(notification)
    await db_session.commit()

    before = _counter_value(notifications_sent_total, channel="email", outcome="sent")

    await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), FakeEmailProvider()
    )

    after = _counter_value(notifications_sent_total, channel="email", outcome="sent")
    assert after == before + 1


async def test_notification_failure_increments_failed_outcome(db_session, restaurant):
    notification = Notification(
        restaurant_id=restaurant.id,
        notification_type="email",
        recipient="bad@example.com",
        message="hello",
        is_sent=False,
    )
    db_session.add(notification)
    await db_session.commit()

    before = _counter_value(notifications_sent_total, channel="email", outcome="failed")

    await notification_service.process_pending_notifications(
        db_session, FakeTelephonyProvider(), FakeEmailProvider(fail_for={"bad@example.com"})
    )

    after = _counter_value(notifications_sent_total, channel="email", outcome="failed")
    assert after == before + 1


async def test_invalid_twilio_signature_increments_failure_counter(client):
    _use_test_telephony_provider(client)
    before = _counter_value(twilio_signature_failures_total)

    client.post(
        "/webhooks/twilio/voice",
        data={"CallSid": "CA_x", "From": "+1", "To": "+2"},
        headers={"X-Twilio-Signature": "not-a-real-signature"},
    )

    after = _counter_value(twilio_signature_failures_total)
    assert after == before + 1
