"""Honest signal study (section 11.4): does the Consumer-Trend Score predict forward returns?

Point-in-time discipline: the score for date D is computed only from posts/news/pageviews dated
<= D (the pipeline's window logic already enforces this through ``end=``). Forward returns use
closes strictly after D. With the fixture corpus (63 synthetic days) and 90 days of real closes
for 10 tickers, the sample is tiny and the result is *not* evidence either way; the point of this
module is the methodology, and it reports confidence intervals and caveats rather than a claim.

Run: .venv/bin/python evals/signal_study.py  → prints a markdown summary (also used by the notebook)
"""

from __future__ import annotations

import math
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from options_scout.config import load_config  # noqa: E402
from options_scout.data.fixtures import FixtureStore  # noqa: E402
from options_scout.llm.client import LLMClient  # noqa: E402
from options_scout.social.pipeline import TrendScout  # noqa: E402


@dataclass
class Observation:
    as_of: datetime
    entity: str
    ticker: str
    score: float
    fwd_returns: dict[int, float | None]  # horizon days → simple return vs the as-of close
    spy_returns: dict[int, float | None]


def _close_on(closes: list[float], end_day_offset: int) -> float | None:
    """Fixture close histories are 90 trading-day arrays ending at the recording date."""
    idx = len(closes) - 1 + end_day_offset
    if 0 <= idx < len(closes):
        return closes[idx]
    return None


def point_in_time_scores(cfg, dates: list[datetime]) -> list[tuple[datetime, str, str, float]]:  # type: ignore[no-untyped-def]
    llm = LLMClient.from_config(cfg, mode="none")
    scout = TrendScout(cfg, llm, mode="fixture")
    out = []
    for d in dates:
        run = scout.run(end=d)  # only posts dated <= d contribute (window ends at d)
        for s in run.signals:
            if s.investable and s.ticker:
                out.append((d, s.entity, s.ticker, s.score))
    return out


def forward_return(closes: list[float], t0_offset: int, horizon_trading_days: int) -> float | None:
    c0 = _close_on(closes, t0_offset)
    c1 = _close_on(closes, t0_offset + horizon_trading_days)
    if c0 is None or c1 is None or c0 <= 0:
        return None
    return c1 / c0 - 1.0


def mean_ci(xs: list[float]) -> tuple[float, float, float]:
    if len(xs) < 2:
        return (xs[0] if xs else float("nan"), float("nan"), float("nan"))
    m = statistics.mean(xs)
    se = statistics.stdev(xs) / math.sqrt(len(xs))
    return m, m - 1.96 * se, m + 1.96 * se


def run_study() -> str:
    cfg = load_config(ROOT)
    store = FixtureStore(cfg.paths.fixtures_dir)
    closes = {t: store.load(t).close_history for t in store.available()}
    spy = closes.get("SPY", [])
    record_date = store.load_indices().as_of
    # Score dates: weekly, from 6 weeks before the recording date up to 4 weeks before it, so
    # that at least a few weeks of forward closes exist inside the 90-day history.
    dates = [record_date - timedelta(days=7 * k) for k in (6, 5, 4)]
    scored = point_in_time_scores(cfg, dates)
    horizons = {30: 21, 60: 42, 90: 63}  # calendar → trading days
    obs: list[Observation] = []
    for d, entity, ticker, score in scored:
        if ticker not in closes:
            continue  # no price fixture (most trend tickers): honest coverage gap, reported below
        t0 = -round((record_date - d).days * 252 / 365)
        fwd = {h: forward_return(closes[ticker], t0, td) for h, td in horizons.items()}
        spy_r = {h: forward_return(spy, t0, td) for h, td in horizons.items()}
        obs.append(Observation(d, entity, ticker, score, fwd, spy_r))
    lines = [
        "## Signal study — point-in-time Consumer-Trend Score vs forward returns",
        "",
        f"_Run {datetime.now(tz=UTC):%Y-%m-%d} on the fixture corpus (synthetic social data, real closes "
        f"for {len(closes)} tickers recorded {record_date:%Y-%m-%d})._",
        "",
        f"- Score dates: {', '.join(d.strftime('%Y-%m-%d') for d in dates)} (weekly, point-in-time).",
        f"- Investable trend signals produced: {len(scored)}; with a price fixture: {len(obs)} "
        f"({len({o.ticker for o in obs})} distinct tickers).",
        "",
    ]
    if len(obs) < 10:
        lines += [
            "**Result: insufficient data — no predictive claim is made.** Fewer than 10 scored "
            "observations have forward prices, because the offline fixture bundle only carries closes "
            "for the 10 demo tickers while the trend board surfaces ~20 other names. The decile "
            "comparison below is therefore illustrative of the method, not evidence of an edge.",
            "",
        ]
    # decile split (top vs bottom third given the tiny sample)
    if obs:
        obs_sorted = sorted(obs, key=lambda o: o.score)
        k = max(len(obs_sorted) // 3, 1)
        bottom, top = obs_sorted[:k], obs_sorted[-k:]
        lines += [
            "| Horizon | Top-tercile mean excess return vs SPY (95% CI) | Bottom-tercile | n top / n bottom |",
            "|---|---|---|---|",
        ]

        def excess(group: list[Observation], h: int) -> list[float]:
            out: list[float] = []
            for o in group:
                fr, sr = o.fwd_returns[h], o.spy_returns[h]
                if fr is not None and sr is not None:
                    out.append(fr - sr)
            return out

        def fmt(m: float, lo: float, hi: float) -> str:
            if math.isnan(m):
                return "n/a"
            if math.isnan(lo):
                return f"{m:+.2%} [n<2]"
            return f"{m:+.2%} [{lo:+.2%}, {hi:+.2%}]"

        for h in horizons:
            te, be = excess(top, h), excess(bottom, h)
            tm, tlo, thi = mean_ci(te)
            bm, blo, bhi = mean_ci(be)
            lines.append(
                f"| {h}d | {fmt(tm, tlo, thi)} | {fmt(bm, blo, bhi)} | {len(te)} / {len(be)} |"
            )
        lines += [
            "",
            "Per-observation detail:",
            "",
            "| as of | entity | ticker | score | 30d | 60d | 90d |",
            "|---|---|---|---|---|---|---|",
        ]
        for o in obs_sorted:
            cells = [
                f"{o.fwd_returns[h]:+.2%}" if o.fwd_returns[h] is not None else "n/a"
                for h in horizons
            ]
            lines.append(
                f"| {o.as_of:%Y-%m-%d} | {o.entity} | {o.ticker} | {o.score:.0f} | "
                + " | ".join(cells)
                + " |"
            )
    lines += [
        "",
        "### Caveats (read these before the numbers)",
        "- **Synthetic social data.** The fixture corpus was generated with designed trend shapes; any "
        "relationship with real price moves is coincidence by construction.",
        "- **Survivorship / selection.** Only tickers with a bundled price fixture are evaluated.",
        "- **Tiny sample, multiple horizons.** Three horizons × two groups on a handful of names: "
        "treat every interval above as uninformative.",
        "- **Forward windows truncated** by the 90-day close history; later horizons have fewer observations.",
        "- **What would make this real:** run `jobs/refresh_trends.py` daily in live mode for 6+ months, "
        "persist each snapshot, then re-run this study on stored scores vs realised returns, with the "
        "same point-in-time rule and a pre-registered hypothesis (top-decile 60-day excess return > 0).",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(run_study())
