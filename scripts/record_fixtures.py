"""Record live market fixtures for the demo tickers (run occasionally, commit the JSON).

Usage: MARKETDATA_TOKEN=... .venv/bin/python scripts/record_fixtures.py [TICKER ...]

Only the expiries the screeners care about are recorded (near 30–45 DTE window and LEAPS
>= ~330 DTE) to keep the files small and the credit count low: MarketData.app charges one
credit per option contract returned, so each ticker costs roughly ``strike_limit`` × chains
credits. Ten tickers do not fit in a free plan's daily allowance; use a paid/trial token.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from options_scout.config import load_config, load_env
from options_scout.data.cache import MemoryCache
from options_scout.data.fixtures import DEMO_TICKERS, FixtureStore, IndexFixture, TickerFixture
from options_scout.data.market import RISK_FREE_FALLBACK, MarketData, MarketDataAppSource


def main(argv: list[str]) -> int:
    load_env()
    cfg = load_config()
    md_cfg = cfg.settings.market_data.marketdata
    token = os.environ.get(md_cfg.api_key_env, "")
    if not token.strip():
        print(f"set {md_cfg.api_key_env} (a MarketData.app API token) first", file=sys.stderr)
        return 2
    tickers = [t.upper() for t in argv] or list(DEMO_TICKERS)
    store = FixtureStore(cfg.paths.fixtures_dir)
    src = MarketDataAppSource(token, strike_limit=md_cfg.strike_limit)
    md = MarketData(
        src,
        MemoryCache(),
        cfg.settings.cache_ttl_seconds.model_dump(),
        None,
        near_dte=(cfg.rules.csp.dte_min - 10, cfg.rules.csp.dte_max + 15),
        far_dte_min=cfg.rules.leaps.dte_min - 35,
    )
    now = datetime.now(tz=UTC)
    vix_hist = src.get_index_history("^VIX", 252)
    vix_now = src.get_index_last("^VIX")
    try:
        irx_now = src.get_index_last("^IRX")
    except Exception as exc:  # MarketData.app has no T-bill index; record the constant in percent
        print(f"^IRX unavailable ({type(exc).__name__}); recording {RISK_FREE_FALLBACK:.2%}")
        irx_now = RISK_FREE_FALLBACK * 100.0
    store.save_indices(
        IndexFixture(
            as_of=now,
            vix_history=vix_hist,
            vix_now=vix_now,
            irx_now=irx_now,
            recorded_with=src.name,
        )
    )
    print(f"indices: VIX={vix_now:.2f} (n={len(vix_hist)}), IRX={irx_now:.2f}%")
    for t in tickers:
        try:
            snap = md.build_snapshot(t)
            closes = src.get_close_history(t, 90)
            snap = snap.model_copy(update={"as_of": now})
            path = store.save(
                TickerFixture(snapshot=snap, close_history=closes, recorded_with=src.name)
            )
            n_opts = sum(len(c.calls) + len(c.puts) for c in snap.chains)
            print(
                f"{t}: spot={snap.spot.price:.2f} chains={len(snap.chains)} options={n_opts} "
                f"earnings={snap.earnings_date} hv30={snap.hv30} atm_iv={snap.atm_iv} -> {path.name}"
            )
            if snap.source_errors:
                print("   errors:", snap.source_errors)
        except Exception as exc:
            print(f"{t}: FAILED {type(exc).__name__}: {exc}")
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
