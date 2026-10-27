from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

Mode = Literal["live", "fixture"]


@dataclass
class SourceStatus:
    name: str
    mode: Mode
    ok: bool = True
    detail: str = ""
    items: int = 0
    errors: list[str] = field(default_factory=list)


class SourceAdapter(Protocol):
    name: str
    mode: Mode

    def status(self) -> SourceStatus: ...


def fixtures_social_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "social"
