"""Live bottleneck sources (PRD 4A.5). Skipped by default; `make test-live` runs them.

EDGAR needs no key (set OPTIONS_SCOUT_CONTACT_EMAIL for a polite User-Agent); FRED needs
FRED_API_KEY and is skipped without it.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta

import pytest

from options_scout.bottleneck.adapters.edgar_fts import EdgarFullTextSearch
from options_scout.bottleneck.adapters.fred import FredSeriesAdapter
from options_scout.bottleneck.sources import sec_cik_to_ticker
from options_scout.bottleneck.themes import sec_ticker_validator
from options_scout.config import AppConfig
from options_scout.data.cache import MemoryCache

pytestmark = pytest.mark.live


def test_live_edgar_one_query(config: AppConfig) -> None:
    edgar = EdgarFullTextSearch(
        "live",
        config.bottleneck_sources.edgar.model_copy(update={"max_documents_per_query": 2}),
        cache=MemoryCache(),
        is_valid_ticker=sec_ticker_validator(config.paths.fixtures_dir),
        cik_to_ticker=sec_cik_to_ticker(config.paths.fixtures_dir),
    )
    # "grid interconnection" (a `power` layer keyword) had ~100 hits in the trailing year on
    # 2026-11-06; the narrower "transformer lead time" had none, so it is not a useful probe.
    since = datetime.now(tz=UTC) - timedelta(days=365)
    rows = edgar.fetch(["grid interconnection"], since, forms=["10-K", "10-Q"], layer_id="power")
    assert edgar.status().ok, edgar.status().errors
    assert rows and all("grid interconnection" in r.text.lower() for r in rows)
    assert all(r.form in {"10-K", "10-Q"} and r.date >= since.date() for r in rows)
    assert all(r.url and r.url.startswith("https://www.sec.gov/Archives/") for r in rows)


def test_live_fred_one_series(config: AppConfig) -> None:
    if not os.environ.get("FRED_API_KEY"):
        pytest.skip("FRED_API_KEY not set")
    fred = FredSeriesAdapter("live", config.bottleneck_sources.fred, cache=MemoryCache())
    pts = fred.fetch("WPU0543", date.today() - timedelta(days=400), date.today())
    assert fred.status().ok, fred.status().errors
    assert len(pts) >= 10 and all(p.value > 0 for p in pts)


def test_live_every_theme_map_series_still_publishes(config: AppConfig) -> None:
    """A discontinued PPI series comes back empty with no error (the fiber optic cable index
    stopped in 2025-06); this guard fails loudly so the theme map gets a replacement."""
    if not os.environ.get("FRED_API_KEY"):
        pytest.skip("FRED_API_KEY not set")
    fred = FredSeriesAdapter("live", config.bottleneck_sources.fred, cache=MemoryCache())
    start, end = date.today() - timedelta(days=400), date.today()
    empty = [
        f"{layer.id}: {ref.id}"
        for _, layer in config.themes.layers()
        for ref in layer.price_series
        if ref.source == "fred" and len(fred.fetch(ref.id, start, end)) < 6
    ]
    assert fred.status().ok, fred.status().errors
    assert empty == [], f"series without recent observations: {empty}"


def test_live_market_facts_for_a_curated_supplier(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The priced_in market terms and the earnings catalyst for one curated supplier, from the
    configured live market-data provider (skipped without its key)."""
    from options_scout.bottleneck.market_facts import market_facts_for
    from options_scout.data.market import MarketData, MarketDataError

    monkeypatch.setenv("OPTIONS_SCOUT_DATA_MODE", "live")
    try:
        md = MarketData.from_config(config, mode="live")
    except MarketDataError as exc:
        pytest.skip(str(exc))
    facts = market_facts_for(md, ["HON"])
    assert set(facts) == {"HON"}
    hon = facts["HON"]
    assert hon.rel_return_90d is not None and -1.0 < hon.rel_return_90d < 5.0
    assert hon.dist_from_high is not None and 0.0 <= hon.dist_from_high <= 1.0
    assert hon.iv_rank is None or 0.0 <= hon.iv_rank <= 100.0
    assert hon.next_event is None or hon.next_event >= date.today()
