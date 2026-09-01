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

# "Are you open today?" is a yes/no question, and reciting the whole
# week back at the caller is a non-answer — a person would say "yes,
# until ten tonight." Same for "what time do you open tomorrow?": the
# caller asked about one specific day, so answer about that day.
_OPEN_NOW_KEYWORDS = (
    "open today",
    "open now",
    "open right now",
    "open at the moment",
    "open yet",
    "still open",
)
_TOMORROW_KEYWORD = "tomorrow"

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


def looks_like_open_now_question(message: str) -> bool:
    """"Are you open today?" / "are you still open?" — a yes/no question."""
    lowered = message.lower()
    return any(kw in lowered for kw in _OPEN_NOW_KEYWORDS)


def looks_like_tomorrow_question(message: str) -> bool:
    return _TOMORROW_KEYWORD in message.lower()


def _format_time_12h(time_str: str) -> str:
    """'22:00' -> '10 PM', '09:30' -> '9:30 AM', '00:00' -> '12 AM'."""
    hour, minute = (int(part) for part in time_str.split(":"))
    period = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12 or 12
    return f"{hour_12} {period}" if minute == 0 else f"{hour_12}:{minute:02d} {period}"


def _entry_for_day(hours: list[RestaurantHours], day_index: int) -> Optional[RestaurantHours]:
    return next((h for h in hours if h.day_of_week == day_index), None)


def _is_open_on(entry: Optional[RestaurantHours]) -> bool:
    return entry is not None and not entry.is_closed


def _as_minutes(time_str: str) -> int:
    hour, minute = (int(part) for part in time_str.split(":"))
    return hour * 60 + minute


def _next_open_day(hours: list[RestaurantHours], now: datetime) -> Optional[tuple[str, str]]:
    """
    The next day the restaurant is open after today, as (when, opening
    time) — e.g. ("tomorrow", "09:00") or ("Saturday", "10:00"). None if
    nothing in the week is open (no hours on file at all).
    """
    for offset in range(1, 8):
        day_index = (now.weekday() + offset) % 7
        entry = _entry_for_day(hours, day_index)
        if _is_open_on(entry):
            assert entry is not None  # _is_open_on guarantees this
            when = "tomorrow" if offset == 1 else _DAY_NAMES[day_index]
            return when, entry.opening_time
    return None


def answer_open_now(hours: list[RestaurantHours], now: datetime) -> str:
    """
    Answers "are you open today?" / "are you still open?" the way a
    person would — a direct yes or no about *now*, not a recital of the
    whole week's schedule.
    """
    if not hours:
        return "I don't have our hours on file — let me connect you with someone who can help."

    entry = _entry_for_day(hours, now.weekday())

    if not _is_open_on(entry):
        next_open = _next_open_day(hours, now)
        if next_open is None:
            return "I don't have our hours on file — let me connect you with someone who can help."
        when, opening = next_open
        return f"We're closed today, but we're open again {when} at {_format_time_12h(opening)}."

    assert entry is not None  # _is_open_on guarantees this
    now_minutes = now.hour * 60 + now.minute
    opening_label = _format_time_12h(entry.opening_time)
    closing_label = _format_time_12h(entry.closing_time)

    if now_minutes < _as_minutes(entry.opening_time):
        return f"Yes, we're open today from {opening_label} to {closing_label}."

    if now_minutes < _as_minutes(entry.closing_time):
        return f"Yes, we're open right now, until {closing_label}."

    next_open = _next_open_day(hours, now)
    if next_open is None:
        return f"We've closed for today — we're open from {opening_label} to {closing_label}."
    when, opening = next_open
    return f"We've closed for tonight, but we're open again {when} at {_format_time_12h(opening)}."


def answer_hours_tomorrow(hours: list[RestaurantHours], now: datetime) -> str:
    """Answers "what time do you open tomorrow?" about tomorrow specifically."""
    if not hours:
        return "I don't have our hours on file — let me connect you with someone who can help."

    day_index = (now.weekday() + 1) % 7
    entry = _entry_for_day(hours, day_index)

    if not _is_open_on(entry):
        return f"We're closed tomorrow, on {_DAY_NAMES[day_index]}."

    assert entry is not None  # _is_open_on guarantees this
    return (
        f"Tomorrow we're open from {_format_time_12h(entry.opening_time)} "
        f"to {_format_time_12h(entry.closing_time)}."
    )


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

    # Open the same hours all week: "we're open every day, 9 AM to 10 PM"
    # is what a person says — nobody recites "Monday to Sunday".
    if len(groups) == 1 and groups[0]["key"] != "closed":
        opening, closing = groups[0]["key"]
        return f"We're open every day, {_format_time_12h(opening)} to {_format_time_12h(closing)}."

    phrases = []
    said_open = False
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
            # "We're open" leads the first open stretch only — repeating it
            # for every group reads like a form letter when spoken aloud.
            lead = "We're open " if not said_open else ""
            said_open = True
            phrases.append(f"{lead}{day_label}, {_format_time_12h(opening)} to {_format_time_12h(closing)}")

    return ". ".join(phrases) + "."


def answer_closing_time_tonight(hours: list[RestaurantHours], now: datetime) -> str:
    """Answers "what time do you close tonight?" for the caller's current day."""
    today_entry: Optional[RestaurantHours] = next((h for h in hours if h.day_of_week == now.weekday()), None)

    if today_entry is None or today_entry.is_closed:
        return "We're closed today."

    return f"We close tonight at {_format_time_12h(today_entry.closing_time)}."
