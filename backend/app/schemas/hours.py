"""Restaurant operating hours schemas."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class HoursEntry(BaseModel):
    """One day's operating hours. day_of_week: 0=Monday .. 6=Sunday."""

    day_of_week: int = Field(ge=0, le=6)
    opening_time: str = Field(description="HH:MM, 24-hour")
    closing_time: str = Field(description="HH:MM, 24-hour")
    is_closed: bool = False

    @field_validator("opening_time", "closing_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError("Time must be in 24-hour HH:MM format, e.g. '09:00' or '22:30'")
        return v


class HoursRead(HoursEntry):
    id: str

    model_config = ConfigDict(from_attributes=True)


class HoursSetRequest(BaseModel):
    """
    Full-week replace: the caller submits the complete weekly schedule
    (0-7 entries, one per day) and it atomically replaces whatever hours
    existed before. Matches the PUT semantics on
    /api/restaurants/{id}/hours in the API design.
    """

    hours: list[HoursEntry] = Field(max_length=7)

    @field_validator("hours")
    @classmethod
    def validate_unique_days(cls, v: list[HoursEntry]) -> list[HoursEntry]:
        days = [entry.day_of_week for entry in v]
        if len(days) != len(set(days)):
            raise ValueError("Each day_of_week must appear at most once")
        return v
