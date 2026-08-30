"""Tests for app.conversation.hours_answer."""

from dataclasses import dataclass
from datetime import datetime

from app.conversation.hours_answer import (
    answer_closing_time_tonight,
    format_hours_summary,
    looks_like_closing_time_question,
    looks_like_hours_question,
)


@dataclass
class _FakeHours:
    day_of_week: int
    opening_time: str
    closing_time: str
    is_closed: bool = False


_STANDARD_WEEK = [
    _FakeHours(0, "11:00", "22:00"),
    _FakeHours(1, "11:00", "22:00"),
    _FakeHours(2, "11:00", "22:00"),
    _FakeHours(3, "11:00", "22:00"),
    _FakeHours(4, "11:00", "22:00"),
    _FakeHours(5, "12:00", "23:00"),
    _FakeHours(6, "12:00", "23:00"),
]


def test_format_hours_summary_groups_consecutive_identical_days():
    summary = format_hours_summary(_STANDARD_WEEK)
    assert summary == "Monday to Friday 11 AM to 10 PM. Saturday and Sunday 12 PM to 11 PM."


def test_format_hours_summary_handles_closed_day():
    week = [_FakeHours(0, "", "", is_closed=True)] + _STANDARD_WEEK[1:]
    summary = format_hours_summary(week)
    assert summary.startswith("Monday we're closed.")


def test_format_hours_summary_empty_hours():
    assert "don't have our hours" in format_hours_summary([])


def test_format_hours_summary_single_odd_day_out():
    week = list(_STANDARD_WEEK)
    week[2] = _FakeHours(2, "16:00", "22:00")  # Wednesday opens later
    summary = format_hours_summary(week)
    assert "Monday" in summary and "Tuesday" in summary and "Wednesday" in summary
    assert "4 PM" in summary


def test_answer_closing_time_tonight_open():
    friday = datetime(2026, 9, 4)  # a Friday
    assert answer_closing_time_tonight(_STANDARD_WEEK, friday) == "We close tonight at 10 PM."


def test_answer_closing_time_tonight_closed():
    monday = datetime(2026, 8, 31)  # a Monday
    week = [_FakeHours(0, "", "", is_closed=True)] + _STANDARD_WEEK[1:]
    assert answer_closing_time_tonight(week, monday) == "We're closed today."


def test_answer_closing_time_tonight_no_entry_for_day():
    monday = datetime(2026, 8, 31)
    assert answer_closing_time_tonight(_STANDARD_WEEK[1:], monday) == "We're closed today."


def test_looks_like_hours_question():
    assert looks_like_hours_question("What time do you close tonight?")
    assert looks_like_hours_question("Are you open on Sundays?")
    assert not looks_like_hours_question("Do you have vegetarian options?")


def test_holiday_questions_are_excluded_from_the_structured_hours_path():
    """
    There's no holiday-hours data model in this MVP — only the regular
    weekly schedule. A holiday question must route to RAG (where an
    operator can document actual holiday hours, or the grounding
    fallback correctly admits "I don't have that information") rather
    than being answered from RestaurantHours, which has no idea a
    restaurant closes early on Thanksgiving.
    """
    assert not looks_like_hours_question("Are you open on Christmas?")
    assert not looks_like_hours_question("What are your Thanksgiving hours?")
    assert not looks_like_hours_question("Are you closed for the holiday?")


def test_looks_like_closing_time_question():
    assert looks_like_closing_time_question("What time do you close?")
    assert not looks_like_closing_time_question("What are your hours?")
