"""VIX from FRED's VIXCLS when the market-data provider has no index data (W27 follow-up).

No network: the FRED fetch is a stub. The provider stand-in answers like MarketData.app did on
the user's plan on 2026-11-11 (no index quote, an empty candle series)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from options_scout.core import volatility
from options_scout.core.models import SeriesPoint
from options_scout.core.regime import make_regime
from options_scout.core.report import render_regime
from options_scout.data.cache import MemoryCache
from options_scout.data.market import (
    FRED_NOTICE,
    FredVix,
    MarketData,
    MarketDataError,
)

TODAY = datetime.now(tz=UTC).date()


class _NoIndexSource:
    name = "marketdata"

    def get_index_history(self, symbol: str, days: int) -> list[float]:
        return []  # what the user's plan returned

    def get_index_last(self, symbol: str) -> float:
        raise MarketDataError("MarketData.app returned no quote for ^VIX")

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class _IndexSource(_NoIndexSource):
    def get_index_history(self, symbol: str, days: int) -> list[float]:
        return [15.0 + (i % 10) for i in range(days)]

    def get_index_last(self, symbol: str) -> float:
        return 18.0


def _fred(values: list[float], calls: list[tuple[str, date, date]] | None = None) -> FredVix:
    def fetch(series_id: str, start: date, end: date) -> list[SeriesPoint]:
        if calls is not None:
            calls.append((series_id, start, end))
        days = [end - timedelta(days=len(values) - i) for i in range(len(values))]
        return [SeriesPoint(day=d, value=v) for d, v in zip(days, values, strict=True)]

    return FredVix(fetch)


def _md(source: Any, fallback: FredVix | None) -> MarketData:
    ttl = {k: 900 for k in ("option_chain", "spot", "earnings", "dividends", "history")}
    return MarketData(source, MemoryCache(), ttl, None, vix_fallback=fallback)


def test_vix_comes_from_fred_when_the_provider_has_no_index_data() -> None:
    values = [12.0 + 0.05 * i for i in range(300)]
    calls: list[tuple[str, date, date]] = []
    md = _md(_NoIndexSource(), _fred(values, calls))
    vix, pct = md.get_vix_percentile()
    window = values[-252:]
    assert vix == pytest.approx(values[-1])
    assert pct == pytest.approx(volatility.percentile_rank(values[-1], window))
    assert calls and calls[0][0] == "VIXCLS"
    assert md.vix_source is not None and "Chicago Board Options Exchange" in md.vix_source
    assert "VIXCLS" in md.vix_source and FRED_NOTICE in md.vix_source
    assert md.status["^VIX"].startswith("FRED VIXCLS, close of ")
    md.get_vix_percentile()
    assert len(calls) == 1  # kept in memory for the day; never written to the SQLite cache
    stored = [v for v, _exp in md.cache._data.values()]  # type: ignore[attr-defined]
    assert all(values[-1] not in (x if isinstance(x, list) else [x]) for x in stored)


def test_the_provider_wins_when_it_has_vix() -> None:
    calls: list[tuple[str, date, date]] = []
    md = _md(_IndexSource(), _fred([20.0] * 300, calls))
    vix, _pct = md.get_vix_percentile()
    assert vix == 18.0 and md.vix_source is None and not calls


def test_too_few_fred_closes_is_an_error_not_a_percentile() -> None:
    md = _md(_NoIndexSource(), _fred([20.0] * 5))
    with pytest.raises(MarketDataError, match="fewer than the 200 needed"):
        md.get_vix_percentile()


def test_both_failing_names_both_reasons() -> None:
    def broken(*_a: object) -> list[SeriesPoint]:
        raise MarketDataError("FRED VIXCLS: HTTP 400 from api.stlouisfed.org")

    md = _md(_NoIndexSource(), FredVix(broken))
    with pytest.raises(MarketDataError, match=r"provider \(.*VIX closes.*\) and FRED \(.*HTTP 400"):
        md.get_vix_percentile()


def test_without_a_fallback_the_provider_error_is_raised() -> None:
    with pytest.raises(MarketDataError, match=r"no quote|VIX closes"):
        _md(_NoIndexSource(), None).get_vix_percentile()


def test_no_fred_key_means_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert FredVix.from_env() is None
    monkeypatch.setenv("FRED_API_KEY", "   ")
    assert FredVix.from_env() is None


def test_the_report_cites_fred_when_vix_came_from_it() -> None:
    from options_scout.config import load_config

    tilt = load_config().risk.regime_tilt
    cited = make_regime(
        vix=19.92,
        vix_percentile=55.0,
        risk_free_rate=0.04,
        tilt=tilt,
        as_of=datetime.now(tz=UTC),
        source="live",
        vix_source="CBOE Volatility Index via FRED. " + FRED_NOTICE,
    )
    assert "VIX source: CBOE Volatility Index via FRED" in render_regime(cited)
    plain = cited.model_copy(update={"vix_source": None})
    assert "VIX source" not in render_regime(plain)


def test_fixture_mode_keeps_its_recorded_vix(config: Any) -> None:
    md = MarketData.from_config(config, mode="fixture")
    vix, pct = md.get_vix_percentile()
    assert vix > 0 and 0 <= pct <= 100 and md.vix_source is None
