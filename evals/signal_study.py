"""Honest signal study (section 11.4): does the Consumer-Trend Score predict forward returns?

Point-in-time discipline: the score for date D is computed only from posts/news/pageviews dated
<= D (the pipeline's window logic already enforces this through ``end=``). Forward returns use
closes strictly after D.

What the statistics count (W36):

- **One observation per ticker per date.** Two entities that resolve to one ticker ("Costco" and
  "Kirkland Signature") share one price path, so they are collapsed before any statistic, keeping
  the higher score, as the run itself does (``agent/nodes/trend_scout.py``).
- **Non-overlapping forward windows.** Score dates a week apart with a 30-day horizon share most
  of their price path. For each horizon only dates at least one horizon apart are used, so the
  sample counts independent windows, not weekly re-reads of the same move.
- **No interval below ``MIN_INDEPENDENT_OBS``.** When there are enough, the interval is a
  t-interval (not 1.96, which assumes a large sample).
- **Synthetic corpus.** The fixture corpus was generated with designed trend shapes, so a return
  paired with its scores means nothing. In that mode every table carries ``SYNTHETIC_LABEL`` and
  the excess-return figures are suppressed.

Run: .venv/bin/python evals/signal_study.py  → prints a markdown summary (also used by the notebook)
"""

from __future__ import annotations

import math
import statistics
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from options_scout.config import load_config  # noqa: E402
from options_scout.data.fixtures import FixtureStore  # noqa: E402
from options_scout.llm.client import LLMClient  # noqa: E402
from options_scout.social.pipeline import TrendScout  # noqa: E402

MIN_INDEPENDENT_OBS = 30
"""Below this many independent observations in a group, no interval is printed and the
insufficient-data banner covers every table."""

SYNTHETIC_LABEL = "synthetic corpus: illustrates the method only"
HORIZONS = {30: 21, 60: 42, 90: 63}  # calendar days → trading days


@dataclass(frozen=True)
class Observation:
    as_of: datetime
    ticker: str
    entities: tuple[str, ...]  # every entity collapsed into this ticker on this date
    score: float
    fwd_returns: dict[int, float | None]  # horizon (calendar days) → simple return
    spy_returns: dict[int, float | None]

    def excess(self, h: int) -> float | None:
        fr, sr = self.fwd_returns[h], self.spy_returns[h]
        return None if fr is None or sr is None else fr - sr


@dataclass(frozen=True)
class Interval:
    mean: float
    lo: float | None  # None: the sample has not earned an interval
    hi: float | None
    n: int


def _close_on(closes: list[float], end_day_offset: int) -> float | None:
    """Fixture close histories are 90 trading-day arrays ending at the recording date."""
    idx = len(closes) - 1 + end_day_offset
    if 0 <= idx < len(closes):
        return closes[idx]
    return None


def point_in_time_scores(cfg: Any, dates: list[datetime]) -> list[tuple[datetime, str, str, float]]:
    llm = LLMClient.from_config(cfg, mode="none")
    scout = TrendScout(cfg, llm, mode="fixture")
    out = []
    for d in dates:
        run = scout.run(end=d)  # only posts dated <= d contribute (window ends at d)
        for s in run.signals:
            if s.investable and s.ticker:
                out.append((d, s.entity, s.ticker, s.score))
    return out


def point_in_time_bottleneck_scores(
    cfg: Any, dates: list[datetime]
) -> list[tuple[datetime, str, str, float]]:
    """Phase 11: the bottleneck company score with the same point-in-time rule. ``end=d`` bounds
    every text source (``until``) and every series, and no snapshot store is attached, so the
    thesis monitor sees only that day's run."""
    from options_scout.bottleneck.engine import BottleneckEngine

    llm = LLMClient.from_config(cfg, mode="none")
    engine = BottleneckEngine(cfg, llm, mode="fixture")
    out = []
    for d in dates:
        run = engine.run(end=d, persist=False)
        for ticker, score in run.scores(curated_only=True).items():
            out.append((d, f"bottleneck:{ticker}", ticker, score))
    return out


def forward_return(closes: list[float], t0_offset: int, horizon_trading_days: int) -> float | None:
    c0 = _close_on(closes, t0_offset)
    c1 = _close_on(closes, t0_offset + horizon_trading_days)
    if c0 is None or c1 is None or c0 <= 0:
        return None
    return c1 / c0 - 1.0


def collapse_by_ticker(
    scored: Iterable[tuple[datetime, str, str, float]],
) -> list[tuple[datetime, str, tuple[str, ...], float]]:
    """One row per (date, ticker): the highest score, and every entity that resolved to it."""
    best: dict[tuple[datetime, str], float] = {}
    names: dict[tuple[datetime, str], set[str]] = {}
    for d, entity, ticker, score in scored:
        key = (d, ticker)
        best[key] = max(best.get(key, score), score)
        names.setdefault(key, set()).add(entity)
    return [(d, t, tuple(sorted(names[(d, t)])), best[(d, t)]) for d, t in sorted(best)]


def independent_dates(dates: Iterable[datetime], horizon_days: int) -> list[datetime]:
    """The earliest date, then each next date at least ``horizon_days`` after the last kept one,
    so no two kept forward windows overlap."""
    kept: list[datetime] = []
    for d in sorted(set(dates)):
        if not kept or (d - kept[-1]).days >= horizon_days:
            kept.append(d)
    return kept


def usable(obs: list[Observation], h: int) -> list[Observation]:
    """Observations for horizon ``h``: on non-overlapping dates, with both returns known."""
    keep = set(independent_dates((o.as_of for o in obs if o.excess(h) is not None), h))
    return [o for o in obs if o.as_of in keep and o.excess(h) is not None]


def mean_interval(xs: list[float], min_n: int = MIN_INDEPENDENT_OBS) -> Interval | None:
    """Mean with a 95% t-interval, or with no interval below ``min_n`` observations."""
    if not xs:
        return None
    m = statistics.mean(xs)
    if len(xs) < max(min_n, 2):
        return Interval(m, None, None, len(xs))
    from scipy.stats import t

    half = float(t.ppf(0.975, len(xs) - 1)) * statistics.stdev(xs) / math.sqrt(len(xs))
    return Interval(m, m - half, m + half, len(xs))


def _fmt_interval(iv: Interval | None) -> str:
    if iv is None:
        return "n/a"
    if iv.lo is None or iv.hi is None:
        return f"{iv.mean:+.2%} (no interval: n < {MIN_INDEPENDENT_OBS})"
    return f"{iv.mean:+.2%} [{iv.lo:+.2%}, {iv.hi:+.2%}]"


def render_trend_study(obs: list[Observation], *, synthetic: bool) -> list[str]:
    """The tercile table and the per-observation detail. ``synthetic`` labels every table and
    suppresses the excess-return figures."""
    lines: list[str] = []
    per_h = {h: usable(obs, h) for h in HORIZONS}
    largest = max((len(v) for v in per_h.values()), default=0)
    if synthetic or largest < MIN_INDEPENDENT_OBS:
        reasons = []
        if synthetic:
            reasons.append(
                "the social corpus is synthetic, so any pairing of its scores with real returns "
                "is coincidence by construction"
            )
        if largest < MIN_INDEPENDENT_OBS:
            reasons.append(
                f"the largest horizon sample has {largest} independent observations (one per "
                f"ticker per non-overlapping window), below the {MIN_INDEPENDENT_OBS} an interval "
                "needs"
            )
        lines += [
            "**Result: insufficient data; no predictive claim is made.** This applies to every "
            f"table below: {'; and '.join(reasons)}.",
            "",
        ]
    if not obs:
        return lines
    for h, rows in per_h.items():
        dates = sorted({o.as_of for o in rows})
        lines.append(
            f"- {h}d: {len(rows)} independent observations on "
            f"{', '.join(f'{d:%Y-%m-%d}' for d in dates) or 'no date with a full window'}."
        )
    lines.append("")
    if synthetic:
        lines += [f"_{SYNTHETIC_LABEL}._", ""]
    lines += [
        "| Horizon | Top-tercile mean excess return vs SPY | Bottom-tercile | n top / n bottom |",
        "|---|---|---|---|",
    ]
    for h, rows in per_h.items():
        ranked = sorted(rows, key=lambda o: o.score)
        k = len(ranked) // 3
        top, bottom = (ranked[-k:], ranked[:k]) if k else ([], [])
        if synthetic:
            t_cell = b_cell = "suppressed (synthetic)" if k else "n/a"
        else:
            t_cell = _fmt_interval(mean_interval([o.excess(h) or 0.0 for o in top]))
            b_cell = _fmt_interval(mean_interval([o.excess(h) or 0.0 for o in bottom]))
        lines.append(f"| {h}d | {t_cell} | {b_cell} | {len(top)} / {len(bottom)} |")
    lines += ["", "Per-observation detail (raw forward returns, one row per ticker per date):", ""]
    if synthetic:
        lines += [f"_{SYNTHETIC_LABEL}._", ""]
    lines += [
        "| as of | ticker | entities | score | 30d | 60d | 90d |",
        "|---|---|---|---|---|---|---|",
    ]
    for o in sorted(obs, key=lambda o: (o.score, o.as_of)):
        cells = [
            f"{o.fwd_returns[h]:+.2%}" if o.fwd_returns[h] is not None else "n/a" for h in HORIZONS
        ]
        lines.append(
            f"| {o.as_of:%Y-%m-%d} | {o.ticker} | {', '.join(o.entities)} | {o.score:.0f} | "
            + " | ".join(cells)
            + " |"
        )
    return lines


def run_study() -> str:
    # Scores come from the fixture corpus, which is synthetic; a live corpus (stored snapshots)
    # would pass ``synthetic=False`` to the renderer.
    synthetic = True
    cfg = load_config(ROOT)
    store = FixtureStore(cfg.paths.fixtures_dir)
    closes = {t: store.load(t).close_history for t in store.available()}
    spy = closes.get("SPY", [])
    record_date = store.load_indices().as_of
    # Score dates: weekly, from 6 weeks before the recording date up to 4 weeks before it, so
    # that at least a few weeks of forward closes exist inside the 90-day history.
    dates = [record_date - timedelta(days=7 * k) for k in (6, 5, 4)]
    scored = point_in_time_scores(cfg, dates)
    collapsed = collapse_by_ticker(scored)
    obs: list[Observation] = []
    for d, ticker, entities, score in collapsed:
        if ticker not in closes:
            continue  # no price fixture (most trend tickers): honest coverage gap, reported below
        t0 = -round((record_date - d).days * 252 / 365)
        fwd = {h: forward_return(closes[ticker], t0, td) for h, td in HORIZONS.items()}
        spy_r = {h: forward_return(spy, t0, td) for h, td in HORIZONS.items()}
        obs.append(Observation(d, ticker, entities, score, fwd, spy_r))
    lines = [
        "## Signal study: point-in-time Consumer-Trend Score vs forward returns",
        "",
        f"_Run {datetime.now(tz=UTC):%Y-%m-%d} on the fixture corpus (synthetic social data, real closes "
        f"for {len(closes)} tickers recorded {record_date:%Y-%m-%d})._",
        "",
        f"- Score dates: {', '.join(d.strftime('%Y-%m-%d') for d in dates)} (weekly, point-in-time).",
        f"- Investable trend signals produced: {len(scored)}; one per ticker per date: "
        f"{len(collapsed)}; with a price fixture: {len(obs)} "
        f"({len({o.ticker for o in obs})} distinct tickers).",
        "",
    ]
    lines += render_trend_study(obs, synthetic=synthetic)
    # ---- Phase 11: the bottleneck company score, reported separately (section 11.4)
    bn_scored = point_in_time_bottleneck_scores(cfg, dates)
    bn_with_prices = [(d, e, t, sc) for d, e, t, sc in bn_scored if t in closes]
    lines += [
        "",
        "## Signal study: point-in-time bottleneck company score (Phase 11, reported separately)",
        "",
        f"- Curated supplier scores produced: {len(bn_scored)} over {len(dates)} dates "
        f"({len({t for _, _, t, _ in bn_scored})} tickers: "
        f"{', '.join(sorted({t for _, _, t, _ in bn_scored}))}); with a price fixture: {len(bn_with_prices)}.",
    ]
    if synthetic or len(bn_with_prices) < MIN_INDEPENDENT_OBS:
        lines += [
            "",
            "**Result: insufficient data; no predictive claim is made.** The offline bundle carries closes for "
            "the ten demo tickers and none of them is a curated bottleneck supplier (HON, CSCO, XOM, CVX, UNP), so "
            "no forward return can be paired with a bottleneck score yet. The synthetic filings corpus would make "
            "any such pairing meaningless anyway; the table above shows the method, the live snapshots in "
            "`data/bottleneck_snapshots.sqlite` (180-day retention) are what this study will read once they exist.",
        ]
    if bn_with_prices:  # pragma: no cover - needs live snapshots and prices
        if synthetic:
            lines += ["", f"_{SYNTHETIC_LABEL}._", ""]
        for d, _e, t, sc in bn_with_prices[:20]:
            lines.append(f"- {d:%Y-%m-%d} {t} score {sc:.0f}")
    lines += [
        "",
        "### Caveats (read these before the numbers)",
        "- **Synthetic social data.** The fixture corpus was generated with designed trend shapes; any "
        "relationship with real price moves is coincidence by construction, so the excess-return figures "
        "are suppressed on it.",
        "- **What counts as an observation.** One per ticker per date (entities that resolve to one "
        "ticker share a price path), and for each horizon only score dates at least one horizon apart, "
        "so overlapping windows are not counted twice. Tickers on the same date still share the "
        "market's move; the excess return over SPY removes only part of it.",
        f"- **No interval below {MIN_INDEPENDENT_OBS} observations.** Above it the interval is a "
        "95% t-interval on the group's excess returns.",
        "- **Survivorship / selection.** Only tickers with a bundled price fixture are evaluated.",
        "- **Multiple horizons.** Three horizons × two groups are six comparisons; one of them "
        "clearing a 95% interval by chance is not a finding.",
        "- **Forward windows truncated** by the 90-day close history; later horizons have fewer observations.",
        "- **Bottleneck score (Phase 11):** scored on the same synthetic corpus; the layer z-scores depend on "
        "designed fixture dates, and the curated suppliers have no bundled closes, so the second study is a "
        "method demonstration only until `jobs/refresh_bottlenecks.py` has run live for two quarters.",
        "- **What would make this real:** run `jobs/refresh_trends.py` daily in live mode for 6+ months, "
        "persist each snapshot, then re-run this study on stored scores vs realised returns, with the "
        "same point-in-time rule and a pre-registered hypothesis (top-decile 60-day excess return > 0).",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(run_study())
