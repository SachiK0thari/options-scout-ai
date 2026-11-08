"""Earnings-call transcripts: fixture mode only.

Transcripts are where management says "lead times are now 100 weeks" in plain words, but they are
not on EDGAR: they are sold by financial-data vendors under licence. The engine therefore has a
transcripts *slot* (so a licensed feed can be plugged in without touching the pipeline) and a
fixture corpus for tests and demos, and nothing else. Live mode records that the source is
unavailable and returns no snippets; it never calls a vendor. The source is disabled by default in
``config/bottleneck_sources.yaml``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from options_scout.bottleneck.adapters.base import Mode, SnippetFixture, SourceStatus
from options_scout.core.models import ConstraintLabel, FilingSnippet

LIVE_UNAVAILABLE = (
    "earnings-call transcripts are not on EDGAR and are licensed from paid vendors; "
    "this adapter runs in fixture mode only"
)


class TranscriptsAdapter:
    name = "transcripts"

    def __init__(self, mode: Mode, fixture_path: Path | None = None) -> None:
        self.mode = mode
        self.fixture_path = fixture_path
        self._status = SourceStatus(name=self.name, mode=mode)
        self._fixture = SnippetFixture(fixture_path, self.name)
        if mode == "live":
            self._status.ok = False
            self._status.detail = LIVE_UNAVAILABLE
            self._status.errors.append(LIVE_UNAVAILABLE)

    def status(self) -> SourceStatus:
        return self._status

    @property
    def ground_truth(self) -> dict[str, ConstraintLabel]:
        return self._fixture.ground_truth

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
        if self.mode == "live":
            return []
        try:
            out = self._fixture.search(
                keywords, since, None, until=until, theme_id=theme_id, layer_id=layer_id
            )
        except Exception as exc:
            self._status.ok = False
            self._status.errors.append(f"{type(exc).__name__}: {exc}")
            return []
        self._status.items += len(out)
        return out
