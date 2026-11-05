"""Alpha Vantage news adapter (Phase 12 step 12.5): fixture mode and a mocked live transport."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from options_scout.config import AppConfig
from options_scout.data.cache import MemoryCache
from options_scout.social.adapters.alphavantage_news import AlphaVantageNewsAdapter, parse_feed
from options_scout.social.news_desk import build_news_sources

SINCE = datetime(2026, 10, 1, tzinfo=UTC)


def test_fixture_mode_returns_ticker_headlines_with_sentiment(config: AppConfig) -> None:
    sources = build_news_sources(config, "fixture")
    assert sources.alphavantage is not None and sources.rss is not None
    items = sources.fetch("COST", "Costco Wholesale", SINCE)
    assert len(items) == 6 and all(i.query == "COST" for i in items)
    assert all(i.sentiment is not None for i in items)
    assert sources.alphavantage.status().items == 6 and sources.alphavantage.status().ok
    assert sources.fetch("ZZZZ", None, SINCE) == []  # unknown ticker: nothing, no error
    later = SINCE + timedelta(days=24)
    assert len(sources.fetch("COST", None, later)) < 6  # the since filter applies


def _feed(ticker: str) -> dict[str, object]:
    return {
        "items": "2",
        "feed": [
            {
                "title": f"{ticker} reports quarterly earnings above estimates",
                "url": f"https://example.com/{ticker.lower()}/earnings",
                "time_published": "20261020T133000",
                "source": "Reuters",
                "ticker_sentiment": [
                    {"ticker": ticker, "ticker_sentiment_score": "0.312"},
                    {"ticker": "SPY", "ticker_sentiment_score": "0.05"},
                ],
            },
            {
                "title": f"{ticker} launches new product line",
                "url": f"https://example.com/{ticker.lower()}/launch",
                "time_published": "20261019T090000",
                "source": "Bloomberg",
                "ticker_sentiment": [],
            },
            {"title": "", "url": "https://example.com/empty", "time_published": "bad"},
        ],
    }


def test_parse_feed_normalises_and_passes_sentiment_through() -> None:
    items = parse_feed(_feed("COST"), "COST")
    assert [i.source for i in items] == ["Reuters", "Bloomberg"]
    assert items[0].sentiment == 0.312 and items[1].sentiment is None
    assert items[0].published_at == datetime(2026, 10, 20, 13, 30, tzinfo=UTC)
    assert items[0].id.startswith("av-") and items[0].query == "COST"


def test_live_mode_caches_and_backs_off(config: AppConfig, monkeypatch: object) -> None:
    import os

    os.environ["ALPHAVANTAGE_API_KEY"] = "test-key"
    calls: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["tickers"])
        if len(calls) == 1:
            return httpx.Response(200, json={"Note": "Thank you for using Alpha Vantage! 25/day"})
        if len(calls) == 2:
            return httpx.Response(429, json={"title": "Too Many Requests"})
        return httpx.Response(200, json=_feed("COST"))

    cache = MemoryCache()
    adapter = AlphaVantageNewsAdapter(
        "live",
        config.news.sources.alphavantage,
        None,
        cache=cache,
        ttl_seconds=60,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    items = adapter.fetch("COST", SINCE)
    assert len(items) == 2 and len(calls) == 3 and sleeps == [1.0, 2.0]
    assert adapter.status().ok and adapter.status().items == 2
    # second call is served from the cache: no new request
    again = adapter.fetch("COST", SINCE)
    assert len(again) == 2 and len(calls) == 3
    assert "apikey" not in repr(adapter)


def test_live_mode_records_errors_instead_of_raising(config: AppConfig) -> None:
    import os

    os.environ.pop("ALPHAVANTAGE_API_KEY", None)
    adapter = AlphaVantageNewsAdapter("live", config.news.sources.alphavantage, None)
    assert adapter.fetch("COST", SINCE) == []
    assert not adapter.status().ok and "ALPHAVANTAGE_API_KEY" in adapter.status().errors[0]

    os.environ["ALPHAVANTAGE_API_KEY"] = "k"
    exhausted = AlphaVantageNewsAdapter(
        "live",
        config.news.sources.alphavantage,
        None,
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
        sleep=lambda _s: None,
    )
    assert exhausted.fetch("COST", SINCE) == [] and "HTTP 500" in exhausted.status().errors[0]
    os.environ.pop("ALPHAVANTAGE_API_KEY", None)
