"""Offline fixture store: one JSON per ticker under tests/fixtures/market/, plus indices.json.

Fixtures are full :class:`TickerSnapshot` payloads plus a 90-day close history, so every
consumer (screeners, HV, IV proxy, stress tests) works with no network.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from options_scout.core.models import TickerSnapshot

DEMO_TICKERS: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "COST",
    "NKE",
    "SBUX",
    "CMG",
    "ELF",
    "DECK",
    "SPY",
    "QQQ",
)


class TickerFixture(BaseModel):
    snapshot: TickerSnapshot
    close_history: list[float] = Field(min_length=31)
    recorded_with: str = "synthetic"  # "yfinance" when recorded live, "synthetic" otherwise


class IndexFixture(BaseModel):
    as_of: datetime
    vix_history: list[float] = Field(min_length=30)  # oldest → newest, ~252 closes
    vix_now: float
    irx_now: float  # 13-week T-bill yield in percent (e.g. 4.25)
    recorded_with: str = "synthetic"


class FixtureStore:
    def __init__(self, fixtures_dir: Path) -> None:
        self.root = fixtures_dir / "market"
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, ticker: str) -> Path:
        return self.root / f"{ticker.upper().replace('^', '_')}.json"

    def available(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json") if p.stem != "indices")

    def has(self, ticker: str) -> bool:
        return self.path_for(ticker).exists()

    def load(self, ticker: str) -> TickerFixture:
        path = self.path_for(ticker)
        if not path.exists():
            raise FileNotFoundError(f"no fixture for {ticker} at {path}")
        return TickerFixture.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, fixture: TickerFixture) -> Path:
        path = self.path_for(fixture.snapshot.ticker)
        path.write_text(fixture.model_dump_json(indent=1), encoding="utf-8")
        return path

    def load_indices(self) -> IndexFixture:
        path = self.root / "indices.json"
        if not path.exists():
            raise FileNotFoundError(f"no index fixture at {path}")
        return IndexFixture.model_validate_json(path.read_text(encoding="utf-8"))

    def save_indices(self, fixture: IndexFixture) -> Path:
        path = self.root / "indices.json"
        path.write_text(fixture.model_dump_json(indent=1), encoding="utf-8")
        return path


def json_default(o: Any) -> str:
    if isinstance(o, datetime | date):
        return o.isoformat()
    raise TypeError(f"not serialisable: {type(o)!r}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=json_default, sort_keys=True)
