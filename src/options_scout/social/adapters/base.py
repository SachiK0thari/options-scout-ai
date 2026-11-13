"""Adapter protocols shared by every consumer-trend source.

Two kinds of source feed the engine (PRD section 4.3):

* ``PostSource`` (Reddit, X): returns public posts that go through the spam filters and LLM entity
  extraction and become per-entity mention series.
* ``AttentionSource`` (Wikipedia pageviews, Google Trends): returns a daily attention series for a
  keyword and only *confirms* trends found in posts.

News RSS is the third kind (the "Wall Street awareness" baseline) and keeps its own interface in
``news.py``. Every adapter has a ``live`` and a ``fixture`` mode and reports a ``SourceStatus``;
``social/sources.py`` builds the enabled set from ``config/social_sources.yaml``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Protocol

from options_scout.core.models import DailyCount, ExtractedEntity, SocialPost

Mode = Literal["live", "fixture"]


@dataclass
class SourceStatus:
    name: str
    mode: Mode
    ok: bool = True
    detail: str = ""
    items: int = 0
    errors: list[str] = field(default_factory=list)
    enabled: bool = True
    # W30: the earliest moment from which the last fetch is known to hold every matching post,
    # up to the fetch time. ``None`` means no complete coverage (failed, partly skipped or not a
    # post source). A source that returns the newest N posts, or only the last 7 days, sets it
    # later than the ``since`` it was asked for, so the baseline weeks before it are not zeros.
    covered_since: datetime | None = None

    @property
    def state(self) -> str:
        """Compact label for reports: disabled | ok | error."""
        if not self.enabled:
            return "disabled"
        return "ok" if self.ok else "error"


class SourceAdapter(Protocol):
    name: str
    mode: Mode

    def status(self) -> SourceStatus: ...


class PostSource(SourceAdapter, Protocol):
    """Posts since ``since``; fixture corpora may also carry gold extraction labels."""

    fixture_path: Path | None
    ground_truth: dict[str, list[ExtractedEntity]]

    def fetch(self, since: datetime) -> list[SocialPost]: ...


class AttentionSource(SourceAdapter, Protocol):
    """Daily attention series for ``keyword`` between ``start`` and ``end`` inclusive."""

    def fetch(self, keyword: str, start: date, end: date) -> list[DailyCount]: ...


def fixtures_social_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "social"


def merge_ground_truth(
    sources: Sequence[PostSource],
) -> Mapping[str, Sequence[ExtractedEntity]] | None:
    merged: dict[str, Sequence[ExtractedEntity]] = {}
    for s in sources:
        merged.update(s.ground_truth)
    return merged or None
