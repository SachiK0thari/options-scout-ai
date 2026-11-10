"""Every ``OPTIONS_SCOUT_*`` environment variable, parsed and checked once at start-up (W42).

A bad value used to fail late and badly: ``OPTIONS_SCOUT_DATA_MODE=LIVE`` gave a 500 on every
request, ``OPTIONS_SCOUT_RATE_LIMIT_PER_MIN=abc`` crashed the API at import and ``0`` answered 429
on every route. :func:`check_startup` now parses them all through :class:`EnvSettings` (case and
surrounding spaces are normalised, an empty value counts as unset) and loads the YAML config, so a
bad setting stops the API, UI, CLI or a job before it serves anything, with one message naming
every bad variable.

The call sites still read ``os.environ`` (the tests set variables per test); this module is the
single place that decides which values are valid.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from options_scout.config import DataMode, EmbedderName, LLMMode, MarketProviderName

Flag = Literal["0", "1"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Tracing = Literal["langsmith", "off", "none"]

DEFAULT_RATE_LIMIT_PER_MIN = 30


class EnvConfigError(RuntimeError):
    """One or more ``OPTIONS_SCOUT_*`` variables (or the YAML config) are invalid."""


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPTIONS_SCOUT_", env_ignore_empty=True, extra="ignore", frozen=True
    )

    data_mode: DataMode | None = None
    llm_mode: LLMMode | None = None
    market_provider: MarketProviderName | None = None
    rag_embedder: EmbedderName | None = None
    rag_index_db: Path | None = None
    rate_limit_per_min: int = Field(default=DEFAULT_RATE_LIMIT_PER_MIN, ge=1, le=100_000)
    log_level: LogLevel = "INFO"
    tracing: Tracing | None = None
    allow_anonymous: Flag | None = None
    api_docs: Flag | None = None
    trusted_proxy: Flag | None = None
    otel: Flag | None = None
    dotenv: Flag | None = None
    root: Path | None = None
    checkpoint_db: Path | None = None

    @field_validator(
        "data_mode", "llm_mode", "market_provider", "rag_embedder", "tracing", mode="before"
    )
    @classmethod
    def _lower(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator(
        "allow_anonymous", "api_docs", "trusted_proxy", "otel", "dotenv", mode="before"
    )
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


def _describe(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        name = "OPTIONS_SCOUT_" + "_".join(str(p) for p in err["loc"]).upper()
        out.append(f"{name}={err.get('input')!r}: {err['msg']}")
    return out


def env_settings() -> EnvSettings:
    """The parsed variables. Raises :class:`EnvConfigError` naming every bad one."""
    try:
        return EnvSettings()
    except ValidationError as exc:
        raise EnvConfigError(
            "Invalid environment configuration:\n  " + "\n  ".join(_describe(exc))
        ) from None


def check_startup(root: Path | None = None) -> EnvSettings:
    """Validate the environment and the YAML config together; call once before serving.

    Raises :class:`EnvConfigError` with a readable message instead of failing per request."""
    settings = env_settings()
    from options_scout.config import load_config

    try:
        load_config(root)
    except (ValidationError, ValueError, OSError) as exc:
        raise EnvConfigError(f"Invalid configuration: {exc}") from None
    return settings


def check_startup_or_exit(root: Path | None = None) -> EnvSettings:
    """:func:`check_startup` for command-line entry points: print the problem and exit 2."""
    try:
        return check_startup(root)
    except EnvConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
