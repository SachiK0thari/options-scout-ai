"""SEC company_tickers.json: ticker validation + company names (requires a contact User-Agent)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from options_scout.social.adapters.base import Mode, SourceStatus

log = logging.getLogger(__name__)
SEC_URL = "https://www.sec.gov/files/company_tickers.json"


@dataclass(frozen=True)
class SECCompany:
    ticker: str
    title: str
    cik: int


class SECAdapter:
    name = "sec"

    def __init__(self, mode: Mode, fixture_path: Path, cache_path: Path | None = None) -> None:
        self.mode = mode
        self.fixture_path = fixture_path
        self.cache_path = cache_path
        self._status = SourceStatus(name=self.name, mode=mode)
        self._by_ticker: dict[str, SECCompany] | None = None

    def status(self) -> SourceStatus:
        return self._status

    def companies(self) -> dict[str, SECCompany]:
        if self._by_ticker is None:
            raw = self._load()
            self._by_ticker = {}
            for v in raw.values():
                t = str(v["ticker"]).upper()
                self._by_ticker[t] = SECCompany(
                    ticker=t, title=str(v["title"]), cik=int(str(v["cik_str"]))
                )
            self._status.items = len(self._by_ticker)
        return self._by_ticker

    def is_valid_ticker(self, ticker: str | None) -> bool:
        return bool(ticker) and str(ticker).upper() in self.companies()

    def name_of(self, ticker: str) -> str | None:
        c = self.companies().get(ticker.upper())
        return c.title if c else None

    def _load(self) -> dict[str, dict[str, object]]:
        if self.mode == "live":
            try:
                return self._fetch_live()
            except Exception as exc:
                self._status.errors.append(f"live fetch failed, using fixture: {exc}")
        data: dict[str, dict[str, object]] = json.loads(
            self.fixture_path.read_text(encoding="utf-8")
        )
        return data

    def _fetch_live(self) -> dict[str, dict[str, object]]:
        import httpx

        contact = os.environ.get("OPTIONS_SCOUT_CONTACT_EMAIL", "contact@example.com")
        headers = {
            "User-Agent": f"options-scout-ai/0.1 {contact}",
            "Accept-Encoding": "gzip, deflate",
        }
        with httpx.Client(timeout=30.0, headers=headers) as client:
            resp = client.get(SEC_URL)
            resp.raise_for_status()
            data: dict[str, dict[str, object]] = resp.json()
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(data), encoding="utf-8")
        return data
