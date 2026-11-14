"""Daily ATM implied-vol snapshot per watchlist ticker.

Free data has no IV history, so we build our own: one row per (ticker, day). Once a ticker
has >= MIN_HISTORY rows, IV rank uses real history; until then callers fall back to the HV proxy.

Run: ``python -m options_scout.jobs.snapshot_iv [TICKER ...]``

``--backfill N`` (W4 step 6) fills the last N sessions from the provider's historical chains
instead of waiting N days: one whole-chain request per ticker and missing session (MarketData.app
historical feed only, about 1 credit per 1,000 contracts). Sessions already stored cost nothing.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

MIN_HISTORY = 30


class IVSnapshotStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by the parallel per-ticker graph branches → serialise access.
        self._lock = threading.Lock()
        # the scheduler writes while the API and UI read: wait on the file lock (W39)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS iv_snapshots (ticker TEXT NOT NULL, day TEXT NOT NULL, "
                "atm_iv REAL NOT NULL, PRIMARY KEY (ticker, day))"
            )
            self._conn.commit()

    def record(self, ticker: str, day: date, atm_iv: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO iv_snapshots (ticker, day, atm_iv) VALUES (?, ?, ?)",
                (ticker.upper(), day.isoformat(), float(atm_iv)),
            )
            self._conn.commit()

    def _session_rows(self, ticker: str) -> list[tuple[date, float]]:
        """Rows dated on NYSE sessions, oldest first (W28 step 12). Earlier versions stored a
        weekend run under the run's date, one stale value two or three times; those rows are
        not trading days and do not count."""
        from options_scout.data.sessions import is_session

        with self._lock:
            rows = self._conn.execute(
                "SELECT day, atm_iv FROM iv_snapshots WHERE ticker = ? ORDER BY day",
                (ticker.upper(),),
            ).fetchall()
        out = [(date.fromisoformat(d), float(v)) for d, v in rows]
        return [(d, v) for d, v in out if is_session(d)]

    def history(self, ticker: str, limit: int = 252) -> list[float]:
        return [v for _, v in self._session_rows(ticker)[-limit:]]

    def has(self, ticker: str, day: date) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM iv_snapshots WHERE ticker = ? AND day = ?",
                (ticker.upper(), day.isoformat()),
            ).fetchone()
        return row is not None

    def count(self, ticker: str) -> int:
        """Distinct trading sessions stored for ``ticker`` (what counts toward MIN_HISTORY)."""
        return len(self._session_rows(ticker))

    def has_enough_history(self, ticker: str) -> bool:
        return self.count(ticker) >= MIN_HISTORY

    def close(self) -> None:
        self._conn.close()


def expected_session(md: object) -> date | None:
    """The session a historical chain feed will return (the last NYSE session before New York's
    today, holidays skipped, W10), or None for a feed whose session cannot be known before
    fetching."""
    from options_scout.data.sessions import last_session_before

    source = getattr(md, "source", None)
    if getattr(source, "chain_feed", None) != "historical":
        return None
    return last_session_before(source._today())  # type: ignore[union-attr]


def quoted_session(snap: Any) -> date:
    """The trading session a snapshot's quotes are from (W28 step 12), not the day the job ran:
    the provider's timestamp in New York, else the chains' ``as_of``, else the run's; a weekend
    or holiday maps to the session before it, so Friday's close run on Sunday is Friday's row."""
    from options_scout.data.freshness import session_of, snapshot_quote_day
    from options_scout.data.sessions import session_on_or_before

    stamp = min(c.as_of for c in snap.chains) if snap.chains else snap.as_of
    return session_on_or_before(snapshot_quote_day(snap, session_of(stamp)))


BACKFILL_SLACK = 10  # extra weekdays tried for holidays while looking for N sessions


def backfill(
    md: Any, store: IVSnapshotStore, tickers: list[str], sessions: int, *, budget: int = 0
) -> dict[str, int]:
    """Record the ATM IV of each of the last ``sessions`` sessions per ticker, newest first,
    the way the daily job computes it (``atm_implied_vol`` at that session's close and price).

    Returns rows added per ticker. Stops cleanly (keeping what was recorded) when the provider
    says the credits are spent; ``budget`` is the credits one request is assumed to need."""
    from options_scout.data.market import QuotaExceededError, atm_implied_vol

    source = md.source
    if not hasattr(source, "session_chains") or getattr(source, "chain_feed", "") != "historical":
        raise SystemExit("snapshot_iv --backfill needs MarketData.app with chain_feed: historical")
    latest = expected_session(md)
    assert latest is not None
    r = md.get_risk_free_rate()
    added: dict[str, int] = {}
    for t in tickers:
        added[t] = 0
        try:
            q = md.get_dividend_yield(t)
        except QuotaExceededError:
            raise
        except Exception:
            q = 0.0  # as build_snapshot does when the lookup fails
        day, found, tried = latest, 0, 0
        while found < sessions and tried < sessions + BACKFILL_SLACK:
            if day.weekday() < 5:
                tried += 1
                if store.has(t, day):
                    found += 1
                else:
                    if budget and hasattr(source, "ensure_budget"):
                        source.ensure_budget(budget)
                    got = source.session_chains(t, day)
                    if got is not None:  # None: a holiday, no session
                        spot, chains = got
                        iv = atm_implied_vol(chains, spot, day, md.near_dte, r=r, q=q)
                        found += 1
                        if iv is not None:
                            store.record(t, day, iv)
                            added[t] += 1
            day -= timedelta(days=1)
        print(f"{t}: {added[t]} session(s) added, rows={store.count(t)}")
    return added


def main(argv: list[str] | None = None) -> int:
    from options_scout.config import get_config, load_env
    from options_scout.data.fixtures import DEMO_TICKERS
    from options_scout.data.market import MarketData
    from options_scout.env import check_startup_or_exit

    load_env()
    check_startup_or_exit()  # W42: bad settings stop here, with a message
    parser = argparse.ArgumentParser(description="Record today's ATM IV per ticker.")
    parser.add_argument("tickers", nargs="*", help="defaults to the demo tickers")
    parser.add_argument(
        "--backfill",
        type=int,
        default=0,
        metavar="N",
        help="fill the last N sessions from historical chains (spends provider credits)",
    )
    args = parser.parse_args(argv)
    cfg = get_config()
    md = MarketData.from_config(cfg)
    if getattr(getattr(md, "source", None), "name", "") == "fixture":
        # recorded test data is not an IV history: writing it would corrupt every rank later
        print(
            "snapshot_iv: data mode is fixture, nothing recorded; set OPTIONS_SCOUT_DATA_MODE=live",
            file=sys.stderr,
        )
        return 0  # a skip, not a failure: the compose scheduler's heartbeat stays healthy
    store = IVSnapshotStore(cfg.paths.iv_snapshot_db)
    tickers = [t.upper() for t in args.tickers] or list(DEMO_TICKERS)
    if args.backfill > 0:
        from options_scout.data.market import QuotaExceededError

        try:
            backfill(
                md,
                store,
                tickers,
                args.backfill,
                budget=cfg.settings.market_data.marketdata.credits_per_ticker,
            )
        except QuotaExceededError as exc:
            print(f"snapshot_iv: stopped, {exc}; rerun tomorrow to continue", file=sys.stderr)
        used = getattr(md.source, "credits_used", None)
        if used is not None:
            left = getattr(md.source, "credits_remaining", None)
            print(f"credits used: {used}; left today: {left}")
        return 0
    expected = expected_session(md)
    for t in tickers:
        if expected is not None and store.has(t, expected):
            print(f"{t}: {expected.isoformat()} already recorded")  # a weekend or repeat pass
            continue
        snap = md.build_snapshot(t)
        if snap.atm_iv is None:
            print(f"{t}: no ATM IV available", file=sys.stderr)
            continue
        store.record(t, quoted_session(snap), snap.atm_iv)
        print(f"{t}: atm_iv={snap.atm_iv:.4f} rows={store.count(t)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
