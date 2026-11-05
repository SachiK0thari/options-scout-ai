"""Alpha Vantage NEWS_SENTIMENT as the News Desk's per-ticker headline source (Phase 12, 12.5).

Live mode calls ``https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers=<T>`` with the
key from the environment (free tier: 25 requests a day), retries 429 / 5xx with exponential
backoff, treats the provider's ``Note`` / ``Information`` rate-limit bodies as errors, and caches
each ticker's response for ``cache_ttl_minutes``. Fixture mode reads
``tests/fixtures/social/ticker_news.jsonl`` (query = ticker). Items are normalised into
``NewsItem`` with the provider's per-ticker sentiment score passed through.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from options_scout.config import AlphaVantageNewsConfig
from options_scout.core.models import NewsItem
from options_scout.social.adapters.base import Mode, SourceStatus

log = logging.getLogger(__name__)

API_URL = "https://www.alphavantage.co/query"
RATE_LIMIT_KEYS = ("Note", "Information")


class AlphaVantageNewsAdapter:
    name = "alphavantage_news"

    def __init__(
        self,
        mode: Mode,
        cfg: AlphaVantageNewsConfig,
        fixture_path: Path | None = None,
        *,
        cache: Any | None = None,
        ttl_seconds: int = 1800,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mode = mode
        self.cfg = cfg
        self.fixture_path = fixture_path
        self.cache = cache  # SQLiteCache / MemoryCache (get/set with a TTL), optional
        self.ttl_seconds = ttl_seconds
        self._transport = transport
        self._sleep = sleep
        self._status = SourceStatus(name=self.name, mode=mode)
        self._fixture: list[NewsItem] | None = None

    def status(self) -> SourceStatus:
        return self._status

    def fetch(self, ticker: str, since: datetime) -> list[NewsItem]:
        ticker = ticker.upper()
        try:
            if self.mode == "fixture":
                out = [
                    n for n in self._load_fixture() if n.query == ticker and n.published_at >= since
                ]
            else:
                out = self._fetch_live(ticker, since)
        except Exception as exc:
            self._status.ok = False
            self._status.errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
            log.warning("alphavantage news fetch failed for %s: %s", ticker, exc)
            return []
        self._status.items += len(out)
        return out

    # -- fixture -----------------------------------------------------------------------
    def _load_fixture(self) -> list[NewsItem]:
        if self._fixture is None:
            if self.fixture_path is None or not self.fixture_path.exists():
                raise FileNotFoundError(f"ticker news fixture missing: {self.fixture_path}")
            items: list[NewsItem] = []
            with self.fixture_path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        items.append(NewsItem.model_validate(json.loads(line)))
            self._fixture = items
        return self._fixture

    # -- live ----------------------------------------------------------------------------
    def _fetch_live(self, ticker: str, since: datetime) -> list[NewsItem]:
        key = os.environ.get(self.cfg.api_key_env)
        if not key:
            raise RuntimeError(f"{self.cfg.api_key_env} not set")
        cache_key = f"avnews:{ticker}:{since.strftime('%Y%m%dT%H%M')}:{self.cfg.limit}"
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return [NewsItem.model_validate(r) for r in cached]
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "time_from": since.astimezone(UTC).strftime("%Y%m%dT%H%M"),
            "limit": str(self.cfg.limit),
            "sort": "LATEST",
            "apikey": key,
        }
        body = self._get_with_backoff(params)
        items = parse_feed(body, ticker)
        if self.cache is not None:
            self.cache.set(cache_key, [i.model_dump(mode="json") for i in items], self.ttl_seconds)
        return items

    def _get_with_backoff(self, params: dict[str, str]) -> dict[str, Any]:
        delay = 1.0
        last: Exception | None = None
        with httpx.Client(timeout=20.0, transport=self._transport) as client:
            for attempt in range(1, self.cfg.max_attempts + 1):
                resp = client.get(API_URL, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = RuntimeError(f"HTTP {resp.status_code}")
                else:
                    resp.raise_for_status()
                    body = resp.json()
                    limited = next((k for k in RATE_LIMIT_KEYS if k in body), None)
                    if limited is None:
                        return dict(body)
                    last = RuntimeError(f"rate limited: {str(body[limited])[:120]}")
                if attempt < self.cfg.max_attempts:
                    self._sleep(delay)
                    delay *= 2
        raise last or RuntimeError("no response")


def _parse_time(raw: str) -> datetime | None:
    """Alpha Vantage times look like ``20260301T120000``."""
    try:
        return datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def parse_feed(body: dict[str, Any], ticker: str) -> list[NewsItem]:
    """``feed[]`` entries → ``NewsItem`` with the per-ticker sentiment score when present."""
    out: list[NewsItem] = []
    for entry in body.get("feed", []) or []:
        published = _parse_time(str(entry.get("time_published", "")))
        title = str(entry.get("title", "")).strip()
        if published is None or not title:
            continue
        url = str(entry.get("url", "") or "") or None
        sentiment: float | None = None
        for ts in entry.get("ticker_sentiment", []) or []:
            if str(ts.get("ticker", "")).upper() == ticker:
                try:
                    sentiment = max(-1.0, min(1.0, float(ts.get("ticker_sentiment_score"))))
                except (TypeError, ValueError):
                    sentiment = None
                break
        nid = "av-" + hashlib.sha1((url or title).encode()).hexdigest()[:12]
        out.append(
            NewsItem(
                id=nid,
                title=title[:300],
                published_at=published,
                source=str(entry.get("source", "") or "Alpha Vantage")[:80],
                url=url,
                query=ticker,
                sentiment=sentiment,
            )
        )
    return out
