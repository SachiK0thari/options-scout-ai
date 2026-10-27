"""Daily ATM implied-vol snapshot per watchlist ticker.

Free data has no IV history, so we build our own: one row per (ticker, day). Once a ticker
has >= MIN_HISTORY rows, IV rank uses real history; until then callers fall back to the HV proxy.

Run: ``python -m options_scout.jobs.snapshot_iv [TICKER ...]``
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

MIN_HISTORY = 30


class IVSnapshotStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS iv_snapshots (ticker TEXT NOT NULL, day TEXT NOT NULL, "
            "atm_iv REAL NOT NULL, PRIMARY KEY (ticker, day))"
        )
        self._conn.commit()

    def record(self, ticker: str, day: date, atm_iv: float) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO iv_snapshots (ticker, day, atm_iv) VALUES (?, ?, ?)",
            (ticker.upper(), day.isoformat(), float(atm_iv)),
        )
        self._conn.commit()

    def history(self, ticker: str, limit: int = 252) -> list[float]:
        rows = self._conn.execute(
            "SELECT atm_iv FROM iv_snapshots WHERE ticker = ? ORDER BY day DESC LIMIT ?",
            (ticker.upper(), limit),
        ).fetchall()
        return [float(r[0]) for r in reversed(rows)]

    def count(self, ticker: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM iv_snapshots WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
        return int(row[0]) if row else 0

    def has_enough_history(self, ticker: str) -> bool:
        return self.count(ticker) >= MIN_HISTORY

    def close(self) -> None:
        self._conn.close()


def main(argv: list[str] | None = None) -> int:
    from options_scout.config import get_config
    from options_scout.data.fixtures import DEMO_TICKERS
    from options_scout.data.market import MarketData

    parser = argparse.ArgumentParser(description="Record today's ATM IV per ticker.")
    parser.add_argument("tickers", nargs="*", help="defaults to the demo tickers")
    args = parser.parse_args(argv)
    cfg = get_config()
    md = MarketData.from_config(cfg)
    store = IVSnapshotStore(cfg.paths.iv_snapshot_db)
    tickers = [t.upper() for t in args.tickers] or list(DEMO_TICKERS)
    for t in tickers:
        snap = md.build_snapshot(t)
        if snap.atm_iv is None:
            print(f"{t}: no ATM IV available", file=sys.stderr)
            continue
        store.record(t, snap.as_of.date(), snap.atm_iv)
        print(f"{t}: atm_iv={snap.atm_iv:.4f} rows={store.count(t)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
