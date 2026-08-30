"""Reservation request schemas.

Reservations are created entirely by the conversation engine
(app/conversation/tools.py) during a live call — this API is read/status-
update only; there is no POST endpoint for staff to create a reservation
by hand (out of scope for the MVP, see docs/roadmap.md).
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models import ReservationStatusEnum


class ReservationRead(BaseModel):
    id: str
    restaurant_id: str
    customer_name: str
    customer_phone: str
    customer_email: Optional[str]
    reservation_date: datetime
    reservation_time: str
    party_size: int
    special_notes: Optional[str]
    status: ReservationStatusEnum
    call_sid: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReservationStatusUpdate(BaseModel):
    status: ReservationStatusEnum
