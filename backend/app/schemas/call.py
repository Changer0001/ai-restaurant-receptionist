"""Call history/transcript schemas — read-only from the admin API's
perspective; calls are created and updated entirely by the voice
pipeline (app/voice/session.py), never through this API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models import CallOutcomeEnum


class CallRead(BaseModel):
    id: str
    restaurant_id: str
    call_sid: str
    caller_number: str
    called_number: str
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[int]
    outcome: CallOutcomeEnum
    was_transferred: bool
    was_escalated: bool
    recording_path: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class CallTranscriptTurnRead(BaseModel):
    role: str
    message: str
    timestamp: datetime
    confidence: Optional[float]

    model_config = ConfigDict(from_attributes=True)


class CallDetailRead(CallRead):
    """The list view (CallRead) omits the full turn-by-turn transcript —
    fetched separately per call, since a busy restaurant's call list
    could otherwise mean transferring hundreds of transcripts nobody's
    looking at yet."""

    transcript: Optional[str]
    transcripts: list[CallTranscriptTurnRead] = []
