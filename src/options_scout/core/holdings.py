"""Holdings analysis (Phase 12, docs/capstone-plan.md section 12.6).

What the user already owns, valued at the run's prices: allocation and sector weights, an
HHI-based diversification score, the weighted expense ratio of any ETFs, beta-weighted exposure
to the index, covered-call-eligible lots, and the concentration each screened cash-secured put
would create if it were assigned. Deterministic and golden-tested; the LLM only narrates.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import NormalDist

from options_scout.config import HoldingsConfig
from options_scout.core.models import (
    Holding,
    HoldingsAnalysis,
    HoldingValue,
    OptionCandidate,
    PostAssignment,
)
from options_scout.core.sizing import concentration_base


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


@dataclass(frozen=True)
class BetaFit:
    """An OLS beta of daily log returns on the index's, with its standard error."""

    beta: float
    se: float
    n_returns: int

    def interval(self, level: float) -> tuple[float, float]:
        """The two-sided ``level`` range, beta ± z·se (normal approximation; with the 60 or more
        returns ``beta_min_returns`` requires, t and z differ in the second decimal)."""
        z = NormalDist().inv_cdf(0.5 + level / 2.0)
        return self.beta - z * self.se, self.beta + z * self.se


def _log_returns(series: Mapping[date, float], common: Sequence[date]) -> list[float]:
    return [math.log(series[common[i]] / series[common[i - 1]]) for i in range(1, len(common))]


def _ols(y: Sequence[float], x: Sequence[float]) -> BetaFit | None:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx <= 0:
        return None
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / sxx
    rss = sum((b - my - slope * (a - mx)) ** 2 for a, b in zip(x, y, strict=True))
    return BetaFit(beta=slope, se=math.sqrt(max(rss, 0.0) / (n - 2) / sxx), n_returns=n)


def beta_fit(
    closes: Sequence[tuple[date, float]],
    index_closes: Sequence[tuple[date, float]],
    *,
    min_returns: int,
) -> BetaFit | None:
    """Slope of daily log returns on the index's, with its standard error, over the dates both
    series have (W25 step 1: joined on date, never truncated to the same length, so one missing
    bar cannot shift every later return by a day). ``None`` with fewer than ``min_returns``
    common returns, a non-positive close or a flat index."""
    a = dict(closes)
    b = dict(index_closes)
    common = sorted(a.keys() & b.keys())
    if len(common) - 1 < max(min_returns, 2):
        return None
    if any(a[d] <= 0 or b[d] <= 0 for d in common):
        return None
    return _ols(_log_returns(a, common), _log_returns(b, common))


def beta(
    closes: Sequence[tuple[date, float]],
    index_closes: Sequence[tuple[date, float]],
    *,
    min_returns: int,
) -> float | None:
    """The point estimate of ``beta_fit``."""
    fit = beta_fit(closes, index_closes, min_returns=min_returns)
    return fit.beta if fit else None


def portfolio_beta_fit(
    weights: Mapping[str, float],
    closes: Mapping[str, Sequence[tuple[date, float]]],
    index_closes: Sequence[tuple[date, float]],
    *,
    min_returns: int,
) -> BetaFit | None:
    """Beta-weighted exposure as one regression: the value-weighted daily return of the holdings
    in ``weights`` on the index's, over the dates all of them and the index share. Its slope is
    the weighted sum of the betas (OLS is linear in the response); its standard error counts the
    holdings moving together, which adding the separate ranges would not."""
    if not weights:
        return None
    series = {t: dict(closes[t]) for t in weights if t in closes}
    if len(series) < len(weights):
        return None
    idx = dict(index_closes)
    common_set = set(idx)
    for sr in series.values():
        common_set &= sr.keys()
    common = sorted(common_set)
    if len(common) - 1 < max(min_returns, 2):
        return None
    if any(idx[d] <= 0 or sr[d] <= 0 for d in common for sr in series.values()):
        return None
    per = {t: _log_returns(sr, common) for t, sr in series.items()}
    port = [sum(weights[t] * per[t][i] for t in per) for i in range(len(common) - 1)]
    return _ols(port, _log_returns(idx, common))


def _range(fit: BetaFit | None, level: float) -> tuple[float | None, float | None]:
    if fit is None:
        return None, None
    lo, hi = fit.interval(level)
    return lo, hi


def covered_call_lots(shares: float, lot: int) -> int:
    return int(shares // lot) if lot > 0 else 0


# ------------------------------------------------------------------------------ analysis
def analyse_holdings(
    holdings: Sequence[Holding],
    prices: Mapping[str, float],
    sectors: Mapping[str, str],
    cfg: HoldingsConfig,
    betas: Mapping[str, float | None] | None = None,
    *,
    closes: Mapping[str, Sequence[tuple[date, float]]] | None = None,
    index_closes: Sequence[tuple[date, float]] | None = None,
) -> HoldingsAnalysis:
    """Value every holding at ``prices`` (tickers without a price are skipped and noted).

    With dated ``closes`` and ``index_closes`` each beta is fitted here with its
    ``cfg.beta_interval`` range, and the beta-weighted exposure is the regression of the
    portfolio's own weighted returns (``portfolio_beta_fit``) with its range. Without them,
    ``betas`` are taken as given and no range is reported."""
    notes: list[str] = []
    fits: dict[str, BetaFit | None] = {}
    if closes is not None and index_closes is not None:
        for t, sr in closes.items():
            fits[t] = beta_fit(sr, index_closes, min_returns=cfg.beta_min_returns)
        short = sorted(t for t, f in fits.items() if f is None)
        if short:
            notes.append(
                f"beta unknown for {', '.join(short)}: fewer than {cfg.beta_min_returns} daily "
                f"returns on dates shared with {cfg.beta_index}"
            )
        betas = {t: (f.beta if f else None) for t, f in fits.items()}
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
                beta_low=_range(fits.get(h.ticker), cfg.beta_interval)[0],
                beta_high=_range(fits.get(h.ticker), cfg.beta_interval)[1],
                covered_call_lots=covered_call_lots(h.shares, cfg.covered_call_lot),
            )
        )
        by_sector[sector] = by_sector.get(sector, 0.0) + weight
    h_index = hhi(p.weight for p in positions)
    with_er = [p for p in positions if p.expense_ratio is not None]
    # W25 step 4: the drag on the whole portfolio, and the ratio across the ETFs alone
    weighted_er = sum(p.weight * (p.expense_ratio or 0.0) for p in with_er) if with_er else None
    etf_weight = sum(p.weight for p in with_er)
    etf_er = (weighted_er / etf_weight) if weighted_er is not None and etf_weight > 0 else None
    with_beta = [p for p in positions if p.beta is not None]
    beta_exposure = sum(p.weight * (p.beta or 0.0) for p in with_beta) if with_beta else None
    exposure_range: tuple[float | None, float | None] = (None, None)
    if fits and with_beta and closes is not None and index_closes is not None:
        port_fit = portfolio_beta_fit(
            {p.ticker: p.weight for p in with_beta},
            closes,
            index_closes,
            min_returns=cfg.beta_min_returns,
        )
        if port_fit is not None:  # the one regression owns the figure and its range
            beta_exposure = port_fit.beta
            exposure_range = _range(port_fit, cfg.beta_interval)
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
        etf_expense_ratio=etf_er,
        beta_weighted_exposure=beta_exposure,
        beta_weighted_exposure_low=exposure_range[0],
        beta_weighted_exposure_high=exposure_range[1],
        beta_interval=cfg.beta_interval if fits else None,
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
