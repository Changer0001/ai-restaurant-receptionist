"""Tests for app.conversation.reservation_extraction."""

import json
from datetime import datetime

from app.conversation.reservation_extraction import extract_reservation_fields
from app.conversation.state import ReservationDraft
from tests.dates import FUTURE_DATE
from tests.fakes import ScriptedLLMProvider

_NOW = datetime(2026, 8, 30)  # a Sunday


async def test_extracts_all_fields_from_one_message():
    llm = ScriptedLLMProvider(
        [],
        default=json.dumps(
            {
                "customer_name": "Jane Smith",
                "customer_phone": "555-123-4567",
                "reservation_date": FUTURE_DATE,
                "reservation_time": "19:00",
                "party_size": 4,
                "special_notes": None,
            }
        ),
    )
    draft = await extract_reservation_fields(llm, "Test Bistro", ReservationDraft(), "Jane Smith, table for 4 Friday at 7, 555-123-4567", "America/New_York", _NOW)

    assert draft.customer_name == "Jane Smith"
    assert draft.customer_phone == "555-123-4567"
    assert draft.reservation_date == FUTURE_DATE
    assert draft.reservation_time == "19:00"
    assert draft.party_size == 4
    assert draft.is_complete()


async def test_merges_incrementally_across_turns():
    llm = ScriptedLLMProvider([], default=json.dumps({"customer_name": "Ada", "party_size": None}))
    partial = ReservationDraft(reservation_date=FUTURE_DATE, reservation_time="19:00", party_size=2)

    draft = await extract_reservation_fields(llm, "Test Bistro", partial, "It's under Ada", "America/New_York", _NOW)

    # New field merged in, existing fields preserved (extraction response
    # omits date/time/party_size — those must not be wiped out).
    assert draft.customer_name == "Ada"
    assert draft.reservation_date == FUTURE_DATE
    assert draft.reservation_time == "19:00"
    assert draft.party_size == 2


async def test_unparseable_response_keeps_draft_unchanged():
    llm = ScriptedLLMProvider([], default="not json at all")
    original = ReservationDraft(customer_name="Ada")

    draft = await extract_reservation_fields(llm, "Test Bistro", original, "blah", "America/New_York", _NOW)

    assert draft == original


async def test_invalid_party_size_is_dropped_not_merged():
    llm = ScriptedLLMProvider([], default=json.dumps({"party_size": "a lot of people"}))
    original = ReservationDraft(party_size=None)

    draft = await extract_reservation_fields(llm, "Test Bistro", original, "a lot of us", "America/New_York", _NOW)

    assert draft.party_size is None  # invalid value never merged


async def test_party_size_over_max_is_rejected():
    llm = ScriptedLLMProvider([], default=json.dumps({"party_size": 500}))
    draft = await extract_reservation_fields(llm, "Test Bistro", ReservationDraft(), "500 people", "America/New_York", _NOW)
    assert draft.party_size is None


async def test_bool_is_not_accepted_as_party_size():
    # JSON `true`/`false` parse to Python bool, which is an int subclass —
    # must not be silently accepted as a party size.
    llm = ScriptedLLMProvider([], default=json.dumps({"party_size": True}))
    draft = await extract_reservation_fields(llm, "Test Bistro", ReservationDraft(), "yes", "America/New_York", _NOW)
    assert draft.party_size is None


async def test_past_date_is_rejected():
    llm = ScriptedLLMProvider([], default=json.dumps({"reservation_date": "2020-01-01"}))
    draft = await extract_reservation_fields(llm, "Test Bistro", ReservationDraft(), "last year sometime", "America/New_York", _NOW)
    assert draft.reservation_date is None


async def test_malformed_date_is_rejected():
    llm = ScriptedLLMProvider([], default=json.dumps({"reservation_date": "next Friday"}))
    draft = await extract_reservation_fields(llm, "Test Bistro", ReservationDraft(), "next Friday", "America/New_York", _NOW)
    assert draft.reservation_date is None


async def test_malformed_time_is_rejected():
    llm = ScriptedLLMProvider([], default=json.dumps({"reservation_time": "7pm"}))
    draft = await extract_reservation_fields(llm, "Test Bistro", ReservationDraft(), "7pm", "America/New_York", _NOW)
    assert draft.reservation_time is None


async def test_implausible_phone_is_rejected():
    llm = ScriptedLLMProvider([], default=json.dumps({"customer_phone": "12"}))
    draft = await extract_reservation_fields(llm, "Test Bistro", ReservationDraft(), "my number is 12", "America/New_York", _NOW)
    assert draft.customer_phone is None


async def test_valid_phone_with_formatting_is_accepted():
    llm = ScriptedLLMProvider([], default=json.dumps({"customer_phone": "(555) 123-4567"}))
    draft = await extract_reservation_fields(llm, "Test Bistro", ReservationDraft(), "555 123 4567", "America/New_York", _NOW)
    assert draft.customer_phone == "(555) 123-4567"


async def test_blank_name_is_treated_as_unknown():
    llm = ScriptedLLMProvider([], default=json.dumps({"customer_name": "   "}))
    draft = await extract_reservation_fields(llm, "Test Bistro", ReservationDraft(), "...", "America/New_York", _NOW)
    assert draft.customer_name is None
