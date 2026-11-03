"""Google Trends interest-over-time as an attention source (live via pytrends) or fixture.

Google has no free official Trends API; ``pytrends`` is an archived, unofficial client that is
rate-limited (HTTP 429) and may break without notice. It is therefore an *optional* dependency
(``pip install -e ".[trends]"``) and the adapter never raises into the pipeline: any failure is
recorded in ``SourceStatus.errors`` and the entity is scored without this source. The series is a
0-100 relative index, which is fine because the engine only uses z-scores of each series against
its own baseline.

Fixture mode reads ``google_trends.json`` (keyword -> daily ``{day, count}`` list). The keyword is
the ``google_trends`` field of the brand-map entry, else the canonical entity name.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from options_scout.config import GoogleTrendsSourceConfig
from options_scout.core.models import DailyCount
from options_scout.social.adapters.base import Mode, SourceStatus

log = logging.getLogger(__name__)

ClientFactory = Callable[[], Any]  # returns an object with build_payload() / interest_over_time()


class GoogleTrendsAdapter:
    name = "google_trends"

    def __init__(
        self,
        mode: Mode,
        cfg: GoogleTrendsSourceConfig,
        fixture_path: Path | None = None,
        *,
        client_factory: ClientFactory | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mode = mode
        self.cfg = cfg
        self.fixture_path = fixture_path
        self._client_factory = client_factory
        self._client: Any | None = None
        self._sleep = sleep
        self._last_request = 0.0
        self._status = SourceStatus(name=self.name, mode=mode)
        self._fixture: dict[str, list[DailyCount]] | None = None

    def status(self) -> SourceStatus:
        return self._status

    def fetch(self, keyword: str, start: date, end: date) -> list[DailyCount]:
        try:
            if self.mode == "fixture":
                series = self._load_fixture().get(keyword, [])
                out = [d for d in series if start <= d.day <= end]
            else:
                out = self._fetch_live(keyword, start, end)
        except Exception as exc:
            self._status.ok = False
            self._status.errors.append(f"{keyword}: {type(exc).__name__}: {exc}")
            return []
        self._status.items += len(out)
        return out

    # -- fixture -----------------------------------------------------------------------
    def _load_fixture(self) -> dict[str, list[DailyCount]]:
        if self._fixture is None:
            if self.fixture_path is None or not self.fixture_path.exists():
                raise FileNotFoundError(f"google_trends fixture missing: {self.fixture_path}")
            raw = json.loads(self.fixture_path.read_text(encoding="utf-8"))
            self._fixture = {
                k: [DailyCount(day=date.fromisoformat(d["day"]), count=int(d["count"])) for d in v]
                for k, v in raw.items()
            }
        return self._fixture

    # -- live ----------------------------------------------------------------------------
    def _get_client(self) -> Any:
        if self._client is None:
            factory = self._client_factory or _pytrends_factory
            self._client = factory()
        return self._client

    def _pace(self) -> None:
        wait = self.cfg.min_request_interval_seconds - (time.monotonic() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    def _fetch_live(self, keyword: str, start: date, end: date) -> list[DailyCount]:
        client = self._get_client()
        self._pace()
        timeframe = f"{start.isoformat()} {end.isoformat()}"  # <= ~9 months gives daily points
        client.build_payload([keyword], timeframe=timeframe, geo=self.cfg.geo)
        frame = client.interest_over_time()
        return frame_to_counts(frame, keyword, start, end)


def frame_to_counts(frame: Any, keyword: str, start: date, end: date) -> list[DailyCount]:
    """Convert a pytrends ``interest_over_time`` DataFrame (index: Timestamp, column: keyword,
    plus ``isPartial``) into DailyCounts inside [start, end]."""
    if frame is None or getattr(frame, "empty", True) or keyword not in frame.columns:
        return []
    out: list[DailyCount] = []
    for ts, value in frame[keyword].items():
        day = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
        if start <= day <= end:
            out.append(DailyCount(day=day, count=max(0, int(value))))
    return out


def _pytrends_factory() -> Any:
    try:
        from pytrends.request import TrendReq
    except ImportError as exc:  # pragma: no cover - exercised only without the optional extra
        raise RuntimeError(
            "google_trends live mode needs the optional dependency: pip install -e '.[trends]'"
        ) from exc
    return TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)
