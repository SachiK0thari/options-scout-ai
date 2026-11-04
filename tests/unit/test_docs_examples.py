"""docs/compliance.md promises how specific sentences fare under the eight checks (step 10.8).

The table between ``<!-- examples:start -->`` and ``<!-- examples:end -->`` is parsed here and every
row is run through ``run_compliance`` against the fixed payload the page describes, so the examples
cannot drift away from the code.
"""

from __future__ import annotations

from typing import Any

import pytest

from options_scout.config import AppConfig
from options_scout.core.compliance import run_compliance
from options_scout.core.models import Citation, Narrative, Paragraph
from tests.conftest import REPO_ROOT

DOC = REPO_ROOT / "docs" / "compliance.md"

PAYLOAD: dict[str, Any] = {
    "positions": [
        {
            "candidate_id": "CSP-COST-2026-12-18-850P",
            "strike": 850,
            "premium": 1250,
            "realistic_loss": 12345,
            "payoff": {"breakeven": 837.5},
        }
    ],
    "quality_screen": {"passed_count": 7, "excluded_count": 3},
    "risk": {"stress_drop_pct": 30},
}
SOURCES = [
    Citation(
        chunk_id="assignment#0",
        doc_id="assignment",
        title="Assignment",
        url="https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document",
        quote="Assignment is the process by which an option writer is selected.",
        tag="S1",
    )
]
RUN_TICKERS = ["COST", "NKE"]


def examples() -> list[tuple[str, str, str, str, bool]]:
    text = DOC.read_text(encoding="utf-8")
    block = text.split("<!-- examples:start -->")[1].split("<!-- examples:end -->")[0]
    rows: list[tuple[str, str, str, str, bool]] = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells[0] == "#":
            continue
        num, sentence, mode, check, verdict = cells[:5]
        assert verdict in ("accepted", "rejected"), line
        rows.append((num, sentence, mode, check, verdict == "accepted"))
    return rows


EXAMPLES = examples()


def test_table_covers_the_sentence_level_checks() -> None:
    assert len(EXAMPLES) >= 15
    by_check: dict[str, set[bool]] = {}
    for _, _, _, check, accepted in EXAMPLES:
        by_check.setdefault(check, set()).add(accepted)
    for check in ("check_language", "check_education_only", "check_citations", "check_numbers"):
        assert by_check[check] == {True, False}, f"{check} needs an accepted and a rejected row"


@pytest.mark.parametrize(
    ("num", "sentence", "mode", "check", "accepted"),
    EXAMPLES,
    ids=[f"row-{r[0]}" for r in EXAMPLES],
)
def test_documented_example_behaves_as_written(
    config: AppConfig, num: str, sentence: str, mode: str, check: str, accepted: bool
) -> None:
    narrative = Narrative(
        paragraphs=[
            Paragraph(mode=mode, text=sentence),  # type: ignore[arg-type]
            Paragraph(mode="notice", text=config.settings.disclaimer),
        ]
    )
    report = run_compliance(
        narrative,
        payload=PAYLOAD,
        sources=SOURCES,
        facts=None,
        cfg=config.compliance,
        disclaimer=config.settings.disclaimer,
        text_kind="report",
        run_tickers=RUN_TICKERS,
        delayed_data=False,
    )
    outcome = {c.name: c for c in report.checks}[check]
    verdict = "accepted" if accepted else "rejected"
    assert outcome.passed == accepted, (
        f"docs/compliance.md row {num} says {check} → {verdict} for {sentence!r}; "
        f"got passed={outcome.passed}: {outcome.detail}"
    )
