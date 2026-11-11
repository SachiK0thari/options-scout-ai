"""Record the offline market fixtures from the live provider (W11 step 2).

Used by ``scripts/record_fixtures.py``. Everything goes through the same :class:`MarketData`
facade a live screen uses, so a fixture holds what the app would have seen:

* chains from the previous session's close (the historical feed: about one credit per 1,000
  contracts, a few credits a ticker), stamped with that session's time rather than the time
  the script ran, so a replay counts days to expiry from the day the quotes are from;
* earnings from the provider, else Alpha Vantage, with the "estimated" and "unknown" flags kept
  (a replay restores them, see :meth:`FixtureSource.earnings_record`);
* VIX from the provider, else FRED's VIXCLS up to the same session, with FRED's citation saved
  so a fixture-mode report still credits it;
* the sector from the curated list when the provider has none (ETFs are told apart by it).

All or nothing: :func:`record` collects the fixtures in memory and :func:`write` is only called
when every ticker succeeded, so the bundle never mixes two sessions.

Licensing: the fixtures are provider data. They are for the owner's personal, non-commercial
use and live in a private repository; see the plan's W11 status note before publishing them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from options_scout.core.models import TickerSnapshot
from options_scout.data.fixtures import FixtureStore, IndexFixture, TickerFixture
from options_scout.data.market import (
    FRED_NOTICE,
    FRED_VIX_CITATION,
    MarketData,
    MarketDataError,
    QuotaExceededError,
)

VIX_HISTORY_DAYS = 252
MIN_VIX_HISTORY = 30  # IndexFixture's minimum
CLOSE_HISTORY_DAYS = 90


@dataclass
class Recording:
    fixtures: list[TickerFixture] = field(default_factory=list)
    indices: IndexFixture | None = None
    failed: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.indices is not None and not self.failed and bool(self.fixtures)


def session_as_of(snap: TickerSnapshot) -> datetime:
    """When the quotes are from: the latest chain stamp, else the quote's own."""
    stamps = [c.as_of for c in snap.chains]
    return max(stamps) if stamps else snap.spot.as_of


def record_vix(md: MarketData, session_day: date) -> tuple[list[float], float, str | None]:
    """(history oldest → newest, last close, citation or None) from the provider, else FRED."""
    try:
        history = md.source.get_index_history("^VIX", VIX_HISTORY_DAYS)
        if len(history) >= MIN_VIX_HISTORY:
            return [float(x) for x in history], float(md.source.get_index_last("^VIX")), None
        provider_error: Exception = MarketDataError(f"{len(history)} VIX closes")
    except QuotaExceededError:
        raise
    except Exception as exc:
        provider_error = exc
    if md.vix_fallback is None:
        raise MarketDataError(
            f"VIX unavailable from the provider ({provider_error}); set FRED_API_KEY"
        )
    closes = [(d, v) for d, v in md.vix_fallback.closes(md.today()) if d <= session_day]
    closes = closes[-VIX_HISTORY_DAYS:]
    if len(closes) < MIN_VIX_HISTORY:
        raise MarketDataError(f"FRED VIXCLS returned {len(closes)} closes up to {session_day}")
    last_day, last = closes[-1]
    citation = f"{FRED_VIX_CITATION} (close of {last_day.isoformat()}). {FRED_NOTICE}"
    return [v for _, v in closes], last, citation


def record(
    md: MarketData,
    tickers: Sequence[str],
    *,
    sector_of: Callable[[str], str | None] = lambda _t: None,
    progress: Callable[[str], None] = lambda _m: None,
) -> Recording:
    rec = Recording()
    for raw in tickers:
        t = raw.upper()
        try:
            snap = md.build_snapshot(t)
            closes = md.get_close_history(t, CLOSE_HISTORY_DAYS)
        except QuotaExceededError:
            raise  # a spent plan: stop, nothing is written
        except Exception as exc:
            rec.failed[t] = f"{type(exc).__name__}: {exc}"
            progress(f"{t}: FAILED {rec.failed[t]}")
            continue
        if not snap.chains:
            rec.failed[t] = "no option chains in the window"
        elif len(closes) <= 30:
            rec.failed[t] = f"only {len(closes)} closes"
        if t in rec.failed:
            progress(f"{t}: FAILED {rec.failed[t]}")
            continue
        spot = snap.spot
        sector = sector_of(t)
        if sector and spot.sector in {"Unknown", ""}:
            spot = spot.model_copy(update={"sector": sector})
        when = session_as_of(snap)
        snap = snap.model_copy(update={"as_of": when, "spot": spot})
        rec.fixtures.append(
            TickerFixture(snapshot=snap, close_history=closes, recorded_with=md.source.name)
        )
        n_opts = sum(len(c.calls) + len(c.puts) for c in snap.chains)
        estimated = " (estimated)" if snap.earnings_estimated else ""
        unknown = "" if snap.earnings_known else " (unknown)"
        progress(
            f"{t}: session {when.date()} spot={snap.spot.price:.2f} chains={len(snap.chains)} "
            f"options={n_opts} earnings={snap.earnings_date}{estimated}{unknown} "
            f"hv30={snap.hv30} atm_iv={snap.atm_iv}"
        )
        for e in snap.source_errors:
            progress(f"   {t} note: {e}")
    if not rec.fixtures:
        return rec
    sessions = sorted({f.snapshot.as_of.date() for f in rec.fixtures})
    if len(sessions) > 1:
        rec.notes.append(f"tickers span sessions {', '.join(map(str, sessions))}")
    as_of = max(f.snapshot.as_of for f in rec.fixtures)
    try:
        history, vix_now, citation = record_vix(md, as_of.date())
    except QuotaExceededError:
        raise
    except Exception as exc:
        rec.failed["^VIX"] = f"{type(exc).__name__}: {exc}"
        return rec
    rec.indices = IndexFixture(
        as_of=as_of,
        vix_history=history,
        vix_now=vix_now,
        irx_now=md.get_risk_free_rate() * 100.0,  # the facade's constant when there is no ^IRX
        recorded_with=md.source.name + ("+fred" if citation else ""),
        vix_source=citation,
    )
    progress(
        f"indices: session {as_of.date()} VIX={vix_now:.2f} (n={len(history)}"
        + (", FRED" if citation else "")
        + f"), rate={rec.indices.irx_now:.2f}%"
    )
    return rec


def write(rec: Recording, store: FixtureStore) -> list[Path]:
    """Save a complete recording; refuses a partial one so the bundle stays one session."""
    if not rec.complete or rec.indices is None:
        raise ValueError("refusing to write a partial recording: " + "; ".join(rec.failed))
    paths = [store.save(f) for f in rec.fixtures]
    paths.append(store.save_indices(rec.indices))
    return paths
