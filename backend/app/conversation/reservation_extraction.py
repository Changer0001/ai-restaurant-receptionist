"""
Reservation Slot Extraction

Turns a caller's free-form utterance into structured reservation fields.
The LLM's output here is never trusted directly — every field is
validated before merging it into the draft, matching the spec's tool-call
principle (the model requests a value, the application validates it)
even though this isn't a discrete "tool call" in the free-form-JSON sense.
An LLM hallucinating a malformed date or a wildly implausible party size
must not corrupt the draft or reach the database.
"""

import json
import re
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from app.conversation.state import ReservationDraft
from app.conversation.text_utils import extract_json_object, strip_thinking
from app.prompts import render_prompt
from app.providers.llm.base import LLMProvider

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_MAX_PARTY_SIZE = 30  # beyond this, it's a private event, not a phone reservation


async def extract_reservation_fields(
    llm: LLMProvider,
    restaurant_name: str,
    draft: ReservationDraft,
    latest_message: str,
    timezone_name: str,
    now: datetime,
) -> ReservationDraft:
    """
    Extract and merge new reservation details from the caller's latest
    message into the existing draft. Invalid or unparseable fields are
    dropped rather than merged — a field that fails validation is treated
    as "still unknown," so the engine asks for it again instead of
    silently accepting bad data.
    """
    prompt = render_prompt(
        "reservation_extraction.txt",
        restaurant_name=restaurant_name,
        today_date=now.strftime("%Y-%m-%d"),
        today_weekday=now.strftime("%A"),
        timezone=timezone_name,
        known_fields_json=json.dumps(asdict(draft)),
        latest_message=latest_message,
    )
    raw = await llm.generate(prompt, temperature=0.0)
    parsed = extract_json_object(strip_thinking(raw))

    if parsed is None:
        return draft

    updates = {
        "customer_name": _validate_name(parsed.get("customer_name")),
        "customer_phone": _validate_phone(parsed.get("customer_phone")),
        "reservation_date": _validate_date(parsed.get("reservation_date"), now),
        "reservation_time": _validate_time(parsed.get("reservation_time")),
        "party_size": _validate_party_size(parsed.get("party_size")),
        "special_notes": _validate_notes(parsed.get("special_notes")),
    }

    merged = asdict(draft)
    for field, value in updates.items():
        if value is not None:
            merged[field] = value

    return ReservationDraft(**merged)


def _validate_name(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _validate_phone(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    digits = re.sub(r"\D", "", value)
    # A plausible phone number has at least 7 digits (short local numbers)
    # and no more than 15 (E.164's max) — reject obvious garbage without
    # forcing a specific country format on a caller.
    if 7 <= len(digits) <= 15:
        return value.strip()
    return None


def _validate_date(value: object, now: datetime) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    if parsed_date < now.date():
        # A model resolving "Friday" to a Friday that already passed this
        # week is a real, observed failure mode — never accept a
        # reservation request for a date that's already gone.
        return None
    return value


def _validate_time(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value if _TIME_RE.match(value) else None


def _validate_party_size(value: object) -> Optional[int]:
    if isinstance(value, bool):  # bool is an int subclass — exclude explicitly
        return None
    if not isinstance(value, int):
        return None
    if 1 <= value <= _MAX_PARTY_SIZE:
        return value
    return None


def _validate_notes(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None
