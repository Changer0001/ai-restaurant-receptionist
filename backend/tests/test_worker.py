"""
Tests for app.worker.run_once() — the single-iteration unit the
standalone worker's poll loop (main()) repeats forever. main() itself
is untested here: it's a thin `while True: run_once(); sleep()` shell
around already-tested logic, not worth simulating an infinite loop for.

These monkeypatch the module's own provider/session-maker construction
so run_once() exercises real wiring (settings -> provider construction
-> notification_service) against the isolated test database, rather
than a real Twilio/SMTP account.
"""

import app.worker as worker
from app.db.models import Notification
from tests.fakes import FakeEmailProvider, FakeTelephonyProvider


def _patch_worker_dependencies(monkeypatch, session_maker, email_provider):
    monkeypatch.setattr(worker, "async_session_maker", session_maker)
    monkeypatch.setattr(worker, "TwilioTelephonyProvider", lambda: FakeTelephonyProvider())

    async def fake_get_email_provider():
        return email_provider

    monkeypatch.setattr(worker, "get_email_provider", fake_get_email_provider)


async def test_run_once_sends_a_due_email_notification(
    session_maker, db_session, restaurant, monkeypatch
):
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

    fake_email = FakeEmailProvider()
    _patch_worker_dependencies(monkeypatch, session_maker, fake_email)

    attempted = await worker.run_once()

    assert attempted == 1
    assert fake_email.sent == [(restaurant.email, "New reservation request", "Party of 4 at 7pm")]

    # run_once() committed the change through its own session — db_session
    # still has this row cached from the insert above, so it must be
    # explicitly refreshed to see what the other session wrote.
    await db_session.refresh(notification)
    assert notification.is_sent is True


async def test_run_once_returns_zero_when_nothing_is_due(session_maker, monkeypatch):
    _patch_worker_dependencies(monkeypatch, session_maker, FakeEmailProvider())

    attempted = await worker.run_once()

    assert attempted == 0
