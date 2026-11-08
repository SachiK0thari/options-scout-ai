"""SEC EDGAR full-text search (``efts.sec.gov/LATEST/search-index``) as the filings source.

Live mode runs one phrase query per layer keyword over 10-K / 10-Q / 8-K filings in the lookback
window, opens the top documents (``max_documents_per_query``) from ``www.sec.gov/Archives`` and
windows the text around the keyword into ≤ 400-character snippets. The filer's ticker comes from
the SEC company list by CIK (``display_names`` is the fallback) and is validated against the same
list; a filer without a listed ticker keeps ``filer_ticker=None``.

SEC fair-access rules (PRD 4A.5, 13): a descriptive ``User-Agent`` with a contact address, fewer
than 10 requests a second (``max_requests_per_second``, default 8), and a 24-hour SQLite cache so a
re-run never repeats a search or a download. 5xx and 429 responses are retried with backoff; any
other 4xx is final and recorded in ``SourceStatus.errors``. Earnings-call transcripts are **not**
on EDGAR; see ``transcripts.py``.

Fixture mode searches ``tests/fixtures/bottleneck/edgar_snippets.jsonl`` by keyword, date and form
exactly as the live search would, so the pipeline behaves the same offline.

Checked against the live API on 2026-11-06: a hit's ``_source`` carries ``ciks``, ``display_names``
(``"NAME  (TICK, TICKW)  (CIK 0000000000)"``), ``file_date``, ``form`` / ``file_type`` /
``root_forms`` and ``adsh``; the response has no passages, hence the document step above.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from options_scout.bottleneck.adapters.base import Mode, SnippetFixture, SourceStatus
from options_scout.bottleneck.snippets import make_snippet, strip_html, window_text
from options_scout.config import EdgarSourceConfig
from options_scout.core.models import ConstraintLabel, FilingSnippet

log = logging.getLogger(__name__)

ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
# "ACME CORP  (ACME, ACMEW)  (CIK 0000001234)": the first symbol in the bracket before "(CIK"
_DISPLAY_TICKER = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,9})(?:,\s*[A-Z0-9.\-]+)*\)\s*\(CIK")
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class EdgarFullTextSearch:
    name = "edgar"

    def __init__(
        self,
        mode: Mode,
        cfg: EdgarSourceConfig,
        fixture_path: Path | None = None,
        *,
        cache: Any | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        is_valid_ticker: Callable[[str], bool] | None = None,
        cik_to_ticker: Mapping[int, str] | None = None,
        now: datetime | None = None,
    ) -> None:
        self.mode = mode
        self.cfg = cfg
        self.fixture_path = fixture_path
        self.cache = cache  # SQLiteCache / MemoryCache (get/set with a TTL), optional
        self._transport = transport  # tests inject httpx.MockTransport
        self._sleep = sleep
        self._clock = clock
        self._is_valid_ticker = is_valid_ticker or (lambda _t: True)
        self._cik_to_ticker = dict(cik_to_ticker or {})
        self._now = now
        self._last_request = -1e9
        self._status = SourceStatus(name=self.name, mode=mode)
        self._fixture = SnippetFixture(fixture_path, self.name)

    def status(self) -> SourceStatus:
        return self._status

    @property
    def ground_truth(self) -> dict[str, ConstraintLabel]:
        return self._fixture.ground_truth

    @property
    def adversarial_ids(self) -> set[str]:
        return self._fixture.adversarial_ids

    def fixture_end(self) -> datetime | None:
        """Latest filing date in the fixture corpus (the pipeline's ``as_of`` offline)."""
        if self.mode != "fixture":
            return None
        try:
            day = self._fixture.end_date()
        except FileNotFoundError:
            return None
        return datetime.combine(day, datetime.min.time(), tzinfo=UTC) if day else None

    def fetch(
        self,
        keywords: Sequence[str],
        since: datetime,
        forms: Sequence[str] | None = None,
        *,
        until: datetime | None = None,
        theme_id: str | None = None,
        layer_id: str | None = None,
    ) -> list[FilingSnippet]:
        forms = list(forms) if forms else list(self.cfg.forms)
        try:
            if self.mode == "fixture":
                out = self._fixture.search(
                    keywords, since, forms, until=until, theme_id=theme_id, layer_id=layer_id
                )
            else:
                out = self._fetch_live(keywords, since, forms, until, theme_id, layer_id)
        except Exception as exc:
            self._status.ok = False
            self._status.errors.append(f"{type(exc).__name__}: {exc}")
            log.warning("edgar fetch failed: %s", exc)
            return []
        self._status.items += len(out)
        return out

    # -- live ----------------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        contact = os.environ.get(self.cfg.contact_email_env)
        if not contact:
            contact = "contact@example.com"
            self._status.detail = f"{self.cfg.contact_email_env} not set; SEC asks for a contact"
        return {
            "User-Agent": f"options-scout-ai/0.1 (educational screener) {contact}",
            "Accept-Encoding": "gzip, deflate",
        }

    def _fetch_live(
        self,
        keywords: Sequence[str],
        since: datetime,
        forms: list[str],
        until: datetime | None,
        theme_id: str | None,
        layer_id: str | None,
    ) -> list[FilingSnippet]:
        start = since.astimezone(UTC).date()
        end = (until or self._now or datetime.now(tz=UTC)).astimezone(UTC).date()
        out: list[FilingSnippet] = []
        seen_docs: set[str] = set()
        with httpx.Client(
            timeout=self.cfg.timeout_seconds, headers=self._headers(), transport=self._transport
        ) as client:
            for kw in keywords:
                try:
                    hits = self._search(client, kw, forms, start, end)
                except Exception as exc:
                    self._status.ok = False
                    self._status.errors.append(f"{kw!r}: {type(exc).__name__}: {exc}")
                    continue
                for hit in hits[: self.cfg.max_documents_per_query]:
                    doc = _parse_hit(hit)
                    if doc is None or doc["url"] in seen_docs:
                        continue
                    seen_docs.add(doc["url"])
                    try:
                        text = self._document_text(client, doc["url"])
                    except Exception as exc:
                        self._status.errors.append(f"{doc['url']}: {type(exc).__name__}: {exc}")
                        continue
                    ticker = self._resolve_ticker(doc)
                    for window in window_text(
                        text, keywords, max_windows=self.cfg.max_snippets_per_document
                    ):
                        out.append(
                            make_snippet(
                                source="edgar",
                                text=window,
                                day=doc["date"],
                                url=doc["url"],
                                filer_ticker=ticker,
                                form=doc["form"],
                                theme_id=theme_id,
                                layer_id=layer_id,
                            )
                        )
        return out

    def _search(
        self, client: httpx.Client, keyword: str, forms: list[str], start: Any, end: Any
    ) -> list[dict[str, Any]]:
        params = {
            "q": f'"{keyword}"',
            "forms": ",".join(forms),
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
        }
        cache_key = (
            f"edgar:search:{keyword}:{params['forms']}:{params['startdt']}:{params['enddt']}"
        )
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return list(cached)
        payload = self._get(client, self.cfg.base_url, params).json()
        hits = list(payload.get("hits", {}).get("hits", []) or [])
        if self.cache is not None:
            self.cache.set(cache_key, hits, self.cfg.cache_ttl_hours * 3600)
        return hits

    def _document_text(self, client: httpx.Client, url: str) -> str:
        cache_key = f"edgar:doc:{url}"
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return str(cached)
        resp = self._get(client, url, None)
        text = strip_html(resp.text[: self.cfg.max_document_chars])
        if self.cache is not None:
            self.cache.set(cache_key, text, self.cfg.cache_ttl_hours * 3600)
        return text

    def _pace(self) -> None:
        min_interval = 1.0 / self.cfg.max_requests_per_second
        wait = min_interval - (self._clock() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()

    def _get(self, client: httpx.Client, url: str, params: dict[str, str] | None) -> httpx.Response:
        delay = 1.0
        last: Exception | None = None
        for attempt in range(1, self.cfg.max_attempts + 1):
            self._pace()
            resp = client.get(url, params=params)
            if resp.status_code in _RETRY_STATUS:
                last = RuntimeError(f"HTTP {resp.status_code}")
                if attempt < self.cfg.max_attempts:
                    self._sleep(delay)
                    delay *= 2
                continue
            resp.raise_for_status()  # other 4xx: final
            return resp
        raise last or RuntimeError("no response")

    def _resolve_ticker(self, doc: dict[str, Any]) -> str | None:
        ticker: str | None = None
        cik = doc.get("cik")
        if isinstance(cik, int) and cik in self._cik_to_ticker:
            ticker = self._cik_to_ticker[cik]
        else:
            m = _DISPLAY_TICKER.search(str(doc.get("display_name") or ""))
            ticker = m.group(1) if m else None
        if ticker and self._is_valid_ticker(ticker):
            return ticker.upper()
        return None


def _parse_hit(hit: dict[str, Any]) -> dict[str, Any] | None:
    """``_id`` is ``<accession>:<filename>``; the document lives under
    ``/Archives/edgar/data/<cik>/<accession without dashes>/<filename>``."""
    src = hit.get("_source") or {}
    hid = str(hit.get("_id") or "")
    if ":" not in hid:
        return None
    accession, filename = hid.split(":", 1)
    ciks = src.get("ciks") or []
    if not ciks or not filename:
        return None
    try:
        cik = int(str(ciks[0]))
        day = datetime.strptime(str(src.get("file_date")), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    names = src.get("display_names") or []
    root_forms = src.get("root_forms") or []
    form = next(
        (
            str(v)
            for v in (src.get("form"), src.get("file_type"), src.get("form_type"), *root_forms)
            if v
        ),
        None,
    )
    return {
        "url": f"{ARCHIVES}/{cik}/{accession.replace('-', '')}/{filename}",
        "cik": cik,
        "date": day,
        "form": form,
        "display_name": str(names[0]) if names else "",
    }


def lookback_start(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)
