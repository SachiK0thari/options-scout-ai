"""Holdings analysis (Phase 12, docs/capstone-plan.md section 12.6).

What the user already owns, valued at the run's prices: allocation and sector weights, an
HHI-based diversification score, the weighted expense ratio of any ETFs, beta-weighted exposure
to the index, covered-call-eligible lots, and the concentration each screened cash-secured put
would create if it were assigned. Deterministic and golden-tested; the LLM only narrates.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from options_scout.config import HoldingsConfig
from options_scout.core.models import (
    Holding,
    HoldingsAnalysis,
    HoldingValue,
    OptionCandidate,
    PostAssignment,
)
from options_scout.core.sizing import concentration_base

MIN_BETA_POINTS = 20


def merge_holdings(holdings: Iterable[Holding]) -> list[Holding]:
    """One row per ticker: shares summed, cost basis share-weighted when every lot has one."""
    by: dict[str, list[Holding]] = {}
    for h in holdings:
        by.setdefault(h.ticker, []).append(h)
    out: list[Holding] = []
    for ticker, lots in by.items():
        shares = sum(lot.shares for lot in lots)
        costs = [lot.cost_basis for lot in lots]
        basis = (
            sum(lot.shares * lot.cost_basis for lot in lots if lot.cost_basis is not None) / shares
            if all(c is not None for c in costs)
            else None
        )
        accounts = {lot.account for lot in lots}
        out.append(
            Holding(
                ticker=ticker,
                shares=shares,
                cost_basis=basis,
                account=accounts.pop() if len(accounts) == 1 else None,
            )
        )
    return sorted(out, key=lambda h: h.ticker)


# ------------------------------------------------------------------------------- metrics
def hhi(weights: Iterable[float]) -> float:
    """Herfindahl-Hirschman index of portfolio weights: 1.0 for one position, 1/N for N equal."""
    ws = [w for w in weights if w > 0]
    total = sum(ws)
    if total <= 0:
        return 0.0
    return sum((w / total) ** 2 for w in ws)


def diversification_score(hhi_value: float) -> float:
    """100 x (1 - HHI): 0 for a single position, 90 for ten equal ones, 95 for twenty."""
    return 100.0 * (1.0 - min(max(hhi_value, 0.0), 1.0))


def beta(closes: Sequence[float], index_closes: Sequence[float]) -> float | None:
    """Slope of daily log returns on the index's: cov / var. ``None`` with too little history."""
    n = min(len(closes), len(index_closes))
    if n < MIN_BETA_POINTS:
        return None
    a = closes[-n:]
    b = index_closes[-n:]
    if any(x <= 0 for x in a) or any(x <= 0 for x in b):
        return None
    ra = [math.log(a[i] / a[i - 1]) for i in range(1, n)]
    rb = [math.log(b[i] / b[i - 1]) for i in range(1, n)]
    mean_a = sum(ra) / len(ra)
    mean_b = sum(rb) / len(rb)
    var_b = sum((y - mean_b) ** 2 for y in rb)
    if var_b <= 0:
        return None
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb, strict=True))
    return cov / var_b


def covered_call_lots(shares: float, lot: int) -> int:
    return int(shares // lot) if lot > 0 else 0


# ------------------------------------------------------------------------------ analysis
def analyse_holdings(
    holdings: Sequence[Holding],
    prices: Mapping[str, float],
    sectors: Mapping[str, str],
    cfg: HoldingsConfig,
    betas: Mapping[str, float | None] | None = None,
) -> HoldingsAnalysis:
    """Value every holding at ``prices`` (tickers without a price are skipped and noted)."""
    notes: list[str] = []
    merged = merge_holdings(holdings)
    valued: list[tuple[Holding, float]] = []
    for h in merged:
        price = prices.get(h.ticker)
        if price is None or price <= 0:
            notes.append(f"{h.ticker}: no price available, left out of the totals")
            continue
        valued.append((h, price))
    total = sum(h.shares * price for h, price in valued)
    positions: list[HoldingValue] = []
    by_sector: dict[str, float] = {}
    for h, price in valued:
        value = h.shares * price
        weight = value / total if total > 0 else 0.0
        sector = sectors.get(h.ticker) or cfg.sectors.get(h.ticker) or "Unknown"
        cost = h.shares * h.cost_basis if h.cost_basis is not None else None
        positions.append(
            HoldingValue(
                ticker=h.ticker,
                shares=h.shares,
                price=price,
                market_value=value,
                cost=cost,
                unrealised_pnl=value - cost if cost is not None else None,
                weight=weight,
                sector=sector,
                expense_ratio=cfg.expense_ratio(h.ticker),
                beta=(betas or {}).get(h.ticker),
                covered_call_lots=covered_call_lots(h.shares, cfg.covered_call_lot),
            )
        )
        by_sector[sector] = by_sector.get(sector, 0.0) + weight
    h_index = hhi(p.weight for p in positions)
    with_er = [p for p in positions if p.expense_ratio is not None]
    weighted_er = sum(p.weight * (p.expense_ratio or 0.0) for p in with_er) if with_er else None
    with_beta = [p for p in positions if p.beta is not None]
    beta_exposure = sum(p.weight * (p.beta or 0.0) for p in with_beta) if with_beta else None
    if with_beta and len(with_beta) < len(positions):
        notes.append(
            f"beta known for {len(with_beta)} of {len(positions)} positions; "
            "exposure covers those only"
        )
    largest = max(positions, key=lambda p: p.weight, default=None)
    largest_sector = max(by_sector.items(), key=lambda kv: kv[1], default=None)
    return HoldingsAnalysis(
        positions=positions,
        total_value=total,
        by_sector=by_sector,
        hhi=h_index,
        effective_positions=(1.0 / h_index) if h_index > 0 else 0.0,
        diversification_score=diversification_score(h_index) if positions else 0.0,
        weighted_expense_ratio=weighted_er,
        beta_weighted_exposure=beta_exposure,
        largest_position=largest.ticker if largest else None,
        largest_sector=largest_sector[0] if largest_sector else None,
        covered_call_eligible=[p.ticker for p in positions if p.covered_call_lots >= 1],
        notes=notes,
    )


def post_assignment(
    analysis: HoldingsAnalysis,
    candidate: OptionCandidate,
    contracts: int,
    *,
    buying_power: float,
    other_cash_on_ticker: float = 0.0,
) -> PostAssignment:
    """Weight of ``candidate.ticker`` after the put is assigned, as a share of holdings plus buying
    power: the base the sizer and the risk check use (``sizing.concentration_base``, PRD 3.10).

    The collateral is cash already inside that base; assignment turns it into stock, so the base
    does not change and only the ticker's numerator grows. ``other_cash_on_ticker`` adds the cash
    of other sized puts on the same ticker, so the figure matches the risk check, which assumes
    every put on a ticker is assigned."""
    if candidate.strategy != "csp" or contracts < 1:
        raise ValueError("post-assignment concentration applies to cash-secured puts")
    shares = contracts * 100
    cash_used = candidate.strike * shares
    before_value = sum(p.market_value for p in analysis.positions if p.ticker == candidate.ticker)
    base = concentration_base(analysis, buying_power)
    weight_before = before_value / base if base > 0 else 0.0
    after_value = before_value + cash_used + other_cash_on_ticker
    weight_after = after_value / base if base > 0 else 1.0
    return PostAssignment(
        candidate_id=candidate.id,
        ticker=candidate.ticker,
        strike=candidate.strike,
        shares_added=shares,
        cash_used=cash_used,
        weight_before=weight_before,
        weight_after=weight_after,
        includes_other_puts=other_cash_on_ticker > 0,
    )


def concentration_after_assignment(
    analysis: HoldingsAnalysis,
    candidates: Sequence[tuple[OptionCandidate, int]],
    *,
    buying_power: float,
    sized: bool = False,
) -> list[PostAssignment]:
    """One row per cash-secured put. With ``sized`` the pairs are the sized portfolio, which can
    hold several puts on one ticker: each row then counts every put on its ticker, as the risk
    check does. Without it the pairs are alternatives (one contract of each screened put) and each
    row stands alone."""
    puts = [(c, n) for c, n in candidates if c.strategy == "csp" and n >= 1]
    cash_by_ticker: dict[str, float] = {}
    if sized:
        for c, n in puts:
            cash_by_ticker[c.ticker] = cash_by_ticker.get(c.ticker, 0.0) + c.strike * n * 100
    return [
        post_assignment(
            analysis,
            c,
            n,
            buying_power=buying_power,
            other_cash_on_ticker=(cash_by_ticker[c.ticker] - c.strike * n * 100 if sized else 0.0),
        )
        for c, n in puts
    ]
