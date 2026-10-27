"""Wikimedia Pageviews API (free, no key, descriptive User-Agent required) or fixture."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from options_scout.core.models import DailyCount
from options_scout.social.adapters.base import Mode, SourceStatus

log = logging.getLogger(__name__)

API = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/"
    "all-access/user/{article}/daily/{start}/{end}"
)


class WikipediaAdapter:
    name = "wikipedia"

    def __init__(self, mode: Mode, fixture_path: Path | None = None) -> None:
        self.mode = mode
        self.fixture_path = fixture_path
        self._status = SourceStatus(name=self.name, mode=mode)
        self._fixture: dict[str, list[DailyCount]] | None = None

    def status(self) -> SourceStatus:
        return self._status

    def fetch(self, article: str, start: date, end: date) -> list[DailyCount]:
        try:
            if self.mode == "fixture":
                series = self._load_fixture().get(article, [])
                out = [d for d in series if start <= d.day <= end]
            else:
                out = self._fetch_live(article, start, end)
        except Exception as exc:
            self._status.ok = False
            self._status.errors.append(f"{article}: {type(exc).__name__}: {exc}")
            return []
        self._status.items += len(out)
        return out

    def _load_fixture(self) -> dict[str, list[DailyCount]]:
        if self._fixture is None:
            if self.fixture_path is None or not self.fixture_path.exists():
                raise FileNotFoundError(f"pageviews fixture missing: {self.fixture_path}")
            raw = json.loads(self.fixture_path.read_text(encoding="utf-8"))
            self._fixture = {
                k: [DailyCount(day=date.fromisoformat(d["day"]), count=int(d["count"])) for d in v]
                for k, v in raw.items()
            }
        return self._fixture

    def _fetch_live(self, article: str, start: date, end: date) -> list[DailyCount]:
        import httpx

        contact = os.environ.get("OPTIONS_SCOUT_CONTACT_EMAIL", "contact@example.com")
        url = API.format(
            article=quote(article.replace(" ", "_"), safe=""),
            start=start.strftime("%Y%m%d"),
            end=end.strftime("%Y%m%d"),
        )
        headers = {"User-Agent": f"options-scout-ai/0.1 (educational screener; {contact})"}
        with httpx.Client(timeout=20.0, headers=headers) as client:
            resp = client.get(url)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            items = resp.json().get("items", [])
        out = []
        for it in items:
            ts = str(it["timestamp"])  # YYYYMMDDHH
            out.append(
                DailyCount(
                    day=date(int(ts[:4]), int(ts[4:6]), int(ts[6:8])), count=int(it["views"])
                )
            )
        return out


def date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
