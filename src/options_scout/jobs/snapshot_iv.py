"""Daily ATM implied-vol snapshot per watchlist ticker.

Free data has no IV history, so we build our own: one row per (ticker, day). Once a ticker
has >= MIN_HISTORY rows, IV rank uses real history; until then callers fall back to the HV proxy.

Run: ``python -m options_scout.jobs.snapshot_iv [TICKER ...]``
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

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

    def history(self, ticker: str, limit: int = 252) -> list[float]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT atm_iv FROM iv_snapshots WHERE ticker = ? ORDER BY day DESC LIMIT ?",
                (ticker.upper(), limit),
            ).fetchall()
        return [float(r[0]) for r in reversed(rows)]

    def has(self, ticker: str, day: date) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM iv_snapshots WHERE ticker = ? AND day = ?",
                (ticker.upper(), day.isoformat()),
            ).fetchone()
        return row is not None

    def count(self, ticker: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM iv_snapshots WHERE ticker = ?", (ticker.upper(),)
            ).fetchone()
        return int(row[0]) if row else 0

    def has_enough_history(self, ticker: str) -> bool:
        return self.count(ticker) >= MIN_HISTORY

    def close(self) -> None:
        self._conn.close()


def expected_session(md: object) -> date | None:
    """The session a historical chain feed will return (the weekday before New York's today),
    or None for a feed whose session cannot be known before fetching."""
    source = getattr(md, "source", None)
    if getattr(source, "chain_feed", None) != "historical":
        return None
    day = source._today() - timedelta(days=1)  # type: ignore[union-attr]
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def main(argv: list[str] | None = None) -> int:
    from options_scout.config import get_config, load_env
    from options_scout.data.fixtures import DEMO_TICKERS
    from options_scout.data.market import MarketData
    from options_scout.env import check_startup_or_exit

    load_env()
    check_startup_or_exit()  # W42: bad settings stop here, with a message
    parser = argparse.ArgumentParser(description="Record today's ATM IV per ticker.")
    parser.add_argument("tickers", nargs="*", help="defaults to the demo tickers")
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
    expected = expected_session(md)
    for t in tickers:
        if expected is not None and store.has(t, expected):
            print(f"{t}: {expected.isoformat()} already recorded")  # a weekend or repeat pass
            continue
        snap = md.build_snapshot(t)
        if snap.atm_iv is None:
            print(f"{t}: no ATM IV available", file=sys.stderr)
            continue
        # the session the quotes are from (a delayed or historical feed is a session behind),
        # not the day the job ran
        day = min(c.as_of for c in snap.chains).date() if snap.chains else snap.as_of.date()
        store.record(t, day, snap.atm_iv)
        print(f"{t}: atm_iv={snap.atm_iv:.4f} rows={store.count(t)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
