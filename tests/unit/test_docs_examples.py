"""docs/compliance.md promises how specific sentences fare under the eleven checks (steps 10.8, 12.9).

Two tables are parsed here. The one between ``<!-- examples:start -->`` and ``<!-- examples:end -->``
is run through ``run_compliance`` as a report against the fixed screening payload the page describes.
The one between ``<!-- phase12-examples:start -->`` and ``<!-- phase12-examples:end -->`` is run as a
chat reply against the goal, news or tax payload its check column selects. Either way the examples
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

# Phase 12 payloads, as the page describes them.
GOAL_PLAN: dict[str, Any] = {
    "status": "stretch",
    "required_return_pct": 8.0,
    "available_return_pct": 5.2,
    "projection": {"years": 10, "stress_drop_pct": 30, "stress": 120000, "base": 150000},
}
FIRE_PLAN: dict[str, Any] = {
    **GOAL_PLAN,
    "fire": {"variant": "lean", "withdrawal_rate_pct": 4.0, "fire_number": 1200000},
}
NEWS: dict[str, Any] = {
    "headlines": [
        {"ticker": "COST", "title": "Costco raises membership fee for the first time since 2017"},
        {"ticker": "NKE", "title": "Nike reports quarterly results after the bell"},
    ]
}
TAX: dict[str, Any] = {"question": "what if I get assigned", "facts": {}}

PHASE12_PAYLOADS: dict[str, tuple[str, dict[str, Any]]] = {
    "goal_narrative": ("goal_narrative", {"goal_plan": GOAL_PLAN}),
    "goal_narrative (FIRE)": ("goal_narrative", {"goal_plan": FIRE_PLAN}),
    "news_grounding": ("news_grounding", {"news": NEWS, **PAYLOAD}),
    "tax_reply": ("tax_reply", {"tax": TAX}),
}


def _rows(start: str, end: str) -> list[tuple[str, str, str, str, bool]]:
    text = DOC.read_text(encoding="utf-8")
    block = text.split(start)[1].split(end)[0]
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


def examples() -> list[tuple[str, str, str, str, bool]]:
    return _rows("<!-- examples:start -->", "<!-- examples:end -->")


def phase12_examples() -> list[tuple[str, str, str, str, bool]]:
    return _rows("<!-- phase12-examples:start -->", "<!-- phase12-examples:end -->")


EXAMPLES = examples()
PHASE12 = phase12_examples()


def test_table_covers_the_sentence_level_checks() -> None:
    assert len(EXAMPLES) >= 15
    by_check: dict[str, set[bool]] = {}
    for _, _, _, check, accepted in EXAMPLES:
        by_check.setdefault(check, set()).add(accepted)
    for check in ("check_language", "check_education_only", "check_citations", "check_numbers"):
        assert by_check[check] == {True, False}, f"{check} needs an accepted and a rejected row"


def test_phase12_table_covers_the_three_specialist_checks() -> None:
    by_check: dict[str, set[bool]] = {}
    for _, _, _, check, accepted in PHASE12:
        assert check in PHASE12_PAYLOADS, check
        by_check.setdefault(PHASE12_PAYLOADS[check][0], set()).add(accepted)
    for check in ("goal_narrative", "news_grounding", "tax_reply"):
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


@pytest.mark.parametrize(
    ("num", "sentence", "mode", "check", "accepted"),
    PHASE12,
    ids=[f"row-{r[0]}" for r in PHASE12],
)
def test_documented_phase12_example_behaves_as_written(
    config: AppConfig, num: str, sentence: str, mode: str, check: str, accepted: bool
) -> None:
    check_name, payload = PHASE12_PAYLOADS[check]
    narrative = Narrative(
        paragraphs=[
            Paragraph(mode=mode, text=sentence),  # type: ignore[arg-type]
            Paragraph(mode="notice", text=config.settings.disclaimer),
        ]
    )
    report = run_compliance(
        narrative,
        payload={**payload, "disclaimer": config.settings.disclaimer},
        sources=SOURCES,
        facts=None,
        cfg=config.compliance,
        disclaimer=config.settings.disclaimer,
        text_kind="answer",
        run_tickers=RUN_TICKERS,
        delayed_data=False,
    )
    outcome = {c.name: c for c in report.checks}[check_name]
    verdict = "accepted" if accepted else "rejected"
    assert outcome.passed == accepted, (
        f"docs/compliance.md row {num} says {check_name} → {verdict} for {sentence!r}; "
        f"got passed={outcome.passed}: {outcome.detail}"
    )
