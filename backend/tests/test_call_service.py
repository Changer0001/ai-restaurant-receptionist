"""Tests for app.services.call_service."""

from app.db.models import CallOutcomeEnum
from app.services import call_service


async def test_create_call_persists_expected_fields(db_session, restaurant):
    call = await call_service.create_call(
        db_session, restaurant.id, "CA123", "+15551234567", "+15559876543"
    )
    await db_session.commit()

    assert call.restaurant_id == restaurant.id
    assert call.call_sid == "CA123"
    assert call.caller_number == "+15551234567"
    assert call.called_number == "+15559876543"
    assert call.outcome == CallOutcomeEnum.UNKNOWN
    assert call.end_time is None


async def test_get_call_by_sid_found_and_not_found(db_session, restaurant):
    await call_service.create_call(db_session, restaurant.id, "CA_findme", "+1", "+2")
    await db_session.commit()

    found = await call_service.get_call_by_sid(db_session, "CA_findme")
    assert found is not None
    assert found.call_sid == "CA_findme"

    missing = await call_service.get_call_by_sid(db_session, "CA_does_not_exist")
    assert missing is None


async def test_append_transcript_turn(db_session, restaurant):
    call = await call_service.create_call(db_session, restaurant.id, "CA1", "+1", "+2")
    await call_service.append_transcript_turn(
        db_session, call, "caller", "Hello there", confidence=0.92
    )
    await call_service.append_transcript_turn(db_session, call, "assistant", "Hi! How can I help?")
    await db_session.commit()

    from sqlalchemy import select

    from app.db.models import CallTranscript

    result = await db_session.execute(
        select(CallTranscript)
        .where(CallTranscript.call_id == call.id)
        .order_by(CallTranscript.timestamp)
    )
    turns = list(result.scalars().all())
    assert len(turns) == 2
    assert turns[0].role == "caller"
    assert turns[0].message == "Hello there"
    assert turns[0].confidence == 0.92
    assert turns[1].role == "assistant"


async def test_record_event(db_session, restaurant):
    call = await call_service.create_call(db_session, restaurant.id, "CA1", "+1", "+2")
    await call_service.record_event(
        db_session, call, "reservation_created", {"reservation_id": "abc"}
    )
    await db_session.commit()

    from sqlalchemy import select

    from app.db.models import CallEvent

    result = await db_session.execute(select(CallEvent).where(CallEvent.call_id == call.id))
    events = list(result.scalars().all())
    assert len(events) == 1
    assert events[0].event_type == "reservation_created"
    assert events[0].event_data == {"reservation_id": "abc"}


async def test_finalize_call_sets_end_time_duration_and_outcome(db_session, restaurant):
    call = await call_service.create_call(db_session, restaurant.id, "CA1", "+1", "+2")
    await db_session.commit()

    finalized = await call_service.finalize_call(
        db_session,
        call,
        CallOutcomeEnum.RESERVATION_CREATED,
        was_transferred=False,
        was_escalated=False,
        transcript_text="caller: hi\nassistant: hello",
    )
    await db_session.commit()

    assert finalized.end_time is not None
    assert finalized.duration_seconds is not None
    assert finalized.duration_seconds >= 0
    assert finalized.outcome == CallOutcomeEnum.RESERVATION_CREATED
    assert finalized.transcript == "caller: hi\nassistant: hello"


async def test_ensure_call_finalized_from_status_is_a_noop_if_already_finalized(
    db_session, restaurant
):
    """The status webhook must never clobber an outcome the live session
    already correctly determined (e.g. RESERVATION_CREATED) with a bare
    CALL_ABANDONED just because CallStatus=="completed" arrived."""
    call = await call_service.create_call(db_session, restaurant.id, "CA1", "+1", "+2")
    await call_service.finalize_call(db_session, call, CallOutcomeEnum.RESERVATION_CREATED)
    await db_session.commit()

    result = await call_service.ensure_call_finalized_from_status(db_session, "CA1", "completed")
    await db_session.commit()

    assert result.outcome == CallOutcomeEnum.RESERVATION_CREATED  # untouched


async def test_ensure_call_finalized_from_status_backstops_an_unfinalized_call(
    db_session, restaurant
):
    """If the WebSocket disconnected abnormally without CallSession.end()
    ever running, the status webhook must still close out the call."""
    call = await call_service.create_call(db_session, restaurant.id, "CA1", "+1", "+2")
    await db_session.commit()
    assert call.end_time is None

    result = await call_service.ensure_call_finalized_from_status(db_session, "CA1", "completed")
    await db_session.commit()

    assert result is not None
    assert result.end_time is not None
    assert result.outcome == CallOutcomeEnum.CALL_ABANDONED


async def test_ensure_call_finalized_from_status_ignores_non_terminal_status(
    db_session, restaurant
):
    await call_service.create_call(db_session, restaurant.id, "CA1", "+1", "+2")
    await db_session.commit()

    result = await call_service.ensure_call_finalized_from_status(db_session, "CA1", "ringing")
    await db_session.commit()

    assert result.end_time is None  # "ringing" is not terminal — must not finalize


async def test_ensure_call_finalized_from_status_unknown_call_sid_returns_none(db_session):
    result = await call_service.ensure_call_finalized_from_status(
        db_session, "CA_nonexistent", "completed"
    )
    assert result is None
