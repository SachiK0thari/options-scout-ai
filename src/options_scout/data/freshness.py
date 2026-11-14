"""How old a quote is (W10): the provider's own timestamp, not the time it was fetched.

Both live providers stamp each price with the moment it was quoted. On a weekend, or with the
previous-session chain feed, that moment is hours or days before the fetch, and a line that says
"fetched 2 min ago" would describe Friday's close as fresh. These helpers turn the provider
timestamps into the freshness line, the run's data note and the spot/chain mismatch note.

Two kinds of feed are judged differently:

- **Intraday** (Tradier, MarketData.app ``chain_feed: live``): quotes should be minutes old, so a
  quote older than ``market_data.max_quote_age_minutes`` is stale.
- **End of day** (MarketData.app ``chain_feed: historical``, the default): the previous session's
  close is the design, not a fault. The data is labelled as end of day and is stale only when it
  is older than the last completed NYSE session (a provider gap, an older chain served from the
  cache, or an unscheduled closure the calendar does not know).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from options_scout.core.models import OptionChain, SpotQuote, TickerSnapshot
from options_scout.data.sessions import last_session_before

NEW_YORK = ZoneInfo("America/New_York")


def format_quote_time(when: datetime) -> str:
    """``Fri 2026-11-06 16:00 ET``: the exchange's clock, since that is what a session means."""
    return f"{when.astimezone(NEW_YORK):%a %Y-%m-%d %H:%M} ET"


def format_session(day: date) -> str:
    """``Fri 2026-11-06``."""
    return f"{day:%a %Y-%m-%d}"


def session_of(when: datetime) -> date:
    """The New York trading date a timestamp belongs to."""
    return when.astimezone(NEW_YORK).date()


def age_minutes(when: datetime, now: datetime) -> int:
    return max(int((now - when).total_seconds() // 60), 0)


def is_stale(when: datetime, now: datetime, max_age_minutes: int) -> bool:
    return age_minutes(when, now) > max_age_minutes


@dataclass(frozen=True)
class QuoteAge:
    """How the oldest quote of a run reads, for the strip and the report."""

    quoted_at: datetime
    end_of_day: bool
    stale: bool
    # end of day only: the session the feed should have returned (the last one before today)
    expected_session: date | None = None

    def headline(self) -> str:
        """``end-of-day data: Fri 2026-11-06 close`` or ``quotes from Fri 2026-11-06 16:00 ET``."""
        if self.end_of_day:
            return f"end-of-day data: {format_session(session_of(self.quoted_at))} close"
        return f"quotes from {format_quote_time(self.quoted_at)}"

    def suffix(self) -> str:
        """What the strip appends to the line when the data is stale."""
        if not self.stale:
            return ""
        if self.end_of_day and self.expected_session is not None:
            return f" · older than the last session ({format_session(self.expected_session)})"
        return " · market closed or stale"

    def warning(self) -> str | None:
        """The strip's warning, only when stale."""
        if not self.stale:
            return None
        if self.end_of_day and self.expected_session is not None:
            return (
                f"These prices are from the {format_session(session_of(self.quoted_at))} close, "
                f"but the last completed session was {format_session(self.expected_session)}: "
                "the provider had no newer chain or an older one was served from the cache, so "
                "prices may have moved since."
            )
        return (
            f"The oldest quote shown is from {format_quote_time(self.quoted_at)}: the market is "
            "closed or the data is stale, so prices may have moved since."
        )

    def report_note(self, max_age_minutes: int) -> str | None:
        """The run's one data note: end-of-day data is always labelled; intraday data only when
        stale."""
        day = format_session(session_of(self.quoted_at))
        if self.end_of_day:
            if self.stale and self.expected_session is not None:
                return (
                    f"market data: end-of-day prices from the {day} close, older than the last "
                    f"completed session ({format_session(self.expected_session)}): the provider "
                    "had no newer chain, an older one was served from the cache, or the market "
                    "closed unscheduled; prices may have moved since"
                )
            return (
                f"market data: end-of-day prices from the {day} close (the previous session); "
                "moves since that close are not reflected"
            )
        if not self.stale:
            return None
        return (
            f"market data: the oldest quote is from {format_quote_time(self.quoted_at)}, more "
            f"than {max_age_minutes} minutes before this run (market closed or stale); prices "
            "may have moved since"
        )


def assess(
    quoted_at: datetime | None, now: datetime, *, end_of_day: bool, max_age_minutes: int
) -> QuoteAge | None:
    """Judge the oldest quote of a run; None when the provider gave no timestamp."""
    if quoted_at is None:
        return None
    if end_of_day:
        expected = last_session_before(session_of(now))
        return QuoteAge(quoted_at, True, session_of(quoted_at) < expected, expected)
    return QuoteAge(quoted_at, False, is_stale(quoted_at, now, max_age_minutes))


def oldest_of(spot: SpotQuote, chains: Sequence[OptionChain]) -> datetime | None:
    """The stalest provider timestamp across a spot and its chains, or None when none has one."""
    stamps = [t for t in (spot.quoted_at, *(c.quoted_at for c in chains)) if t is not None]
    return min(stamps) if stamps else None


def oldest_quote(snapshots: Iterable[TickerSnapshot]) -> datetime | None:
    """The stalest provider timestamp across the snapshots, or None when none has one."""
    stamps = [s.quoted_at for s in snapshots if s.quoted_at is not None]
    return min(stamps) if stamps else None


def spot_chain_mismatch(
    spot: SpotQuote, chains: Sequence[OptionChain], max_age_minutes: int
) -> str | None:
    """A note when the spot and a chain were quoted more than the limit apart, else None.

    Deep in-the-money intrinsic and extrinsic values are wrong when the stock price and the
    option prices are from different moments.
    """
    if spot.quoted_at is None:
        return None
    apart = [
        (int(abs((c.quoted_at - spot.quoted_at).total_seconds()) // 60), c.expiry, c.quoted_at)
        for c in chains
        if c.quoted_at is not None
    ]
    worst = max(apart, key=lambda x: x[0], default=None)
    if worst is None or worst[0] <= max_age_minutes:
        return None
    minutes, expiry, chain_at = worst
    return (
        f"spot quoted {format_quote_time(spot.quoted_at)} but the {expiry} chain "
        f"{format_quote_time(chain_at)} ({minutes} min apart): intrinsic and extrinsic values "
        "mix two moments"
    )


def snapshot_quote_day(snap: TickerSnapshot, fallback: date) -> date:
    """The market date a snapshot's prices are from (W28 step 4): the session of its stalest
    provider timestamp, else ``fallback``. Days to expiry are counted from here, not from the
    run's date: the same $3.00 premium annualised to 6.34% on Friday and 6.90% on a holiday
    Monday because the day count shrank while the quote did not change."""
    return session_of(snap.quoted_at) if snap.quoted_at is not None else fallback


def no_live_bids(snapshots: Iterable[TickerSnapshot]) -> bool:
    """True when there are option chains and every contract in them bids zero: the market is
    closed and the provider is serving placeholders, so "no candidates met the criteria" would
    misread it (W28 step 4)."""
    quotes = [q for s in snapshots for c in s.chains for q in (*c.calls, *c.puts)]
    return bool(quotes) and all(q.bid <= 0 for q in quotes)


MARKET_CLOSED_NOTE = (
    "screener: market closed, no quotes (every option bid is zero); run again during market "
    "hours, or use the end-of-day feed"
)
