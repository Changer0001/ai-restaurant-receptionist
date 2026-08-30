"""
Call Record Business Logic

Persists everything the voice pipeline (app/voice/) needs recorded about
a live call: the Call row itself, its turn-by-turn transcript, and
state-machine events for debugging/auditing. Twilio's own CallSid is
used as the correlation key throughout (in URLs, lookups) rather than
minting a separate internal ID — it's already the unique, Twilio-issued
identifier every other webhook and API call about this call will carry.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.metrics import call_duration_seconds, calls_total
from app.db.models import Call, CallEvent, CallOutcomeEnum, CallTranscript


async def create_call(
    db: AsyncSession,
    restaurant_id: str,
    call_sid: str,
    caller_number: str,
    called_number: str,
) -> Call:
    call = Call(
        restaurant_id=restaurant_id,
        call_sid=call_sid,
        caller_number=caller_number,
        called_number=called_number,
        start_time=datetime.now(timezone.utc),
        outcome=CallOutcomeEnum.UNKNOWN,
    )
    db.add(call)
    await db.flush()
    await db.refresh(call)
    return call


async def get_call_by_sid(db: AsyncSession, call_sid: str) -> Optional[Call]:
    result = await db.execute(select(Call).where(Call.call_sid == call_sid))
    return result.scalar_one_or_none()


async def list_calls_for_restaurant(
    db: AsyncSession, restaurant_id: str, *, limit: int = 50, offset: int = 0
) -> list[Call]:
    """Most recent calls first — for the admin dashboard's call history
    view. Doesn't eager-load transcripts: a busy restaurant's call list
    could otherwise mean transferring hundreds of full transcripts
    nobody's looking at yet (see get_call_or_404 for the detail view)."""
    result = await db.execute(
        select(Call)
        .where(Call.restaurant_id == restaurant_id)
        .order_by(Call.start_time.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_call_or_404(db: AsyncSession, restaurant_id: str, call_id: str) -> Call:
    result = await db.execute(
        select(Call)
        .options(selectinload(Call.transcripts))
        .where(Call.id == call_id, Call.restaurant_id == restaurant_id)
    )
    call = result.scalar_one_or_none()
    if call is None:
        # 404 for a real call ID belonging to another restaurant too —
        # tenant isolation, same as every other restaurant-scoped lookup
        # in this codebase.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call


async def append_transcript_turn(
    db: AsyncSession, call: Call, role: str, message: str, confidence: Optional[float] = None
) -> CallTranscript:
    turn = CallTranscript(
        restaurant_id=call.restaurant_id,
        call_id=call.id,
        role=role,
        message=message,
        timestamp=datetime.now(timezone.utc),
        confidence=confidence,
    )
    db.add(turn)
    await db.flush()
    return turn


async def record_event(
    db: AsyncSession, call: Call, event_type: str, event_data: Optional[dict] = None
) -> CallEvent:
    event = CallEvent(
        restaurant_id=call.restaurant_id,
        call_id=call.id,
        event_type=event_type,
        event_data=event_data,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()
    return event


_TERMINAL_TWILIO_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}


async def ensure_call_finalized_from_status(
    db: AsyncSession, call_sid: str, twilio_status: str
) -> Optional[Call]:
    """
    Backstop for Twilio's status webhook: if the call's WebSocket
    disconnected abnormally (container restart, network blip) without
    our own CallSession.end() ever running, this makes sure the Call row
    still gets an end_time/duration instead of being left open forever.

    A no-op if the call was already finalized (checked via end_time,
    not outcome — a call the session correctly finalized as UNKNOWN-
    turned-CALL_ABANDONED must not be re-processed here) — the status
    callback and the WebSocket disconnect can arrive in either order.
    """
    call = await get_call_by_sid(db, call_sid)
    if call is None or call.end_time is not None or twilio_status not in _TERMINAL_TWILIO_STATUSES:
        return call

    outcome = (
        call.outcome if call.outcome != CallOutcomeEnum.UNKNOWN else CallOutcomeEnum.CALL_ABANDONED
    )
    return await finalize_call(
        db, call, outcome, was_transferred=call.was_transferred, was_escalated=call.was_escalated
    )


async def finalize_call(
    db: AsyncSession,
    call: Call,
    outcome: CallOutcomeEnum,
    *,
    was_transferred: bool = False,
    was_escalated: bool = False,
    transcript_text: Optional[str] = None,
) -> Call:
    """
    Mark a call as ended: sets end_time/duration, final outcome, and
    (optionally) a flattened plain-text transcript on the Call row
    itself — the turn-by-turn CallTranscript rows remain the detailed
    record; this is a convenience summary for quick display.
    """
    call.end_time = datetime.now(timezone.utc)
    # SQLite (used in tests) doesn't preserve timezone-awareness on a
    # round trip through the ORM the way Postgres's timestamptz does in
    # production — call.start_time can come back naive there. Normalize
    # before subtracting rather than assuming the backend round-tripped
    # tzinfo, so this works the same on both.
    start_time = call.start_time
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    call.duration_seconds = int((call.end_time - start_time).total_seconds())
    call.outcome = outcome
    call.was_transferred = was_transferred
    call.was_escalated = was_escalated
    if transcript_text is not None:
        call.transcript = transcript_text

    calls_total.labels(outcome=outcome.value).inc()
    call_duration_seconds.observe(call.duration_seconds)

    await db.flush()
    await db.refresh(call)
    return call
