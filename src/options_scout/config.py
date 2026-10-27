"""Typed settings loaded from config/*.yaml with env-var overrides.

Every threshold in the system lives here (rule 7 of CLAUDE.md). Nothing numeric should be
hard-coded elsewhere.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

RiskProfileName = Literal["conservative", "balanced", "aggressive"]
DataMode = Literal["fixture", "live"]
LLMMode = Literal["fixture", "anthropic", "none"]


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


class LLMSettings(_Strict):
    provider: Literal["anthropic"]
    extraction_model: str
    explanation_model: str
    judge_model: str
    extraction_batch_size: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    pricing: dict[str, ModelPrice]


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


class RankingSettings(_Strict):
    alpha: float = Field(ge=0.0, le=1.0)
    option_quality_weights: OptionQualityWeights


class TrendSettings(_Strict):
    snapshot_max_age_hours: int
    top_n_investable: int
    evidence_posts_per_entity: int


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
    cross_source_max: int
    cross_source_z_threshold: float
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


# ------------------------------------------------------------------------ subreddits.yaml
class SubredditFetch(_Strict):
    posts_per_subreddit: int
    listing: Literal["new", "hot", "top"]
    comments: bool


class Subreddits(_Strict):
    consumer: list[str]
    stock: list[str]
    fetch: SubredditFetch


# ------------------------------------------------------------------------------- loading
class AppConfig(_Strict):
    """Everything from config/ in one typed, frozen object."""

    root: Path
    settings: Settings
    risk: RiskProfiles
    rules: ScreenerRules
    social: SocialScoreConfig
    subreddits: Subreddits

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
    return AppConfig(
        root=root,
        settings=settings,
        risk=RiskProfiles(**_load_yaml(cfg_dir / "risk_profiles.yaml")),
        rules=ScreenerRules(**_load_yaml(cfg_dir / "screener_rules.yaml")),
        social=SocialScoreConfig(**_load_yaml(cfg_dir / "social_score.yaml")),
        subreddits=Subreddits(**_load_yaml(cfg_dir / "subreddits.yaml")),
    )


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Process-wide cached config. Call `get_config.cache_clear()` in tests that mutate env."""
    return load_config()
