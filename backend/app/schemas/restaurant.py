"""Restaurant request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RestaurantRead(BaseModel):
    id: str
    name: str
    description: Optional[str]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]
    phone_number: Optional[str]
    website: Optional[str]
    email: Optional[str]
    timezone: str
    transfer_number: Optional[str]
    menu_url: Optional[str]
    ai_greeting: Optional[str]
    stt_vocabulary: Optional[str]
    takes_reservations: Optional[bool]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RestaurantUpdate(BaseModel):
    """All fields optional — PATCH semantics, only provided fields change."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    address: Optional[str] = Field(default=None, max_length=500)
    city: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=50)
    postal_code: Optional[str] = Field(default=None, max_length=20)
    country: Optional[str] = Field(default=None, max_length=100)
    phone_number: Optional[str] = Field(default=None, max_length=20)
    website: Optional[str] = Field(default=None, max_length=500)
    email: Optional[EmailStr] = None
    timezone: Optional[str] = Field(default=None, max_length=50)
    transfer_number: Optional[str] = Field(default=None, max_length=20)
    menu_url: Optional[str] = Field(default=None, max_length=500)
    ai_greeting: Optional[str] = None
    # Both left out of a PATCH mean "don't change"; see Restaurant in
    # app/db/models.py for what NULL means once stored.
    stt_vocabulary: Optional[str] = None
    takes_reservations: Optional[bool] = None
    is_active: Optional[bool] = None
