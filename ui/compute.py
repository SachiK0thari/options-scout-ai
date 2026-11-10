"""Deterministic helpers the tabs chart: per-position stress, payoff legs, Reg T steps, and the
market overview strip's quotes and data age.

Nothing here is new math; every function calls ``core/`` and reshapes the result for a chart.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from options_scout.config import AppConfig
from options_scout.core import payoff as po
from options_scout.core import risk as core_risk
from options_scout.core.margin import csp_collateral, reg_t_put_margin
from options_scout.core.models import (
    MarketRegime,
    OptionCandidate,
    ScreeningReport,
    SizedPortfolio,
    SizedPosition,
    TickerSnapshot,
)
from options_scout.data.market import MarketData


def candidate_index(report: ScreeningReport) -> dict[str, OptionCandidate]:
    """Every option contract the report knows, by id (CSPs, LEAPS and PMCC short calls)."""
    out: dict[str, OptionCandidate] = {c.id: c for c in report.csp_candidates}
    out.update({c.id: c for c in report.leaps_candidates})
    for p in report.pmcc_candidates:
        out.setdefault(p.leaps.id, p.leaps)
        out.setdefault(p.short_call.id, p.short_call)
    return out


def position_legs(pos: SizedPosition, cands: dict[str, OptionCandidate]) -> list[po.Leg]:
    """Payoff legs of one sized position (a PMCC is the LEAPS plus its short call)."""
    main = cands.get(pos.candidate_id)
    mid = main.mid if main is not None else pos.mid
    if pos.strategy == "csp":
        return po.csp_legs(pos.strike, mid, pos.contracts)
    short = cands.get(pos.pmcc_short_call_id or "")
    if short is not None:
        return po.pmcc_legs(pos.strike, mid, short.strike, short.mid, pos.contracts)
    return po.long_call_legs(pos.strike, mid, pos.contracts)


def portfolio_payoff_vs_move(
    report: ScreeningReport, moves: list[float]
) -> list[tuple[float, float]]:
    """Sum of every position's payoff at expiry when all underlyings move by the same fraction.

    Positions live on different stocks, so the common axis is the market move, not a price.
    A PMCC is valued at its short call's expiry with the LEAPS at intrinsic (conservative).
    """
    cands = candidate_index(report)
    points: list[tuple[float, float]] = []
    for m in moves:
        total = 0.0
        for pos in report.portfolio.positions:
            cand = cands.get(pos.candidate_id)
            spot = cand.spot if cand is not None else pos.strike
            total += po.payoff(position_legs(pos, cands), spot * (1.0 + m))
        points.append((m, round(total, 2)))
    return points


def stress_by_position(
    report: ScreeningReport,
    snapshots: dict[str, TickerSnapshot],
    cfg: AppConfig,
    today: date,
) -> dict[str, dict[float, float]]:
    """The report's stress test re-run one position at a time: ``{candidate_id: {shock: pnl}}``."""
    cands = candidate_index(report)
    out: dict[str, dict[float, float]] = {}
    for pos in report.portfolio.positions:
        single = SizedPortfolio(positions=[pos], totals=report.portfolio.totals)
        results = core_risk.stress_test(
            single,
            cands,
            snapshots,
            shocks=cfg.settings.risk.stress_shocks,
            iv_shock=cfg.settings.risk.stress_iv_shock,
            r=report.regime.risk_free_rate,
            today=today,
            account_value=report.profile.account_value,
        )
        out[pos.candidate_id] = {s.shock: round(s.pnl, 2) for s in results}
    return out


@dataclass(frozen=True)
class RegTStep:
    label: str
    formula: str
    value: float


def reg_t_steps(S: float, K: float, premium: float) -> list[RegTStep]:
    """Section 3.6 Reg T naked-put minimum, one line per step, ending on the same number
    ``core.margin.reg_t_put_margin`` returns."""
    otm = max(S - K, 0.0)
    twenty = 0.20 * S - otm
    ten = 0.10 * K
    base = max(twenty, ten)
    total = reg_t_put_margin(S, K, premium)
    return [
        RegTStep("Out-of-the-money amount", f"max({S:,.2f} − {K:,.2f}, 0)", otm),
        RegTStep("20% of the stock price, less OTM", f"0.20 × {S:,.2f} − {otm:,.2f}", twenty),
        RegTStep("10% of the strike", f"0.10 × {K:,.2f}", ten),
        RegTStep("The larger of the two", f"max({twenty:,.2f}, {ten:,.2f})", base),
        RegTStep("Add the premium received", f"{base:,.2f} + {premium:,.2f}", base + premium),
        RegTStep("× 100 shares = Reg T minimum", f"({base:,.2f} + {premium:,.2f}) × 100", total),
    ]


def collateral_line(K: float, premium: float) -> tuple[str, float]:
    return (f"({K:,.2f} − {premium:,.2f}) × 100", csp_collateral(K, premium))


def greeks_explained(c: OptionCandidate) -> list[tuple[str, str, str]]:
    """(name, value, plain-English meaning for this contract). Numbers are the candidate's own."""
    per_contract_theta = c.theta * 100
    per_contract_vega = c.vega * 100
    side = "sold put" if c.kind == "put" else "long call"
    return [
        (
            "Delta",
            f"{c.delta:+.2f}",
            f"A $1 move in {c.ticker} changes this option's price by about ${abs(c.delta):.2f}. "
            f"For a {side} it is also a rough probability of finishing in the money: "
            f"{abs(c.delta):.0%}.",
        ),
        (
            "Gamma",
            f"{c.gamma:.4f}",
            f"Delta itself moves by about {c.gamma:.4f} per $1 move in the stock, so the "
            f"exposure is not fixed.",
        ),
        (
            "Theta",
            f"{c.theta:+.3f} / day",
            f"Time decay: about ${abs(per_contract_theta):,.2f} per contract per calendar day "
            f"{'in favour of' if c.kind == 'put' else 'against'} the position, all else equal.",
        ),
        (
            "Vega",
            f"{c.vega:.3f} per vol point",
            f"A one-point rise in implied volatility changes the contract's value by about "
            f"${per_contract_vega:,.2f}.",
        ),
        (
            "Implied vol",
            f"{c.iv:.0%}",
            (
                "Solved from the contract's mid price with Black-Scholes-Merton; the Greeks above "
                "are computed from it."
                if c.iv_source == "mid"
                else "The data provider's figure: no volatility reproduces the quoted mid (the "
                "option trades at parity), so the Greeks above use this value instead."
            ),
        ),
        (
            "Probability OTM",
            f"{c.prob_otm:.0%}",
            "Model probability that the option expires worthless (N(d2) for puts).",
        ),
    ]


def profile_from_interrupt(intr: dict[str, Any]) -> dict[str, Any]:
    """Defaults for the editable profile the Scout tab shows while a run waits for review."""
    parsed = dict(intr.get("parsed") or {})
    return {
        "buying_power": float(parsed.get("buying_power") or 50_000.0),
        "account_type": parsed.get("account_type") or "cash",
        "risk_profile": parsed.get("risk_profile") or "conservative",
        "strategies": list(parsed.get("strategies") or ["csp", "leaps"]),
        "max_positions": int(parsed.get("max_positions") or 6),
        "watchlist": list(parsed.get("watchlist") or []),
        "exclude": list(parsed.get("exclude") or []),
        "knowledge_level": parsed.get("knowledge_level") or "intermediate",
    }


# ------------------------------------------------------------------- market overview strip
STRIP_TICKERS: tuple[str, ...] = ("SPY", "QQQ")
STRIP_HISTORY_DAYS = 90  # the window market_data_node already fetched, so live runs hit the cache


@dataclass(frozen=True)
class StripQuote:
    ticker: str
    price: float | None  # None when the source had no quote
    change: float | None  # fraction against the previous close; None without two closes
    in_run: bool  # the quote is this run's snapshot, not an extra lookup


@dataclass(frozen=True)
class MarketStrip:
    """What the market overview strip shows (Phase 12, 12.7); built once per run."""

    quotes: tuple[StripQuote, ...]
    regime: MarketRegime | None
    provider: str
    live: bool
    fetched_at: datetime | None  # oldest quote shown: the fixture's recording or the fetch time
    age: str


def day_change(price: float, closes: Sequence[float]) -> float | None:
    """``price`` against the previous daily close, as a fraction.

    A daily series may or may not already end on today's bar (after the close, or in a recorded
    fixture, the last close *is* the quote), so a last close equal to the price is today's and the
    one before it is the previous close.
    """
    history = [c for c in closes if c > 0]
    if history and abs(history[-1] - price) < 1e-9:
        history = history[:-1]
    if not history:
        return None
    return price / history[-1] - 1.0


def data_age(live: bool, fetched_at: datetime | None, now: datetime) -> str:
    """The freshness line under the provider: quotes are recorded or delayed, never real-time."""
    if fetched_at is None:
        return "no quotes fetched"
    if not live:
        return f"fixture, recorded {fetched_at:%Y-%m-%d}"
    minutes = max(int((now - fetched_at).total_seconds() // 60), 0)
    return f"delayed quotes, fetched {fetched_at:%H:%M} UTC ({minutes} min ago)"


def market_strip(
    md: MarketData,
    snapshots: Mapping[str, TickerSnapshot],
    regime: MarketRegime | None,
    *,
    now: datetime | None = None,
    tickers: Sequence[str] = STRIP_TICKERS,
) -> MarketStrip:
    """SPY and QQQ with their day change, the regime, the provider and the data age.

    A ticker the run screened reuses its snapshot; one it did not is looked up through the same
    cached facade. Either lookup failing leaves that cell empty instead of failing the page.
    """
    live = md.source.name != "fixture"
    quotes: list[StripQuote] = []
    stamps = [s.spot.as_of for s in snapshots.values()]
    for ticker in tickers:
        snap = snapshots.get(ticker)
        spot = snap.spot if snap is not None else None
        if spot is None:
            try:
                spot = md.get_spot(ticker)
            except Exception:  # no quote for this cell
                quotes.append(StripQuote(ticker, None, None, False))
                continue
        stamps.append(spot.as_of)
        try:
            change = day_change(spot.price, md.get_close_history(ticker, STRIP_HISTORY_DAYS))
        except Exception:  # a price without a history still shows
            change = None
        quotes.append(StripQuote(ticker, spot.price, change, snap is not None))
    # the oldest quote on screen: a cache hit keeps its original fetch time, so this is the age
    # of the stalest number, not the time of the run
    fetched_at = min(stamps) if stamps else (regime.as_of if regime is not None else None)
    return MarketStrip(
        quotes=tuple(quotes),
        regime=regime,
        provider=md.source.name,
        live=live,
        fetched_at=fetched_at,
        age=data_age(live, fetched_at, now or md.now()),
    )
