"""
Dates for tests, computed rather than written down.

Reservation extraction validates that a date is not in the past (see
_validate_date), so a hardcoded date in a test is a fuse. The suite used
"2026-09-04" in seventeen places; on the day it was written that was
today in the fixture's timezone and tomorrow it would have been
yesterday, dropping the field, leaving the draft incomplete, and failing
every reservation test at an assertion about conversation state — with
nothing about the real failure in the message.

It was already inconsistent across timezones before it expired: the same
literal was still today in America/New_York while it was already
yesterday in Europe/Rome, so a test that passed against one restaurant
fixture failed against another for reasons that had nothing to do with
the code under test.

Far enough ahead to be future in every timezone, close enough to stay a
plausible restaurant booking.
"""

from datetime import date, timedelta

_DAYS_AHEAD = 3


def future_date() -> str:
    """A YYYY-MM-DD date that is always in the future, in any timezone."""
    return (date.today() + timedelta(days=_DAYS_AHEAD)).isoformat()


def future_weekday() -> str:
    """The weekday name of future_date(), e.g. "Friday"."""
    return (date.today() + timedelta(days=_DAYS_AHEAD)).strftime("%A")


# Module-level so a test can drop it straight into a scripted extraction
# response. Computed at import, which is well inside any single run.
FUTURE_DATE = future_date()
FUTURE_WEEKDAY = future_weekday()
