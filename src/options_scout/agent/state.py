"""Typed LangGraph state (section 5.3) composed of per-specialist slices (section 5.0).

``AgentState`` is the flat ``TypedDict`` LangGraph uses as its channel schema: the reducers for
the per-ticker fan-out live on the flat keys, and every specialist subgraph shares the schema so
specialists exchange data only through typed state. The ``*Slice`` Pydantic models partition
those keys by owner: a specialist may write only the keys of its slice plus the shared ``RunSlice``
bookkeeping, and ``tests/agent/test_agents.py`` enforces both the partition (the slices cover the
state exactly once) and the ownership (each agent fills only its slice). The flat keys are the
Phase 9 keys, unchanged, so the UI, API and evals keep working for one release.
"""

from __future__ import annotations

import operator
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypedDict, TypeVar, get_args, get_origin, get_type_hints

from pydantic import BaseModel, Field

from options_scout.core.models import (
    AllocationPlan,
    ChatTurn,
    Citation,
    ClassifiedNews,
    ComplianceReport,
    Goal,
    GoalPlan,
    Holding,
    HoldingsAnalysis,
    Intent,
    MarketRegime,
    Narrative,
    NewsBrief,
    NewsFlag,
    NewsItem,
    OptionCandidate,
    PMCCCandidate,
    ProfileParse,
    QualityCheck,
    RankedCandidate,
    RiskReport,
    ScreeningReport,
    SizedPortfolio,
    SuitabilityFacts,
    TaxFacts,
    TickerSnapshot,
    TokenUsage,
    TrendSignal,
    UserProfile,
    VerificationResult,
)
from options_scout.rag.models import Chunk, RetrievalResult


def merge_dicts(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(a or {})
    out.update(b or {})
    return out


class AgentState(TypedDict, total=False):
    # input
    request_text: str
    profile_override: dict[str, Any] | None  # full/partial profile supplied by the UI/API
    question: str | None  # Phase 10: an education question (concept Q&A) instead of a screen
    message: str | None  # Phase 10 (10.5): the latest chat turn, classified by route_node
    intent: Intent | None
    review_requested: bool  # refine_profile: show human_review once even if complete
    handoff: dict[str, Any] | None  # a new/refined screen to start on a fresh thread
    what_if_profile: dict[str, Any] | None
    what_if_diff: list[str]
    goal_text: str | None  # Phase 12 (12.3): the chat turn that states a goal
    holdings_text: str | None  # Phase 12 (12.4): the chat turn that lists holdings
    news_text: str | None  # Phase 12 (12.5): the chat turn that asks about news
    tax_text: str | None  # Phase 12 (12.6): the chat turn that asks about tax or accounts
    # intake
    parsed: ProfileParse | None
    profile: UserProfile | None
    profile_complete: bool
    # deterministic pipeline
    regime: MarketRegime | None
    allocation: AllocationPlan | None
    trends: list[TrendSignal]
    social_scores: dict[str, float]
    evidence: list[Chunk]  # Phase 10: the run's evidence posts as a retrievable collection
    universe: list[str]
    market_data: Annotated[dict[str, TickerSnapshot], merge_dicts]  # only tickers that passed
    quality: Annotated[dict[str, QualityCheck], merge_dicts]  # every ticker, passed or not
    candidates: Annotated[list[OptionCandidate], operator.add]
    pmcc_pairs: Annotated[list[PMCCCandidate], operator.add]
    ranked: list[RankedCandidate]
    # News Desk (Phase 12, 12.5)
    news_items: list[NewsItem]
    news_classified: list[ClassifiedNews]
    news_briefs: list[NewsBrief]
    news_flags: list[NewsFlag]
    portfolio: SizedPortfolio | None
    holdings: list[Holding]  # Phase 12 (12.4): what the user already owns
    holdings_analysis: HoldingsAnalysis | None
    risk: RiskReport | None
    suitability_facts: SuitabilityFacts | None  # Phase 10: computed by Risk for Compliance
    # Goal Planning (Phase 12, 12.3)
    goal: Goal | None
    goal_plan: GoalPlan | None
    goal_clarification: str | None  # what the goal text did not state
    # Tax & Accounts (Phase 12, 12.6)
    tax_facts: TaxFacts | None
    # Education (Phase 10: retrieval + tagged narrative + concept answers)
    explain_payload: dict[str, Any] | None
    sources: list[Chunk]  # the [S1]…[Sn] chunks the narrative/answer may cite
    retrievals: list[RetrievalResult]  # retrieval log for the Under-the-hood tab
    narrative: Narrative | None
    citations: list[Citation]  # sources the final text actually cites, numbered
    answer: Narrative | None  # concept Q&A reply (question runs)
    # verification (Phase 10 step 10.4: the full ComplianceReport plus the run's audit log)
    verification: VerificationResult | None
    verifier_feedback: str | None
    compliance: ComplianceReport | None
    audit_log: Annotated[list[ComplianceReport], operator.add]
    # bookkeeping
    retries: Annotated[dict[str, int], merge_dicts]
    errors: Annotated[list[str], operator.add]
    nodes_visited: Annotated[list[str], operator.add]
    node_latency_ms: Annotated[dict[str, float], merge_dicts]
    agents_visited: Annotated[list[str], operator.add]  # Phase 10: one entry per specialist run
    agent_latency_ms: Annotated[dict[str, float], merge_dicts]  # Phase 10: summed over retries
    token_usage: Annotated[list[TokenUsage], operator.add]
    data_source_status: Annotated[dict[str, str], merge_dicts]
    run_id: str
    started_at: str
    report: ScreeningReport | None
    report_markdown: str | None
    chat_history: Annotated[list[ChatTurn], operator.add]  # written by the chat session
    # fan-out payload (only present inside a Send branch)
    ticker: str


# ----------------------------------------------------------------------------- slices (5.0)


class OrchestratorSlice(BaseModel):
    """Owned by the Orchestrator: the request and the confirmed profile."""

    request_text: str = ""
    profile_override: dict[str, Any] | None = None
    question: str | None = None
    message: str | None = None
    intent: Intent | None = None
    review_requested: bool = False
    handoff: dict[str, Any] | None = None
    what_if_profile: dict[str, Any] | None = None
    what_if_diff: list[str] = Field(default_factory=list)
    goal_text: str | None = None
    holdings_text: str | None = None
    news_text: str | None = None
    tax_text: str | None = None
    parsed: ProfileParse | None = None
    profile: UserProfile | None = None
    profile_complete: bool = False


class MarketDataSlice(BaseModel):
    """Owned by Market Data (#1): regime, universe, snapshots and the quality gate."""

    regime: MarketRegime | None = None
    universe: list[str] = Field(default_factory=list)
    market_data: dict[str, TickerSnapshot] = Field(default_factory=dict)
    quality: dict[str, QualityCheck] = Field(default_factory=dict)


class MarketIntelligenceSlice(BaseModel):
    """Owned by Market Intelligence (#2): the consumer-trend board."""

    trends: list[TrendSignal] = Field(default_factory=list)
    social_scores: dict[str, float] = Field(default_factory=dict)
    evidence: list[Chunk] = Field(default_factory=list)


class StrategySlice(BaseModel):
    """Owned by Strategy (#3): screened and ranked candidates."""

    candidates: list[OptionCandidate] = Field(default_factory=list)
    pmcc_pairs: list[PMCCCandidate] = Field(default_factory=list)
    ranked: list[RankedCandidate] = Field(default_factory=list)


class NewsDeskSlice(BaseModel):
    """Owned by News Desk (Phase 12, #8): headlines, their labels, briefs and candidate flags."""

    news_items: list[NewsItem] = Field(default_factory=list)
    news_classified: list[ClassifiedNews] = Field(default_factory=list)
    news_briefs: list[NewsBrief] = Field(default_factory=list)
    news_flags: list[NewsFlag] = Field(default_factory=list)


class PortfolioSlice(BaseModel):
    """Owned by Portfolio (#4): allocation and the sized portfolio."""

    allocation: AllocationPlan | None = None
    portfolio: SizedPortfolio | None = None
    holdings: list[Holding] = Field(default_factory=list)
    holdings_analysis: HoldingsAnalysis | None = None


class RiskSlice(BaseModel):
    """Owned by Risk (#5): constraint checks, stress tests and the suitability facts."""

    risk: RiskReport | None = None
    suitability_facts: SuitabilityFacts | None = None


class GoalPlanningSlice(BaseModel):
    """Owned by Goal Planning (Phase 12, #7): the parsed goal and its deterministic plan."""

    goal: Goal | None = None
    goal_plan: GoalPlan | None = None
    goal_clarification: str | None = None


class TaxSlice(BaseModel):
    """Owned by Tax & Accounts (Phase 12, #9): the illustrative facts a tax reply may quote."""

    tax_facts: TaxFacts | None = None


class EducationSlice(BaseModel):
    """Owned by Education (#6): retrieved sources, the tagged narrative or answer, citations."""

    explain_payload: dict[str, Any] | None = None
    sources: list[Chunk] = Field(default_factory=list)
    retrievals: list[RetrievalResult] = Field(default_factory=list)
    narrative: Narrative | None = None
    citations: list[Citation] = Field(default_factory=list)
    answer: Narrative | None = None


class ComplianceSlice(BaseModel):
    """Owned by Compliance: the eight checks' report, the retry feedback and the audit log."""

    verification: VerificationResult | None = None
    verifier_feedback: str | None = None
    compliance: ComplianceReport | None = None
    audit_log: list[ComplianceReport] = Field(default_factory=list)


class RunSlice(BaseModel):
    """Shared bookkeeping every agent may append to, plus the parent-level report keys."""

    run_id: str = ""
    started_at: str = ""
    retries: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    nodes_visited: list[str] = Field(default_factory=list)
    node_latency_ms: dict[str, float] = Field(default_factory=dict)
    agents_visited: list[str] = Field(default_factory=list)
    agent_latency_ms: dict[str, float] = Field(default_factory=dict)
    token_usage: list[TokenUsage] = Field(default_factory=list)
    data_source_status: dict[str, str] = Field(default_factory=dict)
    report: ScreeningReport | None = None
    report_markdown: str | None = None
    chat_history: list[ChatTurn] = Field(default_factory=list)
    ticker: str | None = None


SLICES: dict[str, type[BaseModel]] = {
    "orchestrator_agent": OrchestratorSlice,
    "market_intelligence_agent": MarketIntelligenceSlice,
    "market_data_agent": MarketDataSlice,
    "strategy_agent": StrategySlice,
    "news_desk_agent": NewsDeskSlice,
    "portfolio_agent": PortfolioSlice,
    "risk_agent": RiskSlice,
    "goal_planning_agent": GoalPlanningSlice,
    "tax_agent": TaxSlice,
    "education_agent": EducationSlice,
    "compliance_agent": ComplianceSlice,
}

SliceT = TypeVar("SliceT", bound=BaseModel)


def slice_keys(model: type[BaseModel]) -> frozenset[str]:
    return frozenset(model.model_fields)


RUN_KEYS: frozenset[str] = slice_keys(RunSlice)


def slice_of(state: Mapping[str, Any], model: type[SliceT]) -> SliceT:
    """View the flat state through one slice (missing keys take the slice defaults)."""
    return model.model_validate({k: state[k] for k in model.model_fields if k in state})


ReducerKind = Literal["add", "merge", "last"]


def reducer_kinds() -> dict[str, ReducerKind]:
    """How each ``AgentState`` key is combined: list append, dict merge, or last value wins."""
    kinds: dict[str, ReducerKind] = {}
    for key, hint in get_type_hints(AgentState, include_extras=True).items():
        kind: ReducerKind = "last"
        if get_origin(hint) is Annotated:
            reducer = get_args(hint)[1]
            kind = "add" if reducer is operator.add else "merge"
        kinds[key] = kind
    return kinds


def state_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """The update a subgraph produced, given the state it started from and the state it ended in.

    Appended lists contribute only their new tail, merged dicts are re-sent whole (idempotent),
    and last-value keys are sent only when they changed. Returning this from the parent-graph
    node, instead of the subgraph's whole final state, applies every reducer exactly once.
    """
    kinds = reducer_kinds()
    out: dict[str, Any] = {}
    for key, value in after.items():
        kind = kinds.get(key, "last")
        if kind == "add":
            had = len(before.get(key) or ())
            tail = list(value)[had:]
            if tail:
                out[key] = tail
        elif kind == "merge":
            if value != before.get(key):
                out[key] = value
        elif key not in before or value != before[key]:
            out[key] = value
    return out
