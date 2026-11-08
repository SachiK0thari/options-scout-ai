"""Price-tracker CSVs the operator drops under ``data/bottleneck_series/`` (PRD 4A.5).

Industry trackers (memory contract prices, transformer lead-time surveys) are licensed data the
operator may have access to; the directory is gitignored and nothing in it is ever committed.
A series ``csv:<id>`` in the theme map reads ``<directory>/<id>.csv`` with a header row and the
columns ``date,value`` (ISO date; extra columns are ignored; unparsable rows are skipped). There is
no network, so ``live`` and ``fixture`` behave the same; tests point ``directory`` at a temp dir.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date
from pathlib import Path

from options_scout.bottleneck.adapters.base import Mode, SourceStatus
from options_scout.config import CsvSeriesSourceConfig
from options_scout.core.models import SeriesPoint

log = logging.getLogger(__name__)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]+$")


class CsvSeriesAdapter:
    name = "csv_series"

    def __init__(self, mode: Mode, cfg: CsvSeriesSourceConfig) -> None:
        self.mode = mode
        self.cfg = cfg
        self.directory = Path(cfg.directory)
        self._status = SourceStatus(name=self.name, mode=mode)
        if not self.directory.exists():
            self._status.detail = f"no tracker CSVs in {self.directory}"

    def status(self) -> SourceStatus:
        return self._status

    def available(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(p.stem for p in self.directory.glob("*.csv"))

    def fetch(self, series_id: str, start: date, end: date) -> list[SeriesPoint]:
        if not _SAFE_ID.match(series_id):
            self._status.ok = False
            self._status.errors.append(f"{series_id!r}: not a valid series file name")
            return []
        path = self.directory / f"{series_id}.csv"
        if not path.exists():
            self._status.ok = False
            self._status.errors.append(f"{series_id}: no file {path}")
            return []
        try:
            points = read_series_csv(path)
        except Exception as exc:
            self._status.ok = False
            self._status.errors.append(f"{series_id}: {type(exc).__name__}: {exc}")
            return []
        out = [p for p in points if start <= p.day <= end]
        if not out:
            self._status.errors.append(
                f"{series_id}: {path.name} has no rows between {start.isoformat()} and "
                f"{end.isoformat()}; the tracker file may be stale"
            )
        self._status.items += len(out)
        return out


def read_series_csv(path: Path) -> list[SeriesPoint]:
    """``date,value`` rows (header required, names case-insensitive, extra columns ignored)."""
    out: list[SeriesPoint] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = {f.strip().lower(): f for f in reader.fieldnames or []}
        day_col = fields.get("date") or fields.get("day")
        value_col = fields.get("value") or fields.get("price")
        if day_col is None or value_col is None:
            raise ValueError(f"{path.name}: header must contain `date` and `value` columns")
        for row in reader:
            try:
                out.append(
                    SeriesPoint(
                        day=date.fromisoformat(str(row[day_col]).strip()[:10]),
                        value=float(str(row[value_col]).strip()),
                    )
                )
            except (TypeError, ValueError, KeyError):
                continue
    out.sort(key=lambda p: p.day)
    return out
