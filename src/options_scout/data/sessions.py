"""NYSE trading sessions: which weekdays the market was open (W10).

Rule-based, with no dependency: the ten regular NYSE holidays and their weekend observance. An
unscheduled closure (a national day of mourning, as on 2025-01-09) is not known here, so the day
after one is treated as a missing session; the stale-data note says that can be the cause.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import cache
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


def _easter(year: int) -> date:
    """Western Easter Sunday (the anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``th ``weekday`` (Monday 0) of the month; ``n = -1`` is the last one."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    """A Saturday holiday is observed on the Friday before, a Sunday one on the Monday after."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@cache
def nyse_holidays(year: int) -> frozenset[date]:
    """The regular NYSE full-day closures in ``year``."""
    days = {
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter(year) - timedelta(days=2),  # Good Friday
        _nth_weekday(year, 5, 0, -1),  # Memorial Day
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),  # Christmas
    }
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:  # a Saturday New Year is not moved back into December
        days.add(_observed(new_year))
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))  # Juneteenth
    return frozenset(days)


def is_session(day: date) -> bool:
    """True when the NYSE was (or will be) open for a regular session on ``day``."""
    return day.weekday() < 5 and day not in nyse_holidays(day.year)


def last_session_before(day: date) -> date:
    """The latest trading session strictly before ``day``."""
    d = day - timedelta(days=1)
    while not is_session(d):
        d -= timedelta(days=1)
    return d


def market_today(now: datetime | None = None) -> date:
    """The US market's date: New York's calendar date at ``now`` (default: the wall clock).

    W28: every comparison of a date with an expiry or an earnings date uses this, not the UTC
    date, which runs a day ahead from 7 or 8 pm Eastern until midnight."""
    when = now or datetime.now(tz=UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(NEW_YORK).date()


def session_on_or_before(day: date) -> date:
    """``day`` when it is a trading session, else the latest session before it."""
    return day if is_session(day) else last_session_before(day)
