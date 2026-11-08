"""FRED (``api.stlouisfed.org/fred/series/observations``) as the price-series source.

The theme map names a producer-price or industrial series per layer (verified by hand when the
layer is added); the engine turns it into ``price_trend`` and ``price_deceleration``. Live mode
needs the free key in ``FRED_API_KEY``; missing observations (FRED's ``"."``) are skipped; 400 /
404 (unknown series) are final and 5xx / 429 are retried. Responses are cached for
``cache_ttl_hours``. Fixture mode reads ``fred_series.json`` (series id → ``[{day, value}]``).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from options_scout.bottleneck.adapters.base import Mode, SourceStatus
from options_scout.config import FredSourceConfig
from options_scout.core.models import SeriesPoint

log = logging.getLogger(__name__)
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class FredSeriesAdapter:
    name = "fred"

    def __init__(
        self,
        mode: Mode,
        cfg: FredSourceConfig,
        fixture_path: Path | None = None,
        *,
        cache: Any | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mode = mode
        self.cfg = cfg
        self.fixture_path = fixture_path
        self.cache = cache
        self._transport = transport
        self._sleep = sleep
        self._status = SourceStatus(name=self.name, mode=mode)
        self._fixture: dict[str, list[SeriesPoint]] | None = None

    def status(self) -> SourceStatus:
        return self._status

    def fetch(self, series_id: str, start: date, end: date) -> list[SeriesPoint]:
        try:
            if self.mode == "fixture":
                series = self._load_fixture().get(series_id, [])
                out = [p for p in series if start <= p.day <= end]
            else:
                out = self._fetch_live(series_id, start, end)
        except Exception as exc:
            self._status.ok = False
            self._status.errors.append(f"{series_id}: {type(exc).__name__}: {exc}")
            log.warning("fred fetch failed for %s: %s", series_id, exc)
            return []
        if not out:
            # FRED answers a discontinued or mistyped id with a valid, empty response. The source
            # worked, so `ok` stays True, but the gap must be visible: an empty series must read as
            # "no price data", never as "prices flat" (PRD 4A.7).
            self._status.errors.append(empty_series_warning(series_id, start, end))
        self._status.items += len(out)
        return out

    # -- fixture -----------------------------------------------------------------------
    def _load_fixture(self) -> dict[str, list[SeriesPoint]]:
        if self._fixture is None:
            if self.fixture_path is None or not self.fixture_path.exists():
                raise FileNotFoundError(f"fred fixture missing: {self.fixture_path}")
            raw = json.loads(self.fixture_path.read_text(encoding="utf-8"))
            self._fixture = {k: parse_observations(v) for k, v in raw.items()}
        return self._fixture

    # -- live ----------------------------------------------------------------------------
    def _fetch_live(self, series_id: str, start: date, end: date) -> list[SeriesPoint]:
        key = os.environ.get(self.cfg.api_key_env)
        if not key:
            raise RuntimeError(f"{self.cfg.api_key_env} not set")
        cache_key = f"fred:{series_id}:{start.isoformat()}:{end.isoformat()}"
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return parse_observations(cached)
        params = {
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }
        body = self._get_with_backoff(params)
        points = parse_observations(body.get("observations", []))
        if self.cache is not None:
            self.cache.set(
                cache_key,
                [{"day": p.day.isoformat(), "value": p.value} for p in points],
                self.cfg.cache_ttl_hours * 3600,
            )
        return points

    def _get_with_backoff(self, params: dict[str, str]) -> dict[str, Any]:
        delay = 1.0
        last: Exception | None = None
        with httpx.Client(timeout=self.cfg.timeout_seconds, transport=self._transport) as client:
            for attempt in range(1, self.cfg.max_attempts + 1):
                resp = client.get(self.cfg.base_url, params=params)
                if resp.status_code in _RETRY_STATUS:
                    last = RuntimeError(f"HTTP {resp.status_code}")
                    if attempt < self.cfg.max_attempts:
                        self._sleep(delay)
                        delay *= 2
                    continue
                if resp.status_code >= 400:
                    detail = _error_message(resp)
                    raise RuntimeError(f"HTTP {resp.status_code}: {detail}")  # final
                return dict(resp.json())
        raise last or RuntimeError("no response")

    def __repr__(self) -> str:  # never echo the key
        return f"FredSeriesAdapter(mode={self.mode!r})"


def empty_series_warning(series_id: str, start: date, end: date) -> str:
    return (
        f"{series_id}: no observations between {start.isoformat()} and {end.isoformat()}; "
        "the series may be discontinued or the id wrong (verify it on fred.stlouisfed.org)"
    )


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("error_message") or body)[:160]
    except ValueError:
        return resp.text[:160]


def parse_observations(rows: Any) -> list[SeriesPoint]:
    """FRED ``observations[]`` (``date``, ``value``; ``"."`` means missing) or the fixture's
    ``{day, value}`` rows → :class:`SeriesPoint` list, oldest first."""
    out: list[SeriesPoint] = []
    for row in rows or []:
        raw_day = row.get("day") or row.get("date")
        raw_value = row.get("value")
        if raw_day is None or raw_value in (None, "", "."):
            continue
        try:
            day = date.fromisoformat(str(raw_day)[:10])
            out.append(SeriesPoint(day=day, value=float(raw_value)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda p: p.day)
    return out
