"""holdings_analysis_node (Portfolio, Phase 12 step 12.4): ``core.holdings.analyse_holdings``.

Prices come from the run's snapshots when the ticker is in the universe and from the market-data
facade otherwise (fixture mode knows ten tickers; anything else is left out and said so). Betas
use the same 90-day close history the quality gate fetches, against the configured index. When
the thread holds a report, every cash-secured-put candidate's post-assignment concentration is
computed too. No LLM.
"""

from __future__ import annotations

from collections.abc import Callable
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


def _betas(deps: Deps, tickers: list[str]) -> dict[str, float | None]:
    cfg = deps.cfg.holdings
    try:
        index = deps.md.source.get_index_history(cfg.beta_index, cfg.beta_lookback_days)
    except Exception:
        try:
            index = deps.md.get_close_history(cfg.beta_index, cfg.beta_lookback_days)
        except Exception:
            return {}
    out: dict[str, float | None] = {}
    for t in tickers:
        try:
            closes = deps.md.get_close_history(t, cfg.beta_lookback_days)
        except Exception:
            continue
        out[t] = core_holdings.beta(closes, index)
    return out


def _post_assignment(state: AgentState, analysis: HoldingsAnalysis) -> list[Any]:
    """Concentration after assignment for the sized CSPs (their contracts) or, before sizing, for
    every CSP candidate at one contract."""
    portfolio = state.get("portfolio")
    cands: dict[str, OptionCandidate] = {c.id: c for c in state.get("candidates") or []}
    pairs: list[tuple[OptionCandidate, int]] = []
    if portfolio is not None and portfolio.positions:
        for p in portfolio.positions:
            c = cands.get(p.candidate_id)
            if c is not None and c.strategy == "csp":
                pairs.append((c, p.contracts))
    else:
        pairs = [(c, 1) for c in cands.values() if c.strategy == "csp"]
    return core_holdings.concentration_after_assignment(analysis, pairs)


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def holdings_analysis_node(state: AgentState) -> dict[str, Any]:
        holdings = list(state.get("holdings") or [])
        if not holdings:
            return {"holdings_analysis": None}
        tickers = sorted({h.ticker for h in holdings})
        prices, sectors, notes = _prices_and_sectors(deps, state, tickers)
        betas = _betas(deps, [t for t in tickers if t in prices])
        analysis = core_holdings.analyse_holdings(
            holdings, prices, sectors, deps.cfg.holdings, betas=betas
        )
        post = _post_assignment(state, analysis) if analysis.positions else []
        analysis = analysis.model_copy(
            update={"post_assignment": post, "notes": [*analysis.notes, *notes]}
        )
        return {"holdings_analysis": analysis}

    return holdings_analysis_node
