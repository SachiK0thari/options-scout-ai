"""Next earnings date from Alpha Vantage when the market-data provider has none (W27 follow-up).

MarketData.app's ``/stocks/earnings`` answered 402 on the user's plan (2026-11-11), so W5 marked
every single stock's date unknown and excluded its puts. Alpha Vantage gives two things on a
free key (personal, non-commercial use under its terms):

* ``EARNINGS_CALENDAR`` — one request lists every *confirmed* upcoming report (1,688 rows for
  three months on 2026-11-11), but most large caps that report in late January were not listed
  yet (AAPL, MSFT, PEP, XOM ...), so a missing name is not "no earnings soon";
* ``EARNINGS`` — one request per company returns its reported dates (AAPL: 123 quarters, gaps of
  91 to 95 days).

Rule decided by the user on 2026-11-11: a confirmed date when the calendar lists one; otherwise
an estimate, the last reported date plus ``cadence_days`` (91), labelled as estimated. The
screens then test the *earliest plausible* date, the estimate minus ``margin_days`` (21): a put
is clear of earnings only if the estimate falls at least 21 days after its expiry. A last report
older than ``stale_after_days`` (a skipped quarter, a delisting) gives no estimate: unknown.

Responses are cached (the calendar for a day, a company's history for a week) through the
facade's cache; requests are spaced to the free tier's five a minute. A daily-limit answer makes
the date unknown; it never fails the ticker.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

import httpx

log = logging.getLogger(__name__)

AV_URL = "https://www.alphavantage.co/query"


class EarningsUnavailableError(RuntimeError):
    """No confirmed date and no estimate: the date stays unknown (W5 fails closed)."""


@dataclass(frozen=True)
class EarningsLookup:
    """``day`` is the date the screens test: the confirmed report date, or for an estimate the
    earliest plausible one (estimate − margin)."""

    day: date
    kind: Literal["confirmed", "estimated"]
    estimate: date | None = None  # the central estimate (last report + cadence), when estimated
    last_reported: date | None = None


class AlphaVantageEarnings:
    CALENDAR_TTL = 86_400  # the calendar changes daily
    HISTORY_TTL = 7 * 86_400  # a company's reported dates change once a quarter

    def __init__(
        self,
        api_key: str,
        *,
        cache: Any | None = None,
        cadence_days: int = 91,
        margin_days: int = 21,
        stale_after_days: int = 120,
        min_interval_s: float = 12.5,
        skip: set[str] | None = None,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("Alpha Vantage API key is empty")
        self._key = key
        self.cache = cache
        self.cadence = timedelta(days=cadence_days)
        self.margin = timedelta(days=margin_days)
        self.stale_after = timedelta(days=stale_after_days)
        self.min_interval_s = min_interval_s
        self.skip = {s.upper() for s in (skip or set())}  # ETFs: no earnings to look up
        self._client = http_client or httpx.Client(timeout=30.0)
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None
        self.requests = 0

    def __repr__(self) -> str:  # never echo the key
        return "AlphaVantageEarnings()"

    @classmethod
    def from_env(
        cls, api_key_env: str, *, cache: Any | None = None, **kw: Any
    ) -> AlphaVantageEarnings | None:
        key = os.environ.get(api_key_env, "").strip()
        return cls(key, cache=cache, **kw) if key else None

    # -- transport ------------------------------------------------------------------------
    def _query(self, **params: str) -> httpx.Response:
        if self._last_call is not None:
            wait = self.min_interval_s - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)  # the free tier allows five requests a minute
        try:
            resp = self._client.get(AV_URL, params={**params, "apikey": self._key})
        except httpx.HTTPError as exc:  # the message may quote the URL, key included
            raise EarningsUnavailableError(
                f"Alpha Vantage: {type(exc).__name__} reaching www.alphavantage.co"
            ) from None
        finally:
            self._last_call = self._clock()
            self.requests += 1
        if resp.status_code >= 400:
            raise EarningsUnavailableError(f"Alpha Vantage: HTTP {resp.status_code}")
        if resp.text.lstrip().startswith("{"):
            body = resp.json()
            notice = body.get("Information") or body.get("Note") or body.get("Error Message")
            if notice:  # a daily or per-minute limit, or a bad symbol: 200 with a message
                raise EarningsUnavailableError(f"Alpha Vantage: {str(notice)[:160]}")
        return resp

    def _cached(self, key: str, ttl: int, fetch: Callable[[], Any]) -> Any:
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return hit
        value = fetch()
        if self.cache is not None:
            self.cache.set(key, value, ttl)
        return value

    # -- data -------------------------------------------------------------------------------
    def calendar(self, today: date) -> dict[str, str]:
        """``{symbol: earliest upcoming reportDate}`` from the three-month calendar."""

        def fetch() -> dict[str, str]:
            text = self._query(function="EARNINGS_CALENDAR", horizon="3month").text
            out: dict[str, str] = {}
            for row in csv.DictReader(io.StringIO(text)):
                sym, day = (row.get("symbol") or "").upper(), row.get("reportDate") or ""
                if sym and day >= today.isoformat() and (sym not in out or day < out[sym]):
                    out[sym] = day
            return out

        return dict(
            self._cached(f"av:earnings_calendar:{today.isoformat()}", self.CALENDAR_TTL, fetch)
        )

    def last_reported(self, symbol: str, today: date) -> date | None:
        def fetch() -> str:
            body = self._query(function="EARNINGS", symbol=symbol).json()
            past = [
                q.get("reportedDate", "")
                for q in body.get("quarterlyEarnings", [])
                if q.get("reportedDate", "") and q["reportedDate"] <= today.isoformat()
            ]
            return max(past) if past else "none"

        raw = self._cached(f"av:last_reported:{symbol}", self.HISTORY_TTL, fetch)
        return None if raw == "none" else date.fromisoformat(raw)

    def lookup(self, symbol: str, today: date) -> EarningsLookup:
        """The confirmed date, else the estimate; :class:`EarningsUnavailableError` otherwise."""
        sym = symbol.upper()
        if sym in self.skip:
            raise EarningsUnavailableError(f"{sym}: an ETF has no earnings")
        confirmed = self.calendar(today).get(sym)
        if confirmed:
            return EarningsLookup(day=date.fromisoformat(confirmed), kind="confirmed")
        last = self.last_reported(sym, today)
        if last is None:
            raise EarningsUnavailableError(f"{sym}: no reported earnings on Alpha Vantage")
        if today - last > self.stale_after:
            raise EarningsUnavailableError(
                f"{sym}: last report {last.isoformat()} is more than "
                f"{self.stale_after.days} days old; no estimate"
            )
        estimate = last + self.cadence
        # an estimate already past means a report is due or overdue: the earliest plausible
        # date is today, so every put on the name is treated as spanning earnings
        return EarningsLookup(
            day=max(estimate - self.margin, today),
            kind="estimated",
            estimate=estimate,
            last_reported=last,
        )
