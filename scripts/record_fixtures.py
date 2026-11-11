"""Record the offline market fixtures from MarketData.app (W11 step 2).

Usage: .venv/bin/python scripts/record_fixtures.py [--out DIR] [TICKER ...]

Needs ``MARKETDATA_TOKEN``, ``ALPHAVANTAGE_API_KEY`` (earnings; the plan has no earnings
endpoint) and ``FRED_API_KEY`` (VIX; the plan has no index data), read from the environment or
``.env``. The logic lives in :mod:`options_scout.data.recording`.

Cost: chains come from the previous session's close, about one credit per 1,000 contracts, plus
the candles: about 5-7 MarketData credits a ticker (about 65 for the ten demo tickers), and one
Alpha Vantage request per stock (25 a day on the free plan; answers are cached for the day).

Nothing is written unless every ticker succeeded, so the bundle is always one session.

Licensing: this is provider data for the owner's personal, non-commercial use. Keep it in a
private repository; do not publish it or serve it to others.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from options_scout.config import load_config, load_env
from options_scout.data.cache import MemoryCache, SQLiteCache
from options_scout.data.fixtures import DEMO_TICKERS, FixtureStore
from options_scout.data.market import (
    FredVix,
    MarketData,
    MarketDataAppSource,
    QuotaExceededError,
    _earnings_fallback,
)
from options_scout.data.recording import record, write


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tickers", nargs="*", help="default: the ten demo tickers")
    parser.add_argument("--out", type=Path, help="fixtures directory (default: the configured)")
    args = parser.parse_args(argv)

    load_env()
    cfg = load_config()
    md_cfg = cfg.settings.market_data
    token = os.environ.get(md_cfg.marketdata.api_key_env, "")
    if not token.strip():
        print(
            f"set {md_cfg.marketdata.api_key_env} (a MarketData.app token) first", file=sys.stderr
        )
        return 2
    earnings = _earnings_fallback(cfg, SQLiteCache(cfg.paths.cache_db))
    if earnings is None:
        print(
            f"set {md_cfg.earnings_api_key_env}: without it stock earnings are recorded as "
            "unknown and their puts are excluded",
            file=sys.stderr,
        )
        return 2
    tickers = [t.upper() for t in args.tickers] or list(DEMO_TICKERS)
    src = MarketDataAppSource(
        token, strike_limit=md_cfg.marketdata.strike_limit, chain_feed=md_cfg.marketdata.chain_feed
    )
    md = MarketData(
        src,
        MemoryCache(),  # fresh quotes, never another run's cache
        cfg.settings.cache_ttl_seconds.model_dump(),
        None,
        near_dte=(cfg.rules.csp.dte_min - 10, cfg.rules.csp.dte_max + 15),
        far_dte_min=cfg.rules.leaps.dte_min - 35,
        credits_per_ticker=md_cfg.marketdata.credits_per_ticker,
        vix_fallback=FredVix.from_env(),
        earnings_fallback=earnings,
    )

    def sector_of(t: str) -> str | None:
        curated = cfg.quality.get(t)
        return curated.sector if curated else None

    try:
        rec = record(md, tickers, sector_of=sector_of, progress=print)
    except QuotaExceededError as exc:
        print(f"stopped: data quota reached ({exc}); nothing written", file=sys.stderr)
        return 1
    finally:
        print(f"MarketData credits used: {src.credits_used}, left: {src.credits_remaining}")
    for note in rec.notes:
        print("note:", note)
    if not rec.complete:
        print("not written; failed: " + "; ".join(f"{k}: {v}" for k, v in rec.failed.items()))
        return 1
    store = FixtureStore(args.out if args.out else cfg.paths.fixtures_dir)
    for path in write(rec, store):
        print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
