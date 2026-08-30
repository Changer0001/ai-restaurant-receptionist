"""
Hours Question Answering

"What time do you close?" and "what are your hours?" are answered
directly from the structured RestaurantHours table, not via the LLM or
RAG search. This is the get_restaurant_hours() tool from the spec's
tool-call architecture (section 18), applied to the single most common
and highest-stakes FAQ category: a wrong guess about hours is worse than
almost any other mistake this system could make, and hours are exactly
the kind of small, structured, frequently-asked data a dedicated tool
should answer deterministically rather than leaving to text generation.
"""

from datetime import datetime
from typing import Optional

from app.db.models import RestaurantHours

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_HOURS_KEYWORDS = ("hour", "open", "close", "closing", "opening")
_CLOSING_KEYWORDS = ("close", "closing")

# There is no RestaurantHolidayHours model (or any other structured
# holiday-hours data) in this MVP's schema — only the regular weekly
# schedule. So a question naming a holiday must NOT be answered from
# RestaurantHours: that table has no idea a restaurant closes early on
# Thanksgiving, and confidently reciting regular hours for a holiday
# would be actively wrong, not just unhelpful. These questions fall
# through to RAG instead, where an operator can document actual holiday
# hours as a knowledge-base entry; with nothing documented, RAG's own
# grounding rule correctly answers "I don't have that information" rather
# than a guess. See docs/roadmap.md for adding a first-class holiday
# hours model.
_HOLIDAY_KEYWORDS = (
    "christmas",
    "thanksgiving",
    "new year",
    "easter",
    "halloween",
    "holiday",
    "memorial day",
    "labor day",
    "independence day",
    "4th of july",
    "fourth of july",
)


def looks_like_hours_question(message: str) -> bool:
    lowered = message.lower()
    if any(kw in lowered for kw in _HOLIDAY_KEYWORDS):
        return False
    return any(kw in lowered for kw in _HOURS_KEYWORDS)


def looks_like_closing_time_question(message: str) -> bool:
    lowered = message.lower()
    return any(kw in lowered for kw in _CLOSING_KEYWORDS)


def _format_time_12h(time_str: str) -> str:
    """'22:00' -> '10 PM', '09:30' -> '9:30 AM', '00:00' -> '12 AM'."""
    hour, minute = (int(part) for part in time_str.split(":"))
    period = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12 or 12
    return f"{hour_12} {period}" if minute == 0 else f"{hour_12}:{minute:02d} {period}"


def format_hours_summary(hours: list[RestaurantHours]) -> str:
    """
    Summarize a week of hours, grouping consecutive days that share
    identical opening/closing times into one phrase — e.g. "Monday to
    Friday 11 AM to 10 PM. Saturday and Sunday 12 PM to 11 PM." — rather
    than reading out seven separate lines.
    """
    if not hours:
        return "I don't have our hours on file — let me connect you with someone who can help."

    by_day = {h.day_of_week: h for h in hours}
    groups: list[dict] = []

    for day in range(7):
        entry = by_day.get(day)
        key = "closed" if (entry is None or entry.is_closed) else (entry.opening_time, entry.closing_time)
        if groups and groups[-1]["key"] == key:
            groups[-1]["days"].append(day)
        else:
            groups.append({"key": key, "days": [day]})

    phrases = []
    for group in groups:
        days = group["days"]
        if len(days) == 1:
            day_label = _DAY_NAMES[days[0]]
        elif len(days) == 2:
            day_label = f"{_DAY_NAMES[days[0]]} and {_DAY_NAMES[days[-1]]}"
        else:
            day_label = f"{_DAY_NAMES[days[0]]} to {_DAY_NAMES[days[-1]]}"

        if group["key"] == "closed":
            phrases.append(f"{day_label} we're closed")
        else:
            opening, closing = group["key"]
            phrases.append(f"{day_label} {_format_time_12h(opening)} to {_format_time_12h(closing)}")

    return ". ".join(phrases) + "."


def answer_closing_time_tonight(hours: list[RestaurantHours], now: datetime) -> str:
    """Answers "what time do you close tonight?" for the caller's current day."""
    today_entry: Optional[RestaurantHours] = next((h for h in hours if h.day_of_week == now.weekday()), None)

    if today_entry is None or today_entry.is_closed:
        return "We're closed today."

    return f"We close tonight at {_format_time_12h(today_entry.closing_time)}."
