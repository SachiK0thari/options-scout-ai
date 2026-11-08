"""Adapter protocols for the bottleneck engine (PRD section 4A.5).

Two kinds of source feed the engine:

* ``FilingSource`` (EDGAR, transcripts, news headlines, industry subreddits): returns text already
  windowed into ≤ 400-character :class:`FilingSnippet` items for the layer keywords it was asked
  about. Snippets are the *only* thing the LLM sees, and they are data, never instructions.
* ``SeriesSource`` (FRED, CSV trackers, Google Trends): returns a dated numeric series for a series
  id; the Python signals turn it into ``price_trend`` and ``price_deceleration``.

Every adapter has a ``live`` and a ``fixture`` mode and reports the same ``SourceStatus`` the
consumer-trend adapters use, so the Under-the-hood tab lists both engines the same way. Fixture
rows may carry a ``label`` (the designed classification the offline fixture LLM replays in step
11.3) and an ``adversarial`` flag (prompt-injection fixtures the evals count); adapters pop both
before validating the snippet and expose the labels as ``ground_truth``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from options_scout.core.models import ConstraintLabel, FilingSnippet, SeriesPoint
from options_scout.social.adapters.base import Mode, SourceStatus

__all__ = [
    "FilingSource",
    "Mode",
    "SeriesSource",
    "SnippetFixture",
    "SourceStatus",
    "fixtures_bottleneck_dir",
    "keyword_hits",
    "load_snippet_fixture",
]


class SourceAdapter(Protocol):
    name: str
    mode: Mode

    def status(self) -> SourceStatus: ...


class FilingSource(SourceAdapter, Protocol):
    """Snippets since ``since`` whose text matches any of ``keywords``.

    ``forms`` narrows EDGAR to 10-K / 10-Q / 8-K and is ignored by sources that have no form.
    ``until`` is the point-in-time bound (the run's ``as_of``): nothing dated after it is returned,
    so a snapshot built for an earlier day sees only what was public then. ``theme_id`` and
    ``layer_id`` are stamped on every snippet as the *query* that found it
    (``FilingSnippet.layer_hint``), never as its label.
    """

    @property
    def ground_truth(self) -> dict[str, ConstraintLabel]:
        """Fixture-only designed labels by snippet id (empty in live mode)."""
        ...

    def fetch(
        self,
        keywords: Sequence[str],
        since: datetime,
        forms: Sequence[str] | None = None,
        *,
        until: datetime | None = None,
        theme_id: str | None = None,
        layer_id: str | None = None,
    ) -> list[FilingSnippet]: ...


class SeriesSource(SourceAdapter, Protocol):
    """Observations of ``series_id`` between ``start`` and ``end`` inclusive, oldest first."""

    def fetch(self, series_id: str, start: date, end: date) -> list[SeriesPoint]: ...


def fixtures_bottleneck_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "bottleneck"


def keyword_hits(text: str, keywords: Sequence[str]) -> list[str]:
    """The keywords that occur in ``text`` (case-insensitive substring match), in query order."""
    low = text.lower()
    return [k for k in keywords if k and k.lower() in low]


class SnippetFixture:
    """A JSONL file of :class:`FilingSnippet` rows plus optional ``label`` / ``adversarial`` keys.

    Shared by the EDGAR and transcripts adapters (and tests): it is loaded once, then searched
    by keyword, date and form the way the live full-text search would be.
    """

    def __init__(self, path: Path | None, source: str) -> None:
        self.path = path
        self.source = source
        self._rows: list[FilingSnippet] | None = None
        self.ground_truth: dict[str, ConstraintLabel] = {}
        self.adversarial_ids: set[str] = set()

    def rows(self) -> list[FilingSnippet]:
        if self._rows is None:
            if self.path is None or not self.path.exists():
                raise FileNotFoundError(f"{self.source} fixture missing: {self.path}")
            self._rows = load_snippet_fixture(
                self.path, self.source, self.ground_truth, self.adversarial_ids
            )
        return self._rows

    def end_date(self) -> date | None:
        rows = self.rows()
        return max(r.date for r in rows) if rows else None

    def search(
        self,
        keywords: Sequence[str],
        since: datetime,
        forms: Sequence[str] | None,
        *,
        until: datetime | None = None,
        theme_id: str | None,
        layer_id: str | None,
    ) -> list[FilingSnippet]:
        since_day = since.date()
        until_day = until.date() if until is not None else None
        wanted = {f.upper() for f in forms} if forms else None
        out: list[FilingSnippet] = []
        for row in self.rows():
            if row.date < since_day or not keyword_hits(row.text, keywords):
                continue
            if until_day is not None and row.date > until_day:
                continue
            if wanted is not None and row.form is not None and row.form.upper() not in wanted:
                continue
            update: dict[str, Any] = {}
            if theme_id is not None:
                update["theme_id"] = theme_id
            if layer_id is not None:
                update["layer_hint"] = layer_id
            out.append(row.model_copy(update=update) if update else row)
        return out


def load_snippet_fixture(
    path: Path,
    source: str,
    ground_truth: dict[str, ConstraintLabel] | None = None,
    adversarial_ids: set[str] | None = None,
) -> list[FilingSnippet]:
    """Read a snippet JSONL fixture, popping the fixture-only ``label`` and ``adversarial`` keys."""
    out: list[FilingSnippet] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            raw: dict[str, Any] = json.loads(line)
            label = raw.pop("label", None)
            adversarial = bool(raw.pop("adversarial", False))
            raw.setdefault("source", source)
            snippet = FilingSnippet.model_validate(raw)
            if label is not None and ground_truth is not None:
                ground_truth[snippet.id] = ConstraintLabel.model_validate(
                    {"snippet_id": snippet.id, "confidence": 1.0, **label}
                )
            if adversarial and adversarial_ids is not None:
                adversarial_ids.add(snippet.id)
            out.append(snippet)
    return out
