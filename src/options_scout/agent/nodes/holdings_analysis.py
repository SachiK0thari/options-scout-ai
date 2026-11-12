"""holdings_analysis_node (Portfolio, Phase 12 step 12.4): ``core.holdings.analyse_holdings``.

Prices come from the run's snapshots when the ticker is in the universe and from the market-data
facade otherwise (fixture mode knows ten tickers; anything else is left out and said so). Betas
use the same 90-day close history the quality gate fetches, against the configured index. When
the thread holds a report, every cash-secured-put candidate's post-assignment concentration is
computed too. No LLM.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core import holdings as core_holdings
from options_scout.core.models import HoldingsAnalysis, OptionCandidate


def _prices_and_sectors(
    deps: Deps, state: AgentState, tickers: list[str]
) -> tuple[dict[str, float], dict[str, str], list[str]]:
    prices: dict[str, float] = {}
    sectors: dict[str, str] = {}
    notes: list[str] = []
    snapshots = state.get("market_data") or {}
    for t in tickers:
        snap = snapshots.get(t)
        if snap is not None:
            prices[t] = snap.spot.price
            sectors[t] = snap.spot.sector
            continue
        try:
            quote = deps.md.get_spot(t)
        except Exception as exc:
            notes.append(f"{t}: no price from {deps.md.source.name} ({type(exc).__name__})")
            continue
        prices[t] = quote.price
        sectors[t] = quote.sector
    for t in tickers:
        curated = deps.cfg.quality.get(t)
        if curated is not None:
            sectors[t] = curated.sector
    return prices, sectors, notes


DatedCloses = list[tuple[date, float]]


def _dated_closes(
    deps: Deps, tickers: list[str]
) -> tuple[dict[str, DatedCloses] | None, DatedCloses | None, list[str]]:
    """Dated closes of each holding and of ``beta_index`` (W25), for the betas, their ranges and
    the portfolio regression ``analyse_holdings`` fits. A source without dates (the bundled
    fixtures) gives none and says so, rather than a misaligned beta."""
    cfg = deps.cfg.holdings
    try:
        index = deps.md.get_dated_close_history(cfg.beta_index, cfg.beta_lookback_days)
    except Exception as exc:
        return None, None, [f"beta not computed: no dated {cfg.beta_index} closes ({exc})"]
    closes: dict[str, DatedCloses] = {}
    for t in tickers:
        try:
            closes[t] = deps.md.get_dated_close_history(t, cfg.beta_lookback_days)
        except Exception:
            continue
    return closes, index, []


def _post_assignment(state: AgentState, analysis: HoldingsAnalysis) -> list[Any]:
    """Concentration after assignment for the sized CSPs (their contracts, every put on a ticker
    counted together, as the risk check does) or, before sizing, for every CSP candidate at one
    contract. Measured against holdings plus the profile's buying power; with no profile on the
    thread there is no base to measure against, so nothing is computed."""
    profile = state.get("profile")
    if profile is None:
        return []
    portfolio = state.get("portfolio")
    cands: dict[str, OptionCandidate] = {c.id: c for c in state.get("candidates") or []}
    pairs: list[tuple[OptionCandidate, int]] = []
    sized = portfolio is not None and bool(portfolio.positions)
    if portfolio is not None and portfolio.positions:
        for p in portfolio.positions:
            c = cands.get(p.candidate_id)
            if c is not None and c.strategy == "csp":
                pairs.append((c, p.contracts))
    else:
        pairs = [(c, 1) for c in cands.values() if c.strategy == "csp"]
    return core_holdings.concentration_after_assignment(
        analysis, pairs, buying_power=profile.buying_power, sized=sized
    )


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def holdings_analysis_node(state: AgentState) -> dict[str, Any]:
        holdings = list(state.get("holdings") or [])
        if not holdings:
            return {"holdings_analysis": None}
        tickers = sorted({h.ticker for h in holdings})
        prices, sectors, notes = _prices_and_sectors(deps, state, tickers)
        closes, index, beta_notes = _dated_closes(deps, [t for t in tickers if t in prices])
        analysis = core_holdings.analyse_holdings(
            holdings, prices, sectors, deps.cfg.holdings, closes=closes, index_closes=index
        )
        post = _post_assignment(state, analysis) if analysis.positions else []
        analysis = analysis.model_copy(
            update={"post_assignment": post, "notes": [*analysis.notes, *notes, *beta_notes]}
        )
        return {"holdings_analysis": analysis}

    return holdings_analysis_node
