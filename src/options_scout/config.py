"""Typed settings loaded from config/*.yaml with env-var overrides.

Every threshold in the system lives here (rule 7 of PRD.md). Nothing numeric should be
hard-coded elsewhere.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from options_scout.bottleneck.themes import ThemeMap, load_theme_map, sec_ticker_validator

RiskProfileName = Literal["conservative", "balanced", "aggressive"]
DataMode = Literal["fixture", "live"]
LLMProviderName = Literal["anthropic", "openrouter"]
# "live" uses settings.llm.provider; "anthropic" / "openrouter" force that live provider.
LLMMode = Literal["fixture", "live", "anthropic", "openrouter", "none"]


def repo_root() -> Path:
    """Return the repository root (directory holding config/)."""
    env = os.environ.get("OPTIONS_SCOUT_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "settings.yaml").exists():
            return parent
    return Path.cwd()


def load_env(path: Path | None = None) -> bool:
    """Load ``<repo_root>/.env`` into ``os.environ`` without overriding existing variables.

    Entry points (CLI, API, UI, evals, jobs) call this once at startup so keys written to
    ``.env`` (LLM provider keys, ``LANGSMITH_API_KEY`` ...) reach the process. A value already
    exported in the shell always wins. Set ``OPTIONS_SCOUT_DOTENV=0`` to skip the file entirely
    (the test suite does this so a developer's real keys never leak into tests). Returns True
    when a file was found and loaded.
    """
    from dotenv import load_dotenv

    if os.environ.get("OPTIONS_SCOUT_DOTENV", "1") == "0":
        return False
    target = path if path is not None else repo_root() / ".env"
    if not target.is_file():
        return False
    return bool(load_dotenv(target, override=False))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- settings.yaml
class Paths(_Strict):
    fixtures_dir: Path
    cache_db: Path
    checkpoint_db: Path
    iv_snapshot_db: Path
    prompts_dir: Path
    brand_map: Path
    llm_cache_dir: Path

    def resolved(self, root: Path) -> Paths:
        return Paths(**{k: (root / v) for k, v in self.model_dump().items()})


class CacheTTL(_Strict):
    option_chain: int
    spot: int
    earnings: int
    dividends: int
    history: int
    social_posts: int
    pageviews: int
    news: int
    sec_tickers: int


class ModelPrice(_Strict):
    input: float
    output: float


class LLMProviderSettings(_Strict):
    """Model names and list prices for one provider (prices only feed cost accounting)."""

    extraction_model: str
    explanation_model: str
    judge_model: str
    pricing: dict[str, ModelPrice]
    base_url: str | None = None  # OpenAI-compatible gateways (OpenRouter); unused by Anthropic


class LLMSettings(_Strict):
    provider: LLMProviderName  # live provider used when llm_mode is "live" (and for model labels)
    extraction_batch_size: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    providers: dict[LLMProviderName, LLMProviderSettings]

    @model_validator(mode="after")
    def _provider_configured(self) -> LLMSettings:
        if self.provider not in self.providers:
            raise ValueError(f"llm.provider={self.provider!r} has no entry under llm.providers")
        return self

    @property
    def active(self) -> LLMProviderSettings:
        return self.providers[self.provider]


class OptionQualityWeights(_Strict):
    annualized_return: float
    prob_otm: float
    liquidity: float
    iv_rank_fit: float

    @model_validator(mode="after")
    def _sums_to_one(self) -> OptionQualityWeights:
        total = self.annualized_return + self.prob_otm + self.liquidity + self.iv_rank_fit
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"option_quality_weights must sum to 1.0, got {total}")
        return self


# Section 3.7: the two Market Intelligence signals together never carry more than this share.
MAX_SIGNAL_WEIGHT = 0.15


class RankingWeights(_Strict):
    """final = option_quality·w1 + stock_quality·w2 + social/100·w3 + bottleneck/100·w4.

    The four weights sum to 1 and ``social + bottleneck`` is capped at :data:`MAX_SIGNAL_WEIGHT`
    (PRD section 3.7 / 4A: the signals re-order, they never dominate).
    """

    option_quality: float = Field(ge=0.0, le=1.0)
    stock_quality: float = Field(ge=0.0, le=1.0)
    social: float = Field(ge=0.0, le=1.0)
    bottleneck: float = Field(default=0.05, ge=0.0, le=1.0)  # Phase 11, section 4A

    @model_validator(mode="after")
    def _sums_to_one_and_signals_capped(self) -> RankingWeights:
        total = self.option_quality + self.stock_quality + self.social + self.bottleneck
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ranking.weights must sum to 1.0, got {total}")
        signals = self.social + self.bottleneck
        if signals > MAX_SIGNAL_WEIGHT + 1e-9:
            raise ValueError(
                f"ranking.weights: social + bottleneck = {signals:g} exceeds the "
                f"{MAX_SIGNAL_WEIGHT:g} cap on Market Intelligence signals (PRD section 3.7)"
            )
        return self


class RankingSettings(_Strict):
    weights: RankingWeights
    option_quality_weights: OptionQualityWeights
    # Keep at most this many ranked candidates per (ticker, strategy); 0 = no cap. Without it a
    # dense ETF chain (SPY: $1 strikes × several expiries) fills the whole top of the list with
    # near-identical contracts.
    max_per_ticker: int = Field(default=2, ge=0)


MarketProviderName = Literal["marketdata", "tradier"]


class MarketDataAppSettings(_Strict):
    api_key_env: str = "MARKETDATA_TOKEN"  # same variable the official SDKs read
    # A chain costs one credit per contract; keep the N strikes nearest the money (0 = all).
    strike_limit: int = Field(default=60, ge=0)


class TradierSettings(_Strict):
    sandbox: bool = True  # sandbox.tradier.com (free developer key, 15-min delayed) vs production
    api_key_env: str = "TRADIER_API_KEY"


class MarketDataSettings(_Strict):
    """Live-mode market data provider. The UI/API may override provider + key per run."""

    provider: MarketProviderName = "marketdata"
    marketdata: MarketDataAppSettings = MarketDataAppSettings()
    tradier: TradierSettings = TradierSettings()


class TrendSettings(_Strict):
    snapshot_max_age_hours: int
    top_n_investable: int
    evidence_posts_per_entity: int
    retention_hours: int


class AgentSettings(_Strict):
    max_sizing_retries: int
    max_explainer_retries: int
    verifier_number_tolerance: float


class RiskSettings(_Strict):
    stress_shocks: list[float]
    stress_iv_shock: float


class Settings(_Strict):
    data_mode: DataMode
    llm_mode: LLMMode
    paths: Paths
    cache_ttl_seconds: CacheTTL
    llm: LLMSettings
    market_data: MarketDataSettings = MarketDataSettings()
    ranking: RankingSettings
    trends: TrendSettings
    agent: AgentSettings
    risk: RiskSettings
    disclaimer: str


# ---------------------------------------------------------------------- risk_profiles.yaml
class AllocationSplit(_Strict):
    csp: float = Field(ge=0, le=1)
    leaps: float = Field(ge=0, le=1)
    cash: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _sums_to_one(self) -> AllocationSplit:
        if abs(self.csp + self.leaps + self.cash - 1.0) > 1e-9:
            raise ValueError("allocation split must sum to 1.0")
        return self


class RegimeTilt(_Strict):
    high_iv_percentile: float
    low_iv_percentile: float
    shift: float = Field(ge=0, le=0.5)


class Constraints(_Strict):
    max_short_put_notional_x: float
    max_margin_usage: float
    max_loss_per_position: float
    max_exposure_per_ticker: float
    max_per_sector: float
    max_dollar_delta_x: float
    # Phase 12 (12.4), the seventh constraint: a ticker's share of (holdings + buying power) after
    # a cash-secured put on it is assigned; applied only when the user entered holdings.
    max_ticker_concentration_after_assignment: float = Field(default=1.0, gt=0.0, le=1.0)


class RiskProfiles(_Strict):
    allocation: dict[RiskProfileName, AllocationSplit]
    regime_tilt: RegimeTilt
    constraints: dict[RiskProfileName, Constraints]
    realistic_loss_drop: float = Field(gt=0, lt=1)


# -------------------------------------------------------------------- screener_rules.yaml
class CSPRules(_Strict):
    dte_min: int
    dte_max: int
    dte_fallback_min: int
    dte_fallback_max: int
    delta_min: float
    delta_max: float
    min_open_interest: int
    max_spread_pct: float
    min_bid: float
    exclude_earnings_before_expiry: bool
    min_underlying_price: float
    min_avg_volume: int
    preferred_iv_rank_min: float


class LEAPSRules(_Strict):
    dte_min: int
    dte_preferred: int
    delta_min: float
    delta_max: float
    max_extrinsic_per_year_pct: float
    min_open_interest: int
    max_spread_pct: float
    preferred_iv_rank_max: float
    roll_warning_dte: int


class PMCCRules(_Strict):
    dte_min: int
    dte_max: int
    dte_fallback_min: int
    dte_fallback_max: int
    delta_min: float
    delta_max: float


class ScreenerRules(_Strict):
    csp: CSPRules
    leaps: LEAPSRules
    pmcc: PMCCRules


# ---------------------------------------------------------------------- social_score.yaml
class ScoreWeights(_Strict):
    velocity_z: float
    acceleration_norm: float
    sentiment: float
    purchase_intent_rate: float
    cross_source_norm: float
    coverage_gap: float
    materiality: float
    novelty_penalty: float
    stock_hype_penalty: float


class ScoreNormalization(_Strict):
    velocity_z_clip: float
    acceleration_clip: float
    cross_source_z_threshold: float  # cross_source_norm divides by the number of enabled sources
    novelty_hot_weeks: int
    novelty_hot_z: float


class SocialFilters(_Strict):
    min_account_age_days: int
    min_author_karma: int
    max_author_share: float
    dedupe_jaccard: float
    stock_talk_flag_share: float


class SocialWindows(_Strict):
    recent_days: int
    baseline_weeks: int


class SocialScoreConfig(_Strict):
    weights: ScoreWeights
    bias: float
    normalization: ScoreNormalization
    materiality: dict[Literal["high", "medium", "low"], float]
    filters: SocialFilters
    windows: SocialWindows


# ------------------------------------------------------------------- quality_universe.yaml
class UniverseLimits(_Strict):
    max_tickers: int = Field(gt=0)


class QualityGates(_Strict):
    require_curated: bool
    min_price: float = Field(gt=0)
    min_avg_volume: float = Field(ge=0)
    max_hv30: float = Field(gt=0)
    max_atm_iv: float = Field(gt=0)
    max_drawdown_90d: float = Field(gt=0, lt=1)
    min_history_days: int = Field(gt=1)


class QualityScoreWeights(_Strict):
    stability: float = Field(ge=0, le=1)
    trend: float = Field(ge=0, le=1)
    curated: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _sums_to_one(self) -> QualityScoreWeights:
        total = self.stability + self.trend + self.curated
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"quality score weights must sum to 1.0, got {total}")
        return self


class QualityScore(_Strict):
    weights: QualityScoreWeights


class CuratedTicker(_Strict):
    ticker: str = Field(min_length=1, max_length=10)
    name: str
    sector: str
    tags: list[str] = Field(default_factory=list)
    why: str

    @field_validator("ticker", mode="before")
    @classmethod
    def _upper(cls, v: object) -> str:
        return str(v).strip().upper()


class QualityUniverse(_Strict):
    universe: UniverseLimits
    gates: QualityGates
    score: QualityScore
    tickers: list[CuratedTicker]

    @model_validator(mode="after")
    def _unique(self) -> QualityUniverse:
        seen = [t.ticker for t in self.tickers]
        dupes = sorted({t for t in seen if seen.count(t) > 1})
        if dupes:
            raise ValueError(f"duplicate curated tickers: {dupes}")
        return self

    def get(self, ticker: str) -> CuratedTicker | None:
        t = ticker.upper()
        return next((c for c in self.tickers if c.ticker == t), None)

    @property
    def symbols(self) -> list[str]:
        return [t.ticker for t in self.tickers]


# ------------------------------------------------------------------------ subreddits.yaml
class SubredditFetch(_Strict):
    posts_per_subreddit: int
    listing: Literal["new", "hot", "top"]
    comments: bool


class Subreddits(_Strict):
    consumer: list[str]
    stock: list[str]
    fetch: SubredditFetch
    # Phase 11 (section 4A.5): industry and enthusiast subs the bottleneck engine reads for
    # everyday observation (prices paid, availability). They never feed the consumer signal.
    industry: list[str] = Field(default_factory=list)


# -------------------------------------------------------------------- social_sources.yaml
PostSourceName = Literal["reddit", "x"]
AttentionSourceName = Literal["wikipedia", "google_trends"]
SOCIAL_SOURCE_NAMES: tuple[str, ...] = ("reddit", "x", "wikipedia", "google_trends", "news")


RedditProvider = Literal["arctic_shift", "praw"]


class ArcticShiftConfig(_Strict):
    """Arctic Shift (https://arctic-shift.photon-reddit.com): free Reddit archive with a public
    search API. No credentials; posts are available within minutes but scores settle after ~36h."""

    base_url: str = "https://arctic-shift.photon-reddit.com"
    page_size: int = Field(default=100, ge=1, le=100)
    max_pages_per_subreddit: int = Field(default=30, ge=1)
    min_request_interval_seconds: float = Field(default=0.25, ge=0.0)
    max_rate_limit_wait_seconds: float = Field(default=60.0, ge=0.0)
    timeout_seconds: float = Field(default=30.0, gt=0.0)


class RedditSourceConfig(_Strict):
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0)
    fixture_file: str = "reddit_posts.jsonl"
    # Live providers, tried in order; the first one that returns posts wins. Default: the Arctic
    # Shift archive first (no credentials), the official Data API via PRAW as the backup.
    providers: list[RedditProvider] = Field(default=["arctic_shift", "praw"], min_length=1)
    arctic_shift: ArcticShiftConfig = Field(default_factory=ArcticShiftConfig)

    @field_validator("providers")
    @classmethod
    def _unique_providers(cls, v: list[RedditProvider]) -> list[RedditProvider]:
        if len(set(v)) != len(v):
            raise ValueError("social_sources: reddit.providers must not repeat a provider")
        return v


class XSearchConfig(_Strict):
    endpoint: Literal["recent", "all"] = "recent"
    lang: str = "en"
    exclude_retweets: bool = True
    exclude_replies: bool = False
    max_results_per_query: int = Field(default=300, ge=10)
    min_author_followers: int = Field(default=0, ge=0)
    consumer_queries: list[str]
    stock_queries: list[str] = Field(default_factory=list)


class XSourceConfig(_Strict):
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0)
    fixture_file: str = "x_posts.jsonl"
    bearer_token_env: str = "X_BEARER_TOKEN"
    search: XSearchConfig


class WikipediaSourceConfig(_Strict):
    enabled: bool = True
    fixture_file: str = "pageviews.json"


class GoogleTrendsSourceConfig(_Strict):
    enabled: bool = True
    fixture_file: str = "google_trends.json"
    provider: Literal["pytrends"] = "pytrends"
    geo: str = "US"
    min_request_interval_seconds: float = Field(default=2.0, ge=0.0)


class NewsSourceConfig(_Strict):
    enabled: bool = True
    fixture_file: str = "news_items.jsonl"


class PostSources(_Strict):
    reddit: RedditSourceConfig
    x: XSourceConfig


class AttentionSources(_Strict):
    wikipedia: WikipediaSourceConfig
    google_trends: GoogleTrendsSourceConfig


class SocialSources(_Strict):
    """Which consumer-trend sources run. Every adapter exists; this only switches them on/off."""

    post_sources: PostSources
    attention_sources: AttentionSources
    news: NewsSourceConfig

    @property
    def enabled_post_sources(self) -> list[PostSourceName]:
        out: list[PostSourceName] = []
        if self.post_sources.reddit.enabled:
            out.append("reddit")
        if self.post_sources.x.enabled:
            out.append("x")
        return out

    @property
    def enabled_attention_sources(self) -> list[AttentionSourceName]:
        out: list[AttentionSourceName] = []
        if self.attention_sources.wikipedia.enabled:
            out.append("wikipedia")
        if self.attention_sources.google_trends.enabled:
            out.append("google_trends")
        return out

    @property
    def enabled(self) -> list[str]:
        names: list[str] = [*self.enabled_post_sources, *self.enabled_attention_sources]
        if self.news.enabled:
            names.append("news")
        return names

    @property
    def source_count(self) -> int:
        """Sources that can confirm a trend: denominator of ``cross_source_norm``."""
        return len(self.enabled)

    def post_weight(self, source: str) -> float:
        if source == "reddit":
            return self.post_sources.reddit.weight
        if source == "x":
            return self.post_sources.x.weight
        return 1.0

    @model_validator(mode="after")
    def _at_least_one_post_source(self) -> SocialSources:
        if not self.enabled_post_sources:
            raise ValueError(
                "social_sources: enable at least one post source (reddit or x); attention and "
                "news sources only confirm trends found in posts"
            )
        return self


def _apply_source_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """``OPTIONS_SCOUT_SOCIAL_SOURCES=reddit,x`` enables exactly the listed sources."""
    env_val = os.environ.get("OPTIONS_SCOUT_SOCIAL_SOURCES")
    if not env_val:
        return raw
    wanted = {s.strip().lower() for s in env_val.split(",") if s.strip()}
    unknown = wanted - set(SOCIAL_SOURCE_NAMES)
    if unknown:
        raise ValueError(
            f"OPTIONS_SCOUT_SOCIAL_SOURCES: unknown source(s) {sorted(unknown)}; "
            f"choose from {list(SOCIAL_SOURCE_NAMES)}"
        )
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in raw.items()}
    for group in ("post_sources", "attention_sources"):
        for name, sub in out.get(group, {}).items():
            out[group][name] = {**sub, "enabled": name in wanted}
    out["news"] = {**out.get("news", {}), "enabled": "news" in wanted}
    return out


# ------------------------------------------------------------------- bottleneck_score.yaml
class BottleneckWeights(_Strict):
    """Section 4A.7 layer-score weights; ``price_deceleration`` and ``supply_response_z`` are
    penalties (subtracted) and ``priced_in`` multiplies exposure as ``1 - w9·priced_in``."""

    tightness_z: float = Field(ge=0.0)
    customer_confirmation: float = Field(ge=0.0)
    price_trend: float = Field(ge=0.0)
    cross_source_norm: float = Field(ge=0.0)
    supplier_scarcity: float = Field(ge=0.0)
    capacity_lead: float = Field(ge=0.0)
    price_deceleration: float = Field(ge=0.0)  # penalty
    supply_response_z: float = Field(ge=0.0)  # penalty
    priced_in: float = Field(ge=0.0, le=1.0)  # exposure multiplier weight


class BottleneckNormalization(_Strict):
    tightness_z_clip: float = Field(gt=0.0)
    supply_response_z_clip: float = Field(gt=0.0)
    cross_source_z_threshold: float
    price_trend_days: int = Field(ge=7)
    capacity_lead_years_cap: float = Field(gt=0.0)
    recent_days: int = Field(ge=1)
    baseline_weeks: int = Field(ge=1)


class BottleneckFlags(_Strict):
    """Section 4A.8 thresholds: flags on candidates, never filters."""

    support_min: float = Field(ge=0.0, le=100.0)
    price_deceleration_max: float
    supply_response_z_max: float


PricingPowerName = Literal["high", "medium", "low"]
CapacityName = Literal["constrained", "ample"]
SupplierCountName = Literal["few", "several", "many"]


class BottleneckScoreConfig(_Strict):
    """``config/bottleneck_score.yaml``: weights, curated-field maps, flags, thesis monitor."""

    weights: BottleneckWeights
    bias: float
    normalization: BottleneckNormalization
    materiality: dict[Literal["high", "medium", "low"], float]
    pricing_power: dict[PricingPowerName, float]
    capacity: dict[CapacityName, float]
    supplier_count: dict[SupplierCountName, float]
    flags: BottleneckFlags
    easing_decay: float = Field(gt=0.0, le=1.0)
    retention_days: int = Field(ge=1)
    snapshot_max_age_hours: int = Field(ge=1)

    @model_validator(mode="after")
    def _maps_complete(self) -> BottleneckScoreConfig:
        expected: dict[str, tuple[str, ...]] = {
            "materiality": ("high", "medium", "low"),
            "pricing_power": ("high", "medium", "low"),
            "capacity": ("constrained", "ample"),
            "supplier_count": ("few", "several", "many"),
        }
        for name, keys in expected.items():
            table: dict[str, float] = getattr(self, name)
            missing = set(keys) - set(table)
            if missing:
                raise ValueError(f"bottleneck_score.{name} is missing {sorted(missing)}")
            bad = {k: v for k, v in table.items() if not 0.0 <= v <= 1.0}
            if bad:
                raise ValueError(f"bottleneck_score.{name} values must be in [0, 1]: {bad}")
        return self


# ----------------------------------------------------------------- bottleneck_sources.yaml
BottleneckSourceName = Literal[
    "edgar", "fred", "csv_series", "transcripts", "news", "reddit", "google_trends"
]
BOTTLENECK_SOURCE_NAMES: tuple[str, ...] = (
    "edgar",
    "fred",
    "csv_series",
    "transcripts",
    "news",
    "reddit",
    "google_trends",
)
BOTTLENECK_TEXT_SOURCES: tuple[str, ...] = ("edgar", "transcripts", "news", "reddit")
BOTTLENECK_SERIES_SOURCES: tuple[str, ...] = ("fred", "csv_series", "google_trends")


class EdgarSourceConfig(_Strict):
    """SEC EDGAR full-text search: free, official; descriptive User-Agent, under 10 req/s."""

    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0)
    fixture_file: str = "edgar_snippets.jsonl"
    base_url: str = "https://efts.sec.gov/LATEST/search-index"
    forms: list[str] = Field(default=["10-K", "10-Q", "8-K"], min_length=1)
    lookback_days: int = Field(default=120, ge=1)
    max_requests_per_second: float = Field(default=8.0, gt=0.0, le=10.0)
    cache_ttl_hours: int = Field(default=24, ge=1)
    contact_email_env: str = "OPTIONS_SCOUT_CONTACT_EMAIL"
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    max_documents_per_query: int = Field(default=10, ge=1)  # filings opened per keyword
    max_snippets_per_document: int = Field(default=4, ge=1)
    max_document_chars: int = Field(default=2_000_000, ge=10_000)  # a 10-K is a few MB of HTML
    max_attempts: int = Field(default=3, ge=1)  # 5xx / 429 are retried; other 4xx are final


class FredSourceConfig(_Strict):
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0)
    fixture_file: str = "fred_series.json"
    api_key_env: str = "FRED_API_KEY"
    base_url: str = "https://api.stlouisfed.org/fred/series/observations"
    lookback_days: int = Field(default=400, ge=30)
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    cache_ttl_hours: int = Field(default=24, ge=1)
    max_attempts: int = Field(default=3, ge=1)


class CsvSeriesSourceConfig(_Strict):
    """Dated CSVs the operator drops under ``directory`` (licence is theirs; never committed)."""

    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0)
    directory: Path = Path("data/bottleneck_series")


class TranscriptsSourceConfig(_Strict):
    """Earnings-call transcripts are not on EDGAR and are paid elsewhere: fixture mode only."""

    enabled: bool = False
    weight: float = Field(default=1.0, ge=0.0)
    fixture_file: str = "transcripts.jsonl"


class BottleneckNewsSourceConfig(_Strict):
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0)
    fixture_file: str = "news.jsonl"
    max_items_per_layer: int = Field(default=50, ge=1)


class BottleneckRedditSourceConfig(_Strict):
    """Industry subreddits (``industry:`` list in ``config/subreddits.yaml``, step 11.2)."""

    enabled: bool = True
    weight: float = Field(default=0.5, ge=0.0)
    fixture_file: str = "reddit_posts.jsonl"


class BottleneckTrendsSourceConfig(_Strict):
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0)
    fixture_file: str = "google_trends.json"


class BottleneckSources(_Strict):
    """Which bottleneck sources run (``config/bottleneck_sources.yaml``). Every adapter exists
    (from step 11.2); this only switches them on and off and weights them."""

    edgar: EdgarSourceConfig = Field(default_factory=EdgarSourceConfig)
    fred: FredSourceConfig = Field(default_factory=FredSourceConfig)
    csv_series: CsvSeriesSourceConfig = Field(default_factory=CsvSeriesSourceConfig)
    transcripts: TranscriptsSourceConfig = Field(default_factory=TranscriptsSourceConfig)
    news: BottleneckNewsSourceConfig = Field(default_factory=BottleneckNewsSourceConfig)
    reddit: BottleneckRedditSourceConfig = Field(default_factory=BottleneckRedditSourceConfig)
    google_trends: BottleneckTrendsSourceConfig = Field(
        default_factory=BottleneckTrendsSourceConfig
    )

    def _block(self, name: str) -> Any:
        if name not in BOTTLENECK_SOURCE_NAMES:
            raise KeyError(f"unknown bottleneck source {name!r}")
        return getattr(self, name)

    def is_enabled(self, name: str) -> bool:
        return bool(self._block(name).enabled)

    def weight(self, name: str) -> float:
        return float(self._block(name).weight)

    @property
    def enabled(self) -> list[str]:
        return [n for n in BOTTLENECK_SOURCE_NAMES if self.is_enabled(n)]

    @property
    def text_sources(self) -> list[str]:
        """Sources that yield snippets for classification (tightening / easing mentions)."""
        return [n for n in BOTTLENECK_TEXT_SOURCES if self.is_enabled(n)]

    @property
    def series_sources(self) -> list[str]:
        return [n for n in BOTTLENECK_SERIES_SOURCES if self.is_enabled(n)]

    @property
    def source_count(self) -> int:
        """Sources that can confirm a tightening: denominator of ``cross_source_norm``."""
        return len(self.enabled)

    def resolved(self, root: Path) -> BottleneckSources:
        csv = self.csv_series.model_copy(update={"directory": root / self.csv_series.directory})
        return self.model_copy(update={"csv_series": csv})

    @model_validator(mode="after")
    def _at_least_one_text_source(self) -> BottleneckSources:
        if not self.text_sources:
            raise ValueError(
                "bottleneck_sources: enable at least one text source "
                f"({', '.join(BOTTLENECK_TEXT_SOURCES)}); series sources only confirm a "
                "tightening found in filings and headlines"
            )
        return self


def _apply_bottleneck_source_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """``OPTIONS_SCOUT_BOTTLENECK_SOURCES=edgar,fred,news`` enables exactly the listed sources."""
    env_val = os.environ.get("OPTIONS_SCOUT_BOTTLENECK_SOURCES")
    if not env_val:
        return raw
    wanted = {s.strip().lower() for s in env_val.split(",") if s.strip()}
    unknown = wanted - set(BOTTLENECK_SOURCE_NAMES)
    if unknown:
        raise ValueError(
            f"OPTIONS_SCOUT_BOTTLENECK_SOURCES: unknown source(s) {sorted(unknown)}; "
            f"choose from {list(BOTTLENECK_SOURCE_NAMES)}"
        )
    out = dict(raw)
    for name in BOTTLENECK_SOURCE_NAMES:
        block = out.get(name)
        out[name] = {**(block if isinstance(block, dict) else {}), "enabled": name in wanted}
    return out


# ------------------------------------------------------------------------- goals.yaml
class SavingsRateTable(_Strict):
    rates: list[float] = Field(min_length=1)
    real_return: float = Field(gt=-1.0, lt=1.0)

    @field_validator("rates")
    @classmethod
    def _rates_in_unit_interval(cls, v: list[float]) -> list[float]:
        if any(not 0.0 < r < 1.0 for r in v):
            raise ValueError("savings rates must be strictly between 0 and 1")
        return v


class GoalsConfig(_Strict):
    """Goal Planning assumptions (Phase 12 section 12.2); printed beside every projection."""

    withdrawal_rate: float = Field(gt=0.0, lt=0.5)
    fat_multiple: float = Field(gt=1.0)
    stretch_band: float = Field(ge=0.0, lt=0.5)
    max_horizon_years: int = Field(default=100, ge=1)
    assumed_return: dict[RiskProfileName, float]
    max_assumed_return: dict[RiskProfileName, float]
    assignment_frequency: dict[RiskProfileName, float]
    retirement_age: float = Field(gt=0.0)
    savings_rate_table: SavingsRateTable

    @model_validator(mode="after")
    def _every_profile(self) -> GoalsConfig:
        for name, table in (
            ("assumed_return", self.assumed_return),
            ("max_assumed_return", self.max_assumed_return),
            ("assignment_frequency", self.assignment_frequency),
        ):
            missing = {"conservative", "balanced", "aggressive"} - set(table)
            if missing:
                raise ValueError(f"goals.{name} is missing {sorted(missing)}")
        for profile, cap in self.max_assumed_return.items():
            if self.assumed_return[profile] > cap:
                raise ValueError(f"goals.assumed_return[{profile}] exceeds its max_assumed_return")
        return self


# -------------------------------------------------------------------------- news.yaml
class AlphaVantageNewsConfig(_Strict):
    enabled: bool = True
    api_key_env: str = "ALPHAVANTAGE_API_KEY"
    fixture_file: str = "ticker_news.jsonl"
    limit: int = Field(default=50, ge=1, le=1000)
    max_attempts: int = Field(default=3, ge=1, le=6)


class RssNewsConfig(_Strict):
    enabled: bool = True


class NewsSourcesConfig(_Strict):
    alphavantage: AlphaVantageNewsConfig = Field(default_factory=AlphaVantageNewsConfig)
    rss: RssNewsConfig = Field(default_factory=RssNewsConfig)


class NewsConfig(_Strict):
    """News Desk parameters and sources (Phase 12 section 12.3)."""

    half_life_days: float = Field(gt=0.0)
    stale_days: int = Field(ge=1)
    capture_window_days: int = Field(ge=0)
    max_items_per_ticker: int = Field(ge=1)
    cache_ttl_minutes: int = Field(ge=1)
    lookback_days: int = Field(default=14, ge=1)
    sources: NewsSourcesConfig = Field(default_factory=NewsSourcesConfig)


# --------------------------------------------------------------------------- tax.yaml
class TaxConfig(_Strict):
    """Tax & Accounts mechanics (Phase 12 section 12.4); no rates, no liability."""

    long_term_holding_days: int = Field(ge=1)
    wash_sale_window_days: int = Field(ge=1)
    early_withdrawal_age: float = Field(gt=0.0)
    section_1256_underlyings: list[str]
    equity_option_etfs: list[str]

    @field_validator("section_1256_underlyings", "equity_option_etfs", mode="before")
    @classmethod
    def _upper(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("expected a list of symbols")
        return sorted({str(t).strip().upper() for t in v if str(t).strip()})

    @model_validator(mode="after")
    def _disjoint(self) -> TaxConfig:
        both = set(self.section_1256_underlyings) & set(self.equity_option_etfs)
        if both:
            raise ValueError(f"symbols listed as both 1256 and equity options: {sorted(both)}")
        return self


# ---------------------------------------------------------------------- holdings.yaml
class HoldingsConfig(_Strict):
    """Holdings analysis parameters (Phase 12 section 12.6)."""

    covered_call_lot: int = Field(ge=1)
    beta_lookback_days: int = Field(ge=10)
    beta_index: str = Field(min_length=1)
    expense_ratios_pct: dict[str, float] = Field(default_factory=dict)
    sectors: dict[str, str] = Field(default_factory=dict)

    @field_validator("expense_ratios_pct", "sectors", mode="before")
    @classmethod
    def _upper_keys(cls, v: object) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("expected a mapping keyed by ticker")
        return {str(k).strip().upper(): val for k, val in v.items()}

    def expense_ratio(self, ticker: str) -> float | None:
        """Annual expense ratio as a fraction (0.0945% -> 0.000945), None for a stock."""
        pct = self.expense_ratios_pct.get(ticker.upper())
        return None if pct is None else pct / 100.0


# ---------------------------------------------------------------------------- rag.yaml
EmbedderName = Literal["hash", "fastembed"]
CollectionName = Literal["concepts", "basics", "tax", "rules", "filings", "evidence"]
COLLECTION_NAMES: tuple[str, ...] = ("concepts", "basics", "tax", "rules", "filings", "evidence")


class CollectionConfig(_Strict):
    weight: float = Field(default=1.0, ge=0.0)


def _default_shared_term() -> dict[EmbedderName, bool]:
    return {"hash": True, "fastembed": False}


class RagConfig(_Strict):
    """Retrieval layer settings (PRD section 5.6). ``OPTIONS_SCOUT_RAG_EMBEDDER`` overrides
    ``embedder`` so CI can pin the hash embedder while a developer indexes with fastembed."""

    embedder: EmbedderName = "hash"
    fastembed_model: str = "BAAI/bge-small-en-v1.5"
    hash_dimensions: int = Field(default=2048, ge=64)
    top_k: int = Field(default=6, ge=1)
    report_sources: int = Field(default=6, ge=1)
    similarity_floor: dict[EmbedderName, float]
    rrf_k: int = Field(default=60, ge=1)
    title_boost: float = Field(default=0.0, ge=0.0)  # BM25F-style bonus for a title-head match
    require_shared_term: dict[EmbedderName, bool] = Field(default_factory=_default_shared_term)
    chunk_tokens: int = Field(default=400, ge=50)
    overlap: float = Field(default=0.15, ge=0.0, lt=0.5)
    knowledge_dir: Path
    index_db: Path
    collections: dict[CollectionName, CollectionConfig]

    @model_validator(mode="after")
    def _complete(self) -> RagConfig:
        missing = set(COLLECTION_NAMES) - set(self.collections)
        if missing:
            raise ValueError(f"rag.collections is missing {sorted(missing)}")
        for name in ("hash", "fastembed"):
            if name not in self.similarity_floor:
                raise ValueError(f"rag.similarity_floor needs a value for {name!r}")
        return self

    @property
    def floor(self) -> float:
        return self.similarity_floor[self.embedder]

    @property
    def shared_term_required(self) -> bool:
        """Whether a chunk must share a content word with the query to be eligible (lexical
        embedders only; see ``config/rag.yaml``)."""
        return self.require_shared_term.get(self.embedder, False)

    def weight(self, kind: str) -> float:
        coll = self.collections.get(kind)  # type: ignore[call-overload]
        return coll.weight if coll is not None else 1.0

    def resolved(self, root: Path) -> RagConfig:
        return self.model_copy(
            update={"knowledge_dir": root / self.knowledge_dir, "index_db": root / self.index_db}
        )


def _apply_rag_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    env_val = os.environ.get("OPTIONS_SCOUT_RAG_EMBEDDER")
    return {**raw, "embedder": env_val} if env_val else raw


# ---------------------------------------------------------------------- compliance.yaml
class BannedPattern(_Strict):
    label: str
    pattern: str


class SuitabilityConfig(_Strict):
    min_buying_power: dict[Literal["csp", "leaps", "pmcc"], float]
    reject_naked_language_on_cash: bool = True
    reject_leverage_opportunity_when_conservative: bool = True


class GoalComplianceConfig(_Strict):
    """Check 9 (Phase 12): rules for a Goal Planning narrative."""

    require_status: bool = True  # "fits" / "stretch" / "does not fit" must appear
    require_stress_path: bool = True  # the stress path is named whenever a projection is shown
    fire_requires_withdrawal_source: bool = True  # variant + withdrawal rate + diversified research
    promise_pattern: str = r"\bwill (?:reach|hit|have|grow|be worth|cover|get you|retire)\b"


class TaxComplianceConfig(_Strict):
    """Check 11 (Phase 12): rules for a Tax & Accounts reply."""

    disclaimer: str = (
        "This is education, not tax advice; rules change and individual situations differ, so "
        "confirm with a tax professional or the IRS publication cited."
    )
    forbid_rates: bool = True  # never state the rate a reader will pay
    rate_pattern: str = (
        r"\b(?:taxed|tax rate|bracket|rate)\s+(?:at|of|is|will be)\s+\d{1,2}(?:\.\d+)?\s?%"
        r"|\b\d{1,2}(?:\.\d+)?\s?%\s+(?:tax|bracket|rate)\b"
    )
    imperative_pattern: str = (
        r"(?:^|[.!?]\s+)(?:file|report|claim|deduct|elect)\s+(?:your|the|a|form)\b"
    )


class ComplianceConfig(_Strict):
    """Section 13.1 rules: banned patterns with an allow-list, suitability limits, freshness."""

    max_age_days: int = Field(default=400, ge=1)
    reminder: str = "Education, not advice."
    require_delayed_data_statement: bool = True
    banned_patterns: list[BannedPattern]
    allow_list: list[str] = Field(default_factory=list)
    suitability: SuitabilityConfig
    goal: GoalComplianceConfig = Field(default_factory=GoalComplianceConfig)  # check 9 (Phase 12)
    tax: TaxComplianceConfig = Field(default_factory=TaxComplianceConfig)  # check 11 (Phase 12)

    @model_validator(mode="after")
    def _patterns_compile(self) -> ComplianceConfig:
        import re

        for bp in self.banned_patterns:
            re.compile(bp.pattern, re.IGNORECASE)
        for a in self.allow_list:
            re.compile(a, re.IGNORECASE)
        re.compile(self.goal.promise_pattern, re.IGNORECASE)
        re.compile(self.tax.rate_pattern, re.IGNORECASE)
        re.compile(self.tax.imperative_pattern, re.IGNORECASE)
        return self


# ------------------------------------------------------------------------------- loading
class AppConfig(_Strict):
    """Everything from config/ in one typed, frozen object."""

    root: Path
    settings: Settings
    risk: RiskProfiles
    rules: ScreenerRules
    social: SocialScoreConfig
    subreddits: Subreddits
    sources: SocialSources
    quality: QualityUniverse
    rag: RagConfig
    compliance: ComplianceConfig
    goals: GoalsConfig
    news: NewsConfig
    tax: TaxConfig
    holdings: HoldingsConfig
    bottleneck: BottleneckScoreConfig  # Phase 11, section 4A
    bottleneck_sources: BottleneckSources
    themes: ThemeMap  # validated theme map; `curated` derived from `quality`

    @property
    def paths(self) -> Paths:
        return self.settings.paths


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping at top level")
    return data


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Allow OPTIONS_SCOUT_<KEY> to override top-level scalar settings keys."""
    out = dict(raw)
    for key in ("data_mode", "llm_mode"):
        env_val = os.environ.get(f"OPTIONS_SCOUT_{key.upper()}")
        if env_val:
            out[key] = env_val
    return out


def load_config(root: Path | None = None) -> AppConfig:
    root = (root or repo_root()).resolve()
    cfg_dir = root / "config"
    settings_raw = _apply_env_overrides(_load_yaml(cfg_dir / "settings.yaml"))
    settings = Settings(**settings_raw)
    settings = settings.model_copy(update={"paths": settings.paths.resolved(root)})
    quality = QualityUniverse(**_load_yaml(cfg_dir / "quality_universe.yaml"))
    themes = load_theme_map(
        cfg_dir / "themes.yaml",
        curated=quality.symbols,
        is_valid_ticker=sec_ticker_validator(settings.paths.fixtures_dir),
    )
    return AppConfig(
        root=root,
        settings=settings,
        risk=RiskProfiles(**_load_yaml(cfg_dir / "risk_profiles.yaml")),
        rules=ScreenerRules(**_load_yaml(cfg_dir / "screener_rules.yaml")),
        social=SocialScoreConfig(**_load_yaml(cfg_dir / "social_score.yaml")),
        subreddits=Subreddits(**_load_yaml(cfg_dir / "subreddits.yaml")),
        sources=SocialSources(
            **_apply_source_overrides(_load_yaml(cfg_dir / "social_sources.yaml"))
        ),
        quality=quality,
        rag=RagConfig(**_apply_rag_overrides(_load_yaml(cfg_dir / "rag.yaml"))).resolved(root),
        compliance=ComplianceConfig(**_load_yaml(cfg_dir / "compliance.yaml")),
        goals=GoalsConfig(**_load_yaml(cfg_dir / "goals.yaml")),
        news=NewsConfig(**_load_yaml(cfg_dir / "news.yaml")),
        tax=TaxConfig(**_load_yaml(cfg_dir / "tax.yaml")),
        holdings=HoldingsConfig(**_load_yaml(cfg_dir / "holdings.yaml")),
        bottleneck=BottleneckScoreConfig(**_load_yaml(cfg_dir / "bottleneck_score.yaml")),
        bottleneck_sources=BottleneckSources(
            **_apply_bottleneck_source_overrides(_load_yaml(cfg_dir / "bottleneck_sources.yaml"))
        ).resolved(root),
        themes=themes,
    )


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Process-wide cached config. Call `get_config.cache_clear()` in tests that mutate env."""
    return load_config()
