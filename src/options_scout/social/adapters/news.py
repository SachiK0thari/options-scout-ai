"""Google News RSS / Yahoo Finance RSS as the 'Wall Street awareness' baseline, or fixture."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote_plus

from options_scout.core.models import NewsItem
from options_scout.social.adapters.base import Mode, SourceStatus

log = logging.getLogger(__name__)

GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


class NewsAdapter:
    name = "news"

    def __init__(self, mode: Mode, fixture_path: Path | None = None) -> None:
        self.mode = mode
        self.fixture_path = fixture_path
        self._status = SourceStatus(name=self.name, mode=mode)
        self._fixture: list[NewsItem] | None = None

    def status(self) -> SourceStatus:
        return self._status

    def fetch(self, query: str, since: datetime, ticker: str | None = None) -> list[NewsItem]:
        try:
            if self.mode == "fixture":
                out = [
                    n for n in self._load_fixture() if n.query == query and n.published_at >= since
                ]
            else:
                out = self._fetch_live(query, since, ticker)
        except Exception as exc:
            self._status.ok = False
            self._status.errors.append(f"{query}: {type(exc).__name__}: {exc}")
            return []
        self._status.items += len(out)
        return out

    def _load_fixture(self) -> list[NewsItem]:
        if self._fixture is None:
            if self.fixture_path is None or not self.fixture_path.exists():
                raise FileNotFoundError(f"news fixture missing: {self.fixture_path}")
            items = []
            with self.fixture_path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        items.append(NewsItem.model_validate(json.loads(line)))
            self._fixture = items
        return self._fixture

    def _fetch_live(self, query: str, since: datetime, ticker: str | None) -> list[NewsItem]:
        import feedparser

        urls = [GOOGLE_NEWS.format(q=quote_plus(query))]
        if ticker:
            urls.append(YAHOO_RSS.format(ticker=ticker))
        out: list[NewsItem] = []
        for url in urls:
            feed = feedparser.parse(url)
            for e in feed.entries:
                published = _entry_time(e)
                if published is None or published < since:
                    continue
                link = str(getattr(e, "link", "") or "")
                nid = hashlib.sha1((link or str(e.get("title", ""))).encode()).hexdigest()[:16]
                out.append(
                    NewsItem(
                        id=nid,
                        title=str(e.get("title", ""))[:300],
                        published_at=published,
                        source=str(
                            getattr(getattr(e, "source", None), "title", "")
                            or feed.feed.get("title", "rss")
                        ),
                        url=link or None,
                        query=query,
                    )
                )
        return out


def _entry_time(e: object) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(e, attr, None)
        if t:
            try:
                y, mo, d, h, mi, sec = (int(x) for x in t[:6])
                return datetime(y, mo, d, h, mi, sec, tzinfo=UTC)
            except (TypeError, ValueError):
                continue
    return None
