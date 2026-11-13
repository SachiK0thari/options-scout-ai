"""Per-company market facts for ``priced_in`` and ``catalyst_days`` (PRD 4A.7, steps 6 and 7).

Everything here comes from data the app already fetches through :class:`MarketData`: the close
history gives the 90-day return relative to the benchmark and the distance to the 52-week high,
the ticker snapshot gives the IV rank, and the next earnings date is the catalyst. The refresh
job (daily) and the in-graph node both call :func:`market_facts_for` for the **curated** suppliers
only, so the pure plays shown as context cost no extra calls. A ticker the source cannot serve (no
offline fixture, a provider error) is skipped silently: ``priced_in`` then falls back to the
coverage term and ``catalyst_days`` stays ``None``, which the board prints as such.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date

from options_scout.bottleneck.signals import CompanyMarketFacts
from options_scout.data.market import MarketData

__all__ = ["HIGH_DAYS", "RETURN_DAYS", "CompanyMarketFacts", "market_facts_for"]

log = logging.getLogger(__name__)

RETURN_DAYS = 90  # trading-day lookback for the relative return (section 4A.7 says 90-day)
HIGH_DAYS = 252  # one trading year for the 52-week high
HISTORY_DAYS = HIGH_DAYS + 10  # what to request, so both windows are covered


def _return(closes: list[float], days: int) -> float | None:
    if len(closes) <= days or closes[-1 - days] <= 0:
        return None
    return closes[-1] / closes[-1 - days] - 1.0


def _dist_from_high(closes: list[float], days: int) -> float | None:
    window = [c for c in closes[-days:] if c > 0]
    if len(window) < 2:
        return None
    high = max(window)
    return (high - window[-1]) / high if high > 0 else None


def market_facts_for(
    md: MarketData,
    tickers: Iterable[str],
    *,
    today: date | None = None,
    benchmark: str = "SPY",
    with_iv_rank: bool = True,
) -> dict[str, CompanyMarketFacts]:
    """``{ticker: CompanyMarketFacts}`` for every ticker the market source can serve.

    ``with_iv_rank`` builds the option snapshot (chains) to read the IV rank; the job turns it
    off for a cheap refresh when only the price terms and the catalyst are wanted.
    """
    today = today or md.today()
    bench: list[float] = []
    try:
        bench = md.get_close_history(benchmark, HISTORY_DAYS)
    except Exception as exc:  # the relative return is then just the ticker's own return
        log.info(
            "market facts: no %s history (%s); relative return uses raw return", benchmark, exc
        )
    bench_ret = _return(bench, RETURN_DAYS) if bench else None
    out: dict[str, CompanyMarketFacts] = {}
    for raw in tickers:
        t = raw.strip().upper()
        try:
            closes = md.get_close_history(t, HISTORY_DAYS)
        except Exception as exc:
            log.info("market facts: no history for %s (%s); skipped", t, exc)
            continue
        own = _return(closes, RETURN_DAYS)
        rel = None if own is None else own - (bench_ret or 0.0)
        dist = _dist_from_high(closes, HIGH_DAYS)
        iv_rank: float | None = None
        earnings: date | None = None
        if with_iv_rank:
            try:
                snap = md.build_snapshot(t)
                # W4: only a rank from stored history; the IV/HV proxy reads high for nearly
                # every name and would inflate the priced-in penalty
                if snap.iv_rank is not None and snap.iv_rank_source == "history":
                    iv_rank = round(snap.iv_rank * 100.0, 2)
                earnings = snap.earnings_date
            except Exception as exc:
                log.info("market facts: no snapshot for %s (%s); price terms only", t, exc)
        if earnings is None:
            try:
                earnings = md.get_earnings_date(t)
            except Exception:
                earnings = None
        if earnings is not None and earnings < today:
            earnings = None  # a past report date is not a catalyst
        if own is None and dist is None and iv_rank is None and earnings is None:
            continue
        out[t] = CompanyMarketFacts(
            rel_return_90d=None if rel is None else round(rel, 4),
            dist_from_high=None if dist is None else round(dist, 4),
            iv_rank=iv_rank,
            next_event=earnings,
        )
    return out
