from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, PositiveFloat, SecretStr

from options_scout.core.models import AccountType, RiskProfile, UserProfile


class MarketDataAuth(BaseModel):
    """Per-request market data provider. The key is a SecretStr: never logged or echoed."""

    provider: Literal["yfinance", "tradier"] = "yfinance"
    api_key: SecretStr | None = None
    sandbox: bool = True


class ScreenRequest(BaseModel):
    request_text: str | None = Field(default=None, max_length=4000)
    profile: UserProfile | None = None
    thread_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_\-]*$")
    market_data: MarketDataAuth | None = None  # omit → server default (fixture or configured)


class RecommendRequest(BaseModel):
    """The simple front door: buying power + what you want. Everything else has safe defaults."""

    buying_power: PositiveFloat
    strategy: Literal["csp", "leaps", "both"] = "both"
    account_type: AccountType = "cash"
    risk_profile: RiskProfile = "conservative"
    watchlist: list[str] = Field(default_factory=list, max_length=20)
    exclude: list[str] = Field(default_factory=list, max_length=50)
    max_positions: int = Field(default=6, ge=1, le=20)
    pmcc: bool = False
    market_data: MarketDataAuth | None = None

    def to_profile(self) -> UserProfile:
        strategies = {"csp": {"csp"}, "leaps": {"leaps"}, "both": {"csp", "leaps"}}[self.strategy]
        if self.pmcc and "leaps" in strategies:
            strategies = {*strategies, "pmcc"}
        return UserProfile(
            buying_power=self.buying_power,
            account_value=self.buying_power,
            account_type=self.account_type,
            risk_profile=self.risk_profile,
            strategies=strategies,
            watchlist=self.watchlist,
            exclude=self.exclude,
            max_positions=self.max_positions,
        )


class ScreenResponse(BaseModel):
    thread_id: str
    status: Literal["running", "interrupted", "completed", "failed"]


class ResumeRequest(BaseModel):
    answer: dict[str, Any]


class RunStatus(BaseModel):
    thread_id: str
    status: Literal["running", "interrupted", "completed", "failed", "unknown"]
    current_node: str | None
    nodes_visited: list[str]
    interrupt: dict[str, Any] | None
    errors: list[str]
    partial: dict[str, Any]


class QualityUniverseEntry(BaseModel):
    ticker: str
    name: str
    sector: str
    tags: list[str]
    why: str


class QualityUniverseResponse(BaseModel):
    gates: dict[str, Any]
    tickers: list[QualityUniverseEntry]


class Health(BaseModel):
    status: str
    data_mode: str
    llm_mode: str
    sources: dict[str, str]
    version: str
