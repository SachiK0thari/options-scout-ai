"""Typed LangGraph state with reducers for the per-ticker fan-out (section 5.3)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from options_scout.core.models import (
    AllocationPlan,
    MarketRegime,
    OptionCandidate,
    PMCCCandidate,
    ProfileParse,
    RankedCandidate,
    RiskReport,
    ScreeningReport,
    SizedPortfolio,
    TickerSnapshot,
    TokenUsage,
    TrendSignal,
    UserProfile,
    VerificationResult,
)


def merge_dicts(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(a or {})
    out.update(b or {})
    return out


class AgentState(TypedDict, total=False):
    # input
    request_text: str
    profile_override: dict[str, Any] | None  # full/partial profile supplied by the UI/API
    # intake
    parsed: ProfileParse | None
    profile: UserProfile | None
    profile_complete: bool
    # deterministic pipeline
    regime: MarketRegime | None
    allocation: AllocationPlan | None
    trends: list[TrendSignal]
    social_scores: dict[str, float]
    universe: list[str]
    market_data: Annotated[dict[str, TickerSnapshot], merge_dicts]
    candidates: Annotated[list[OptionCandidate], operator.add]
    pmcc_pairs: Annotated[list[PMCCCandidate], operator.add]
    ranked: list[RankedCandidate]
    portfolio: SizedPortfolio | None
    risk: RiskReport | None
    # LLM + verification
    explain_payload: dict[str, Any] | None
    narrative: str | None
    verification: VerificationResult | None
    verifier_feedback: str | None
    # bookkeeping
    retries: Annotated[dict[str, int], merge_dicts]
    errors: Annotated[list[str], operator.add]
    nodes_visited: Annotated[list[str], operator.add]
    node_latency_ms: Annotated[dict[str, float], merge_dicts]
    token_usage: Annotated[list[TokenUsage], operator.add]
    data_source_status: Annotated[dict[str, str], merge_dicts]
    run_id: str
    started_at: str
    report: ScreeningReport | None
    report_markdown: str | None
    # fan-out payload (only present inside a Send branch)
    ticker: str
