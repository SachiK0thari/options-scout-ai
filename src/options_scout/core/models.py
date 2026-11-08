"""Pydantic v2 models used at every boundary (tools, agent state, API, reports)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, field_validator

AccountType = Literal["cash", "margin", "portfolio_margin"]
RiskProfile = Literal["conservative", "balanced", "aggressive"]
KnowledgeLevel = Literal["beginner", "intermediate", "advanced"]  # Phase 12: learning path
Strategy = Literal["csp", "leaps", "pmcc"]
OptionKind = Literal["call", "put"]
CandidateStrategy = Literal["csp", "leaps", "pmcc_short_call"]
IVRankSource = Literal["history", "hv_proxy", "none"]
RegimeLabel = Literal["high_iv", "normal", "low_iv"]
EntityType = Literal["product", "brand", "company", "store"]
Materiality = Literal["high", "medium", "low"]
PostSourceName = Literal["reddit", "x"]
SourceName = Literal["reddit", "x", "wikipedia", "google_trends", "news"]
# Phase 11, section 4A: the bottleneck signal's vocabulary
BottleneckSourceName = Literal[
    "edgar", "fred", "csv_series", "transcripts", "news", "reddit", "google_trends"
]
SupplyRole = Literal["supplier", "customer"]
ConstraintSide = Literal["customer", "supplier", "neutral"]
ConstraintDirection = Literal["tightening", "easing", "neutral"]
ConstraintKind = Literal["lead_time", "price", "capacity", "deal", "coverage", "other"]
FalsifierOperator = Literal[">", ">=", "<", "<="]
BottleneckEvidenceKind = Literal["filing", "price", "headline", "post"]


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _all_strategies() -> set[Strategy]:
    return {"csp", "leaps", "pmcc"}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


GoalKind = Literal["income", "growth", "contribution", "fire"]
FireVariant = Literal["lean", "regular", "fat", "coast", "barista"]
FeasibilityStatus = Literal["fits", "stretch", "does_not_fit"]
LeverName = Literal["more_capital", "longer_horizon", "different_profile"]
NewsCategory = Literal[
    "earnings", "guidance", "product", "legal_regulatory", "macro", "m_and_a", "other"
]
NewsRelevance = Literal["high", "medium", "low"]


# ------------------------------------------------------------------------------- user
class UserProfile(Model):
    buying_power: PositiveFloat
    account_value: PositiveFloat
    account_type: AccountType
    risk_profile: RiskProfile
    strategies: set[Strategy] = Field(default_factory=_all_strategies)
    watchlist: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    max_positions: int = Field(default=8, ge=1, le=50)
    options_level: int | None = None  # broker approval level, informational only
    knowledge_level: KnowledgeLevel | None = None  # Phase 12: caps retrieval, sets the prose level

    @field_validator("watchlist", "exclude", mode="before")
    @classmethod
    def _normalise_tickers(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list | tuple | set):
            raise ValueError("expected a list of tickers")
        return sorted({str(t).upper().strip() for t in v if str(t).strip()})

    @field_validator("strategies")
    @classmethod
    def _non_empty(cls, v: set[Strategy]) -> set[Strategy]:
        if not v:
            raise ValueError("at least one strategy is required")
        return v


class ProfileParse(Model):
    """Structured-output schema for intake. Fields are optional so the LLM can say 'unknown'."""

    buying_power: float | None = None
    account_value: float | None = None
    account_type: AccountType | None = None
    risk_profile: RiskProfile | None = None
    strategies: list[Strategy] | None = None
    watchlist: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    max_positions: int | None = None
    knowledge_level: KnowledgeLevel | None = None  # Phase 12
    needs_clarification: list[str] = Field(
        default_factory=list, description="Required fields the text did not state unambiguously."
    )


# ----------------------------------------------------------------------------- market
class SpotQuote(Model):
    ticker: str
    price: PositiveFloat
    avg_volume: float = Field(ge=0)
    as_of: datetime
    sector: str = "Unknown"


class OptionQuote(Model):
    contract_symbol: str
    kind: OptionKind
    strike: PositiveFloat
    expiry: date
    bid: float = Field(ge=0)
    ask: float = Field(ge=0)
    last: float = Field(ge=0, default=0.0)
    volume: int = Field(ge=0, default=0)
    open_interest: int = Field(ge=0, default=0)
    iv: float = Field(ge=0)  # implied vol as a fraction, e.g. 0.25

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


class OptionChain(Model):
    ticker: str
    expiry: date
    as_of: datetime
    calls: list[OptionQuote] = Field(default_factory=list)
    puts: list[OptionQuote] = Field(default_factory=list)


class TickerSnapshot(Model):
    """Everything the screeners need for one ticker, built offline or live."""

    ticker: str
    as_of: datetime
    spot: SpotQuote
    chains: list[OptionChain]
    earnings_date: date | None
    hv30: float | None = Field(default=None, ge=0)
    dividend_yield: float = Field(default=0.0, ge=0)
    atm_iv: float | None = Field(default=None, ge=0)
    iv_rank: float | None = Field(default=None, ge=0, le=1)
    iv_rank_source: IVRankSource = "none"
    source_errors: list[str] = Field(default_factory=list)

    def expiries(self) -> list[date]:
        return sorted({c.expiry for c in self.chains})


class MarketRegime(Model):
    vix: float = Field(ge=0)
    vix_percentile: float = Field(ge=0, le=100)
    risk_free_rate: float = Field(ge=-0.05, le=0.5)
    label: RegimeLabel
    as_of: datetime
    source: Literal["live", "fixture"] = "fixture"


class AllocationPlan(Model):
    risk_profile: RiskProfile
    account_type: AccountType
    buying_power: PositiveFloat
    csp_pct: float = Field(ge=0, le=1)
    leaps_pct: float = Field(ge=0, le=1)
    cash_pct: float = Field(ge=0, le=1)
    csp_dollars: float = Field(ge=0)
    leaps_dollars: float = Field(ge=0)
    cash_dollars: float = Field(ge=0)
    tilt: Literal["none", "to_csp", "to_leaps"]
    rationale: list[str]


# ---------------------------------------------------------------------------- pricing
class Greeks(Model):
    delta: float
    gamma: float
    theta: float  # per calendar day, option price units
    vega: float  # per 1 vol point (0.01)
    price: float


# --------------------------------------------------------------------------- screeners
class OptionCandidate(Model):
    id: str  # e.g. "CSP-COST-2026-12-04-900P"
    strategy: CandidateStrategy
    ticker: str
    sector: str
    spot: PositiveFloat
    expiry: date
    dte: int = Field(ge=0)
    strike: PositiveFloat
    kind: OptionKind
    bid: float = Field(ge=0)
    ask: float = Field(ge=0)
    mid: float = Field(ge=0)
    spread_pct: float = Field(ge=0)
    open_interest: int = Field(ge=0)
    iv: float = Field(ge=0)
    iv_rank: float | None = None
    iv_rank_source: IVRankSource
    delta: float
    gamma: float
    theta: float
    vega: float
    prob_otm: float = Field(ge=0, le=1)
    collateral: float | None = None  # CSP cash-secured amount
    margin_req: float | None = None  # Reg T naked put requirement
    annualized_return: float | None = None  # on collateral (CSP)
    return_on_margin: float | None = None
    extrinsic_per_year_pct: float | None = None  # LEAPS
    intrinsic: float | None = None
    extrinsic: float | None = None
    breakeven: float
    earnings_before_expiry: bool
    flags: list[str] = Field(default_factory=list)


class PMCCCandidate(Model):
    id: str
    ticker: str
    leaps: OptionCandidate
    short_call: OptionCandidate
    net_debit: float = Field(ge=0)  # LEAPS mid - short call mid
    net_delta: float
    safety_margin: float  # short strike - (LEAPS strike + LEAPS debit); must be >= 0
    short_call_annualized_yield_on_debit: float


class QualityCheck(Model):
    """Deterministic 'good to own' gate for one underlying (section 3.7)."""

    ticker: str
    name: str | None = None
    sector: str = "Unknown"
    curated: bool
    passed: bool
    score: float = Field(ge=0, le=1)
    components: dict[str, float]  # stability, trend, curated (each 0–1)
    metrics: dict[str, float | None]  # price, avg_volume, hv30, atm_iv, drawdown_90d
    reasons: list[str] = Field(default_factory=list)  # failed gates, plain English
    why_good_to_own: str | None = None
    tags: list[str] = Field(default_factory=list)


class RankedCandidate(Model):
    candidate: OptionCandidate
    option_quality: float = Field(ge=0, le=1)
    social_score: float = Field(ge=0, le=100)
    quality_score: float = Field(default=0.5, ge=0, le=1)
    final_score: float = Field(ge=0, le=1)
    rank: int = Field(ge=1)
    pmcc: PMCCCandidate | None = None  # populated when a LEAPS has a matched short call


# ------------------------------------------------------------------------------ sizing
class SizedPosition(Model):
    candidate_id: str
    strategy: CandidateStrategy
    ticker: str
    sector: str
    contracts: int = Field(ge=1)
    strike: float
    expiry: date
    mid: float
    delta: float
    notional: float = Field(ge=0)  # strike * 100 * contracts (short puts) or LEAPS cost
    capital_used: float = Field(ge=0)  # collateral (cash) / margin (margin acct) / debit (LEAPS)
    margin_used: float = Field(ge=0)
    realistic_loss: float = Field(ge=0)
    dollar_delta: float
    premium: float  # +income for shorts, -debit for longs
    pmcc_short_call_id: str | None = None


class PortfolioTotals(Model):
    short_put_notional: float = Field(ge=0)
    capital_used: float = Field(ge=0)
    margin_used: float = Field(ge=0)
    leaps_cost: float = Field(ge=0)
    realistic_loss: float = Field(ge=0)
    dollar_delta: float
    premium_income: float
    cash_reserve: float = Field(ge=0)
    buying_power_used_pct: float = Field(ge=0)


class SizedPortfolio(Model):
    positions: list[SizedPosition]
    totals: PortfolioTotals
    skipped: list[str] = Field(default_factory=list)  # candidate ids that could not be sized + why
    attempt: int = Field(default=1, ge=1)


# -------------------------------------------------------------------------------- risk
class ConstraintCheck(Model):
    name: str
    limit: float
    value: float
    passed: bool
    detail: str


class StressResult(Model):
    shock: float  # e.g. -0.10
    iv_shock: float
    pnl: float
    pnl_pct_account: float


class RiskReport(Model):
    checks: list[ConstraintCheck]
    stress: list[StressResult]
    warnings: list[str]
    passed: bool
    worst_case_loss: float  # most negative stress pnl
    max_loss_at_minus_30: float  # realistic loss total


# ------------------------------------------------------------------------------ social
class SocialPost(Model):
    """One public post from any post source, normalised so filters/extraction are source-agnostic.

    Reddit: ``subreddit`` is the sub, ``author_karma`` is link+comment karma, ``score`` is upvotes.
    X: ``subreddit`` is None (or the matched query label), ``author_karma`` is the follower count,
    ``score`` is likes + reposts, ``title`` is empty and the text is in ``body``.
    ``is_stock_sub`` means "stock-talk context" (a stock subreddit, a cashtag, a stock query).
    """

    id: str
    source: PostSourceName
    subreddit: str | None
    author_id: str | None
    author_karma: int | None = None
    author_age_days: int | None = None
    created_at: datetime
    score: int = 0
    title: str
    body: str = ""
    url: str | None = None
    is_stock_sub: bool = False


class DailyCount(Model):
    day: date
    count: int = Field(ge=0)


class SeriesPoint(Model):
    """One observation of a price or index series (Phase 11: FRED, CSV trackers, search interest).

    Unlike :class:`DailyCount` the value is a float: producer-price indexes and contract prices
    are not counts. Series are monthly, weekly or daily; the signals only need the ordering.
    """

    day: date
    value: float


class NewsItem(Model):
    id: str
    title: str
    published_at: datetime
    source: str
    url: str | None = None
    query: str
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)  # provider score (Phase 12)


class ExtractedEntity(Model):
    name: str
    type: EntityType
    sentiment: float = Field(ge=-1, le=1)
    is_purchase_intent: bool
    is_stock_talk: bool


class PostExtraction(Model):
    post_id: str
    entities: list[ExtractedEntity]


class ExtractionBatch(Model):
    """Structured-output schema for one extraction call (~20 posts)."""

    results: list[PostExtraction]


class TickerResolution(Model):
    entity: str
    company_name: str | None
    ticker: str | None
    investable: bool
    method: Literal["brand_map", "fuzzy_sec", "llm_validated", "private", "unresolved"]
    confidence: float = Field(ge=0, le=1)
    materiality: Materiality | None = None
    sector: str | None = None


class EvidenceItem(Model):
    post_id: str
    source: PostSourceName
    subreddit: str | None
    score: int
    date: date
    excerpt: str = Field(max_length=200)
    url: str | None = None


class TrendSignal(Model):
    entity: str
    entity_type: str
    ticker: str | None
    investable: bool
    score: float = Field(ge=0, le=100)
    components: dict[str, float]
    evidence: list[EvidenceItem]
    as_of: datetime
    flags: list[str] = Field(default_factory=list)


# ------------------------------------------------------------- bottleneck (Phase 11, 4A)
class FilingSnippet(Model):
    """One ≤ 400-character window of a filing, headline, transcript or post, ready to classify.

    Snippets are data, never instructions: the classifier wraps ``text`` in delimiters and nothing
    in it can add a ticker or influence a tool call (section 4A.5).
    """

    id: str  # content hash; the classification cache key
    source: BottleneckSourceName
    text: str = Field(min_length=1, max_length=400)
    date: date
    url: str | None = None
    filer_ticker: str | None = None  # SEC-validated; gives `side` through the theme map
    form: str | None = None  # 10-K | 10-Q | 8-K for EDGAR; None elsewhere
    theme_id: str | None = None  # the theme whose layer keywords found the snippet
    layer_hint: str | None = None  # the layer whose keywords matched (the query, not the label)

    @field_validator("filer_ticker", mode="before")
    @classmethod
    def _upper_ticker(cls, v: object) -> str | None:
        if v is None:
            return None
        t = str(v).strip().upper()
        return t or None


class ConstraintLabel(Model):
    """The only LLM output in the bottleneck engine (section 4A.6): a label per snippet.

    Any ticker a label mentions is validated against the SEC list or the label is discarded.
    """

    snippet_id: str
    layer_id: str | None
    side: ConstraintSide
    direction: ConstraintDirection
    kind: ConstraintKind
    confidence: float = Field(ge=0.0, le=1.0)
    tickers: list[str] = Field(default_factory=list)  # SEC-validated mentions, upper-case


class ConstraintLabelBatch(Model):
    labels: list[ConstraintLabel]


class FalsifierStatus(Model):
    """One falsifier of a layer's thesis and whether it has tripped (section 4A.9)."""

    signal: str
    op: FalsifierOperator
    value: float
    snapshots: int = Field(ge=1)  # consecutive daily snapshots the predicate must hold
    tripped: bool = False
    since: date | None = None  # first snapshot date of the current run of hits
    observed: float | None = None  # the signal's latest value, for the board

    @property
    def state(self) -> str:
        if not self.tripped:
            return "holding"
        return f"tripped since {self.since.isoformat()}" if self.since else "tripped"


class BottleneckEvidence(Model):
    """One item of the evidence pack (section 4A.10): a filing excerpt, a price point or a
    supply-response headline. Links and short excerpts only, never full text."""

    kind: BottleneckEvidenceKind
    source: BottleneckSourceName
    date: date
    excerpt: str = Field(max_length=200)
    url: str | None = None
    filer_ticker: str | None = None
    label: str | None = None  # e.g. "tightening · lead_time" or the series label
    series_id: str | None = None
    value: float | None = None  # the price point for a `price` item


class BottleneckSignal(Model):
    """A layer row (``ticker is None``) or a company row of the bottleneck board (section 7)."""

    theme_id: str
    layer_id: str
    layer_name: str
    ticker: str | None  # None for the layer row itself
    role: SupplyRole | None
    curated: bool  # on the good-to-own list?
    investable: bool  # curated and role == supplier
    layer_score: float = Field(ge=0, le=100)
    score: float = Field(ge=0, le=100)  # company score (== layer_score for the layer row)
    components: dict[str, float]  # every signal in 4A.7 plus exposure and priced_in
    thesis: str
    falsifiers: list[FalsifierStatus] = Field(default_factory=list)
    catalyst_days: int | None = None
    flags: list[str] = Field(default_factory=list)  # bottleneck_support, bottleneck_easing, ...
    evidence: list[BottleneckEvidence] = Field(default_factory=list)
    as_of: datetime

    @property
    def thesis_weakening(self) -> bool:
        return any(f.tripped for f in self.falsifiers)


# -------------------------------------------------------------------- narrative (Phase 10)
ParagraphMode = Literal["education", "screen_result", "notice"]
NO_SOURCE_SENTENCE = "I don't have a source for that in my knowledge base."
SOURCE_TAG = r"\[S(\d+)\]"  # the [Sn] citation tag the Education agent writes


class Citation(Model):
    """A retrieved knowledge-base chunk the narrative relies on (PRD 5.6); ``tag`` is its [Sn]."""

    chunk_id: str
    doc_id: str
    title: str
    url: str
    quote: str
    kind: str = "concepts"  # concepts | rules | filings | evidence
    tag: str = ""  # "S1"… once numbered for a narrative
    as_of: date | None = None  # the source document's date (freshness check)


class Paragraph(Model):
    """One narrative paragraph tagged by the LLM (section 13.1).

    ``education`` explains a concept and must carry ≥ 1 citation tag; ``screen_result`` reports
    computed numbers only; ``notice`` holds the disclaimer and data caveats (neither a definitional
    claim nor run data).
    """

    mode: ParagraphMode
    text: str
    citations: list[str] = Field(default_factory=list)  # tags such as "S1"

    @field_validator("citations", mode="before")
    @classmethod
    def _normalise_tags(cls, v: object) -> list[str]:
        out: list[str] = []
        for tag in v if isinstance(v, list | tuple | set) else []:
            t = str(tag).strip().strip("[]").upper()
            if t.startswith("S") and t[1:].isdigit() and t not in out:
                out.append(t)
        return out


class Narrative(Model):
    """Structured output of the explainer and the concept answerer."""

    paragraphs: list[Paragraph] = Field(default_factory=list)

    @property
    def markdown(self) -> str:
        return "\n\n".join(p.text.strip() for p in self.paragraphs if p.text.strip())

    @property
    def tags(self) -> list[str]:
        """Every citation tag used, in first-use order (declared or inline ``[Sn]``)."""
        import re

        seen: list[str] = []
        for p in self.paragraphs:
            for t in [*p.citations, *(f"S{n}" for n in re.findall(SOURCE_TAG, p.text))]:
                if t not in seen:
                    seen.append(t)
        return seen

    @classmethod
    def plain(cls, text: str, mode: ParagraphMode = "screen_result") -> Narrative:
        return cls(
            paragraphs=[Paragraph(mode=mode, text=t) for t in text.split("\n\n") if t.strip()]
        )


# ------------------------------------------------------------------------------ report
class VerificationResult(Model):
    passed: bool
    numbers_checked: int
    ungrounded_numbers: list[str]
    banned_phrases_found: list[str]
    disclaimer_present: bool
    cited_candidate_ids: list[str]
    attempts: int
    # Phase 10 step 10.3: [Sn] tags must point at retrieved sources
    citations_checked: int = 0
    unknown_citations: list[str] = Field(default_factory=list)


# -------------------------------------------------------------------- compliance (13.1)
Severity = Literal["block", "warn"]
TextKind = Literal["report", "answer"]


class SuitabilityFacts(Model):
    """Deterministic facts the Risk agent computes so Compliance never recomputes anything."""

    account_type: AccountType
    risk_profile: RiskProfile
    buying_power: float
    account_value: float
    strategies_requested: list[str]
    strategies_present: list[str]  # from the sized positions: csp / leaps / pmcc
    margin_used: float
    realistic_loss_pct: float  # portfolio realistic loss / account value
    max_position_loss_pct: float  # worst single position realistic loss / account value
    loss_limit_pct: float  # profile limit per position (section 3.2)
    position_count: int
    max_positions: int
    earnings_flagged: list[str] = Field(default_factory=list)  # candidate ids
    hv_proxy_ids: list[str] = Field(default_factory=list)
    pmcc_present: bool = False
    leaps_requested: bool = False


class ComplianceCheck(Model):
    name: str
    passed: bool
    severity: Severity = "block"
    detail: str = ""
    locations: list[str] = Field(default_factory=list)  # paragraph indexes / tags / ids


class ComplianceReport(Model):
    """Outcome of the Compliance agent for one text (13.1); appended to the run's audit log."""

    passed: bool
    checks: list[ComplianceCheck]
    retry_feedback: str = ""
    audit_id: str
    text_kind: TextKind = "report"
    attempts: int = 1
    verification: VerificationResult

    @property
    def failed_checks(self) -> list[ComplianceCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "block"]

    @property
    def warnings(self) -> list[ComplianceCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "warn"]


# -------------------------------------------------------------- conversation (Phase 10, 10.5)
# ------------------------------------------------------------------- goals (Phase 12, 12.2)
class Goal(Model):
    """What the user wants the account to do. Money in dollars, rates as fractions, time in years.
    ``start_balance`` defaults to the profile's account value when the agent builds the goal."""

    kind: GoalKind
    start_balance: float = Field(ge=0)
    monthly_contribution: float = Field(default=0.0, ge=0)
    target_monthly_income: float | None = Field(default=None, gt=0)  # income
    target_balance: float | None = Field(default=None, gt=0)  # growth / contribution
    horizon_years: float | None = Field(default=None, gt=0)
    # fire
    variant: FireVariant | None = None
    annual_expenses: float | None = Field(default=None, gt=0)
    minimum_expenses: float | None = Field(default=None, gt=0)  # lean
    fat_expenses: float | None = Field(default=None, gt=0)  # fat (else fat_multiple x expenses)
    part_time_income: float = Field(default=0.0, ge=0)  # barista, per year
    withdrawal_rate: float | None = Field(default=None, gt=0, lt=0.5)
    current_age: float | None = Field(default=None, gt=0)
    target_age: float | None = Field(default=None, gt=0)

    @field_validator("variant", mode="before")
    @classmethod
    def _lower_variant(cls, v: object) -> object:
        return str(v).strip().lower() if isinstance(v, str) else v


class GoalParse(Model):
    """Structured output of ``prompts/parse_goal.md``: every field optional so the model can say
    'not stated'; ``goal_intake_node`` fills ``start_balance`` from the profile when absent."""

    kind: GoalKind | None = None
    target_monthly_income: float | None = Field(default=None, gt=0)
    target_balance: float | None = Field(default=None, gt=0)
    horizon_years: float | None = Field(default=None, gt=0)
    monthly_contribution: float | None = Field(default=None, ge=0)
    start_balance: float | None = Field(default=None, ge=0)
    annual_expenses: float | None = Field(default=None, gt=0)
    minimum_expenses: float | None = Field(default=None, gt=0)
    fat_expenses: float | None = Field(default=None, gt=0)
    part_time_income: float | None = Field(default=None, ge=0)
    withdrawal_rate: float | None = Field(default=None, gt=0, lt=0.5)
    variant: FireVariant | None = None
    current_age: float | None = Field(default=None, gt=0)
    target_age: float | None = Field(default=None, gt=0)
    needs_clarification: list[str] = Field(default_factory=list)

    @field_validator("variant", mode="before")
    @classmethod
    def _lower_variant(cls, v: object) -> object:
        return str(v).strip().lower() if isinstance(v, str) else v


class YieldEstimate(Model):
    """What the sized portfolio earns per year, as the Goal Planning agent sees it."""

    gross_yield: float  # capital-weighted annualised return incl. the cash reserve at cash_rate
    stress_adjusted_yield: float  # gross minus assignment_frequency x realistic loss / capital
    cash_rate: float
    capital_used: float
    cash_reserve: float
    realistic_loss: float
    assignment_frequency: float
    detail: list[str] = Field(default_factory=list)

    @property
    def total_capital(self) -> float:
        return self.capital_used + self.cash_reserve


class GoalLever(Model):
    name: LeverName
    value: float | None  # dollars, years, or None when no profile cap admits the goal
    detail: str


class FeasibilityVerdict(Model):
    status: FeasibilityStatus
    required_return: float | None  # None when the goal needs no return (already met)
    available_return: float  # the stress-adjusted yield the verdict was judged against
    profile_cap: float
    gap: float  # required - available in return points (negative = headroom)
    levers: list[GoalLever] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ProjectionPoint(Model):
    year: float
    balance: float


class ProjectionPath(Model):
    label: Literal["stress", "base", "best", "assumed"]
    annual_return: float
    points: list[ProjectionPoint]
    note: str = ""


class FirePlan(Model):
    variant: FireVariant
    expense_target: float
    withdrawal_rate: float
    fire_number: float
    assumed_return: float  # the diversified-portfolio assumption the projection uses
    years_to_fi: float | None  # None: not reached within the horizon cap at the assumed return
    coast_balance: float | None  # balance needed today to coast to the FIRE number by target age
    savings_rate: float | None
    income_coverage: float | None  # share of the expense target the stress-adjusted yield covers
    buying_power_for_full_coverage: float | None
    targets: dict[str, float] = Field(default_factory=dict)  # lean/regular/fat FIRE numbers
    notes: list[str] = Field(default_factory=list)


class GoalPlan(Model):
    goal: Goal
    yield_estimate: YieldEstimate
    feasibility: FeasibilityVerdict
    projection: list[ProjectionPath]
    fire: FirePlan | None = None
    assumptions: list[str] = Field(default_factory=list)


# -------------------------------------------------------------------- news (Phase 12, 12.3)
class ClassifiedNews(Model):
    item: NewsItem
    ticker: str
    category: NewsCategory = "other"
    relevance: NewsRelevance = "low"
    summary: str = ""
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)  # provider score, pass-through
    weight: float = Field(ge=0.0, le=1.0)  # recency weight
    stale: bool = False


class NewsClassification(Model):
    """One headline's label from ``prompts/classify_news.md`` (or the rule-based stand-in)."""

    id: str
    category: NewsCategory = "other"
    relevance: NewsRelevance = "low"
    summary: str = Field(default="", max_length=300)


class NewsClassificationBatch(Model):
    items: list[NewsClassification] = Field(default_factory=list)


class NewsFlag(Model):
    candidate_id: str
    ticker: str
    flag: Literal["earnings_within_dte", "ex_dividend_before_expiry", "ex_dividend_capture_window"]
    event_date: date
    detail: str


class NewsBrief(Model):
    ticker: str
    items: list[ClassifiedNews]
    flags: list[NewsFlag] = Field(default_factory=list)
    as_of: datetime


# ---------------------------------------------------------------- holdings (Phase 12, 12.6)
class Holding(Model):
    ticker: str = Field(min_length=1, max_length=10)
    shares: float = Field(gt=0)
    cost_basis: float | None = Field(default=None, ge=0)  # per share
    account: AccountType | Literal["ira"] | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def _upper(cls, v: object) -> str:
        return str(v).strip().upper()


class TaxFacts(Model):
    """Illustrative mechanics computed by ``core/tax.py`` for a tax reply (Phase 12, 12.6): the
    screened put's assignment basis, the LEAPS long-term threshold, the wash-sale window around
    today, and the Section 1256 status of the run's tickers. Never a liability or a rate."""

    as_of: date
    candidate_id: str | None = None
    ticker: str | None = None
    strike: float | None = None
    premium: float | None = None
    assigned_basis_per_share: float | None = None
    assigned_total_basis: float | None = None
    cash_paid_at_assignment: float | None = None
    premium_if_expired: float | None = None
    leaps_candidate_id: str | None = None
    leaps_long_term_from: date | None = None
    leaps_days_to_long_term: int | None = None
    wash_sale_window_start: date | None = None
    wash_sale_window_end: date | None = None
    wash_sale_window_days: int | None = None
    section_1256: dict[str, bool | None] = Field(default_factory=dict)
    account_type: str | None = None
    notes: list[str] = Field(default_factory=list)


class HoldingsParse(Model):
    """Structured output of ``prompts/parse_holdings.md``: the positions a message lists."""

    holdings: list[Holding] = Field(default_factory=list)
    needs_clarification: list[str] = Field(default_factory=list)


class HoldingValue(Model):
    ticker: str
    shares: float
    price: float
    market_value: float
    cost: float | None
    unrealised_pnl: float | None
    weight: float  # share of total market value
    sector: str
    expense_ratio: float | None  # fraction per year, ETFs only
    beta: float | None
    covered_call_lots: int


class PostAssignment(Model):
    candidate_id: str
    ticker: str
    strike: float
    shares_added: int
    cash_used: float
    weight_before: float
    weight_after: float


class HoldingsAnalysis(Model):
    positions: list[HoldingValue]
    total_value: float
    by_sector: dict[str, float]  # weights
    hhi: float
    effective_positions: float
    diversification_score: float  # 0-100 = 100 x (1 - HHI)
    weighted_expense_ratio: float | None
    beta_weighted_exposure: float | None  # sum of weight x beta over positions with a beta
    largest_position: str | None
    largest_sector: str | None
    covered_call_eligible: list[str]
    post_assignment: list[PostAssignment] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


Intent = Literal[
    "new_screen",
    "refine_profile",
    "concept",
    "why",
    "what_if",
    "off_topic",
    "goal",
    "holdings",
    "news",
    "tax",
]
INTENTS: tuple[str, ...] = (
    "new_screen",
    "refine_profile",
    "concept",
    "why",
    "what_if",
    "off_topic",
    "goal",  # Phase 12
    "holdings",
    "news",
    "tax",
)
OFF_TOPIC_REPLY = (
    "I can help with options education and with screening cash-secured puts, LEAPS and PMCCs on "
    "good-to-own stocks. Ask about a concept, about why a stock or candidate was treated the way "
    "it was, or describe your buying power and account to run a screen."
)


class RouteDecision(Model):
    """Structured output of the Orchestrator's router (prompt ``route_message``)."""

    intent: Intent
    question: str | None = None  # the question to answer for concept / why
    profile_changes: dict[str, Any] = Field(default_factory=dict)  # for refine_profile / what_if
    reason: str = ""


class ChatTurn(Model):
    """One message of a conversation, stored on the thread (13.1: every assistant turn carries
    the ComplianceReport its text passed)."""

    role: Literal["user", "assistant"]
    text: str
    intent: Intent | None = None
    compliance: ComplianceReport | None = None
    citations: list[Citation] = Field(default_factory=list)
    thread_id: str
    new_thread_id: str | None = None  # a what-if / new screen started on another thread
    ts: datetime = Field(default_factory=utcnow)


class TokenUsage(Model):
    model: str
    task: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cached: bool = False


class RunMetadata(Model):
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    data_mode: str
    llm_mode: str
    models: dict[str, str]
    prompt_versions: dict[str, str]
    config_hash: str
    data_source_status: dict[str, str]
    token_usage: list[TokenUsage] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    node_latency_ms: dict[str, float] = Field(default_factory=dict)
    nodes_visited: list[str] = Field(default_factory=list)
    # Phase 10: per-specialist trace (agent_latency_ms sums an agent's retries)
    agent_latency_ms: dict[str, float] = Field(default_factory=dict)
    agents_visited: list[str] = Field(default_factory=list)


class ScreeningReport(Model):
    run_id: str
    as_of: datetime
    profile: UserProfile
    regime: MarketRegime
    allocation: AllocationPlan
    trends: list[TrendSignal]
    universe: list[str]
    quality: list[QualityCheck] = Field(default_factory=list)  # passed + excluded, in run order
    csp_candidates: list[OptionCandidate]
    leaps_candidates: list[OptionCandidate]
    pmcc_candidates: list[PMCCCandidate]
    ranked: list[RankedCandidate]
    portfolio: SizedPortfolio
    risk: RiskReport
    narrative: Narrative  # Phase 10: tagged paragraphs with [Sn] citations
    narrative_markdown: str  # the same text joined, for the API/UI and the Markdown report
    citations: list[Citation] = Field(default_factory=list)  # numbered sources the text cites
    verification: VerificationResult
    compliance: ComplianceReport | None = None  # Phase 10 step 10.4: the eight checks + audit id
    audit_log: list[ComplianceReport] = Field(default_factory=list)  # every evaluation this run
    goal_plan: GoalPlan | None = None  # Phase 12: present when the run carried a goal
    news_briefs: list[NewsBrief] = Field(default_factory=list)  # Phase 12: News Desk
    news_flags: list[NewsFlag] = Field(default_factory=list)
    bottlenecks: list[BottleneckSignal] = Field(default_factory=list)  # Phase 11: the board
    errors: list[str]
    metadata: RunMetadata
    disclaimer: str
