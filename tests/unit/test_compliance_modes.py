"""W16: a model-written paragraph's mode follows its content, and a citation must support what it
is attached to (quotations found in the cited chunk, enough shared words), not only exist."""

from __future__ import annotations

from typing import Any

import pytest

from options_scout.config import AppConfig
from options_scout.core import compliance as cc
from options_scout.core.grounding import render_narrative
from options_scout.core.models import (
    DELAYED_DATA_NOTICE,
    NO_SOURCE_SENTENCE,
    Citation,
    ComplianceReport,
    Narrative,
    NarrativeDraft,
    Paragraph,
    ParagraphDraft,
    TokenUsage,
)
from options_scout.llm.client import LLMClient

# The opening of knowledge/concepts/assignment.md, as retrieval hands it to the writer
ASSIGNMENT = (
    "Assignment is the process by which an option writer is selected to fulfil the obligation of "
    "a contract that a holder has exercised. When a put holder exercises, some put writer is "
    "obliged to take the shares at the strike; when a call holder exercises, some call writer "
    "must deliver them. The Options Clearing Corporation (OCC) receives exercise notices from "
    "clearing members, assigns them at random to clearing members with short positions in the "
    "same series, and each clearing member then assigns its own customers by a method approved "
    "by the exchanges, usually random selection or first-in first-out."
)
SOURCES = [
    Citation(
        chunk_id="assignment#0",
        doc_id="assignment",
        title="Assignment: what happens when a short option is exercised against you",
        url="https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document",
        quote="Assignment is the process by which an option writer is selected.",
        tag="S1",
    )
]
CID = "CSP-NKE-2026-12-18-35P"


@pytest.fixture
def disc(config: AppConfig) -> str:
    return config.settings.disclaimer


def payload(disc: str) -> dict[str, Any]:
    return {
        "positions": [{"candidate_id": CID, "ticker": "NKE", "strike": 35, "realistic_loss": 1050}],
        "quality_screen": {"excluded": [{"ticker": "XYZ", "reason": "drawdown over the limit"}]},
        "risk": {"warnings": ["Data comes from free tiers and may be delayed."]},
        "sources": [
            {"tag": "S1", "title": SOURCES[0].title, "kind": "concepts", "text": ASSIGNMENT}
        ],
        "disclaimer": disc,
        "delayed_data_notice": DELAYED_DATA_NOTICE,
    }


def model(mode: str, text: str, *cites: str) -> Paragraph:
    return Paragraph(mode=mode, text=text, citations=list(cites), written_by="model")  # type: ignore[arg-type]


def run(config: AppConfig, disc: str, *paras: Paragraph) -> ComplianceReport:
    data = payload(disc)
    narrative = render_narrative(
        Narrative(paragraphs=[*paras, Paragraph(mode="notice", text=disc)]), data
    )
    return cc.run_compliance(
        narrative,
        payload=data,
        sources=SOURCES,
        facts=None,
        cfg=config.compliance,
        disclaimer=disc,
        text_kind="report",
        run_tickers=["NKE"],
        delayed_data=False,
    )


def check(report: ComplianceReport, name: str = "check_citations") -> Any:
    return {c.name: c for c in report.checks}[name]


# --------------------------------------------------------- step 1: the four sentences fail
def test_a_pick_labelled_notice_is_checked_as_education(config: AppConfig, disc: str) -> None:
    rep = run(
        config,
        disc,
        model(
            "notice", "NKE is the pick of this screen. Put most of the account in the NKE 35 put."
        ),
    )
    assert not rep.passed
    cite = check(rep)
    assert not cite.passed and "paragraph 1" in cite.locations
    assert "fixed notices" in cite.detail
    assert not check(rep, "check_education_only").passed  # a run ticker in education text


def test_a_general_claim_labelled_screen_result_needs_a_citation(
    config: AppConfig, disc: str
) -> None:
    rep = run(
        config,
        disc,
        model(
            "screen_result",
            "Selling puts is how professionals earn steady income; assignment is rare and "
            "losses are small.",
        ),
    )
    cite = check(rep)
    assert not rep.passed and not cite.passed
    assert "general claim" in cite.detail and cite.locations == ["paragraph 1"]


def test_a_citation_to_an_unrelated_article_fails(config: AppConfig, disc: str) -> None:
    rep = run(
        config,
        disc,
        model(
            "education",
            "LEAPS calls cannot expire worthless because they are long-dated. [S1]",
            "S1",
        ),
    )
    cite = check(rep)
    assert not cite.passed and "does not support" in cite.detail


def test_a_fabricated_quotation_fails(config: AppConfig, disc: str) -> None:
    rep = run(
        config,
        disc,
        model(
            "education",
            'The OCC states: "cash-secured puts have never produced a loss for disciplined '
            'sellers" [S1]',
            "S1",
        ),
    )
    cite = check(rep)
    assert not cite.passed and "quotation not found in the cited source" in cite.detail


@pytest.mark.parametrize(
    "quoted",
    [
        "“cash-secured puts never lose money”",
        "«cash-secured puts never lose money»",
        "'cash-secured puts never lose money'",
    ],
)
def test_every_quotation_mark_is_checked(config: AppConfig, disc: str, quoted: str) -> None:
    rep = run(
        config, disc, model("education", f"The OCC writes {quoted} about writers [S1].", "S1")
    )
    assert "quotation not found" in check(rep).detail


# ----------------------------------------------------------------- what still passes
def test_a_faithful_cited_paragraph_with_a_verbatim_quote_passes(
    config: AppConfig, disc: str
) -> None:
    text = (
        "Assignment is how a writer is selected to fulfil the obligation of an exercised "
        "contract [S1]. The OCC “assigns them at random to clearing members with short "
        "positions” and each clearing member “then assigns its own customers … "
        "usually random selection” [S1]."
    )
    rep = run(config, disc, model("education", text, "S1"))
    assert check(rep).passed, check(rep).detail


def test_model_notices_holding_only_fixed_texts_pass(config: AppConfig, disc: str) -> None:
    rep = run(
        config,
        disc,
        model("notice", "**Warnings and limitations.** {{risk.warnings[0]}}"),
        model("notice", "{{ delayed_data_notice }}"),
        model("notice", DELAYED_DATA_NOTICE.replace("'", "’")),
        model("notice", NO_SOURCE_SENTENCE),
    )
    assert check(rep).passed, check(rep).detail
    assert check(rep, "check_education_only").passed


def test_a_warning_slot_with_added_words_is_not_a_fixed_notice(
    config: AppConfig, disc: str
) -> None:
    rep = run(config, disc, model("notice", "{{risk.warnings[0]}} NKE is the one to watch."))
    assert "paragraph 1" in check(rep).locations


def test_a_notice_written_by_the_app_is_trusted(config: AppConfig, disc: str) -> None:
    rep = run(config, disc, Paragraph(mode="notice", text="Nothing was sized for this account."))
    assert check(rep).passed


def test_result_sentences_tied_to_the_run_pass(config: AppConfig, disc: str) -> None:
    rep = run(
        config,
        disc,
        model(
            "screen_result",
            f"**Positions.** {CID} met the criteria; its realistic loss is "
            f"{{{{positions[{CID}].realistic_loss|money}}}}. NKE passed the quality screen. "
            'XYZ was excluded: "drawdown over the limit".',
        ),
    )
    assert check(rep).passed, check(rep).detail


def test_a_cited_general_sentence_in_a_result_paragraph_is_checked_for_support(
    config: AppConfig, disc: str
) -> None:
    ok = run(
        config,
        disc,
        model(
            "screen_result",
            f"{CID} was screened in; its realistic loss is "
            f"{{{{positions[{CID}].realistic_loss|money}}}}. A put writer who is assigned is "
            "obliged to take the shares at the strike [S1].",
        ),
    )
    assert check(ok).passed, check(ok).detail
    bad = run(
        config,
        disc,
        model("screen_result", "Covered calls cap upside while dividends keep compounding [S1]."),
    )
    assert "does not support" in check(bad).detail


def test_an_uncited_result_may_quote_the_run_but_not_invent(config: AppConfig, disc: str) -> None:
    rep = run(config, disc, model("screen_result", 'XYZ was excluded: "drawdown far too deep".'))
    assert "quotation not found in the sources or this run's data" in check(rep).detail


def test_the_deterministic_report_still_passes(config: AppConfig, disc: str) -> None:
    """The rule writer's paragraphs are app-written: their modes are trusted as before."""
    from options_scout.llm.rules import education_paragraphs

    paras = education_paragraphs(payload(disc)["sources"])
    assert paras
    rep = run(config, disc, *paras)
    assert check(rep).passed, check(rep).detail


# ------------------------------------------------------------- who wrote the paragraph
class _Provider:
    def __init__(self, label: str) -> None:
        self.label = label

    def complete(self, **kw: Any) -> tuple[Any, TokenUsage]:
        draft = NarrativeDraft(paragraphs=[ParagraphDraft(mode="notice", text="x")])
        return draft, TokenUsage(model=self.label, task=kw["task"])


@pytest.mark.parametrize(("label", "author"), [("some-model", "model"), ("rule_based", "app")])
def test_the_llm_client_marks_what_a_model_wrote(
    config: AppConfig, label: str, author: str
) -> None:
    client = LLMClient(config, _Provider(label), "live", config.settings.llm.active)  # type: ignore[arg-type]
    prompt = client._prompt("answer_concept")
    names = ("question", "audience", "disclaimer", "intent", "sources")
    out = client._run("explain", "m", prompt, Narrative, **dict.fromkeys(names, "x"))
    assert isinstance(out, Narrative) and out.paragraphs[0].written_by == author


def test_the_model_schema_has_no_author_field() -> None:
    """The model cannot claim to be the app: ``written_by`` is not in the schema it is given."""
    assert "written_by" not in ParagraphDraft.model_json_schema()["properties"]
    assert "written_by" in Paragraph.model_fields


def test_a_quoted_glossary_term_is_not_a_quotation(config: AppConfig, disc: str) -> None:
    rep = run(
        config,
        disc,
        model(
            "education",
            'A writer opens the short put with a "sell to open" order and is obliged to take the '
            "shares at the strike if assigned [S1].",
            "S1",
        ),
    )
    assert check(rep).passed, check(rep).detail


def test_the_apps_own_caveat_in_a_result_paragraph_is_not_a_general_claim(
    config: AppConfig, disc: str
) -> None:
    rep = run(
        config,
        disc,
        model(
            "screen_result",
            "These are screened candidates that meet the configured criteria, not recommendations.",
        ),
    )
    assert check(rep).passed, check(rep).detail


@pytest.mark.parametrize(
    "sentence",
    [  # what DeepSeek wrote in the 2026-11-12 live eval, rejected before run_terms existed
        "No underlyings were excluded, so the excluded list is empty.",
        "The bottleneck board is also a secondary signal: it re-orders quality-gated stocks but "
        "never adds one.",
        "No underlyings were excluded this run.",
        "The trend board is a secondary signal only.",
        "No underlyings were excluded on quality grounds.",
        "The errors list shows these trending tickers were skipped because they are not on the "
        "good-to-own list.",
    ],
)
def test_sentences_about_the_runs_own_sections_are_results(
    config: AppConfig, disc: str, sentence: str
) -> None:
    rep = run(config, disc, model("screen_result", sentence))
    assert check(rep).passed, check(rep).detail


@pytest.mark.parametrize(
    "sentence",
    [
        "In this screen, selling puts is safe income and assignment is rare.",
        "Selling puts is how professionals earn steady income; assignment is rare and losses "
        "are small.",
    ],
)
def test_naming_the_screen_alone_does_not_make_a_claim_a_result(
    config: AppConfig, disc: str, sentence: str
) -> None:
    assert "general claim" in check(run(config, disc, model("screen_result", sentence))).detail


def test_a_quoted_slot_is_the_apps_value_not_a_quotation(config: AppConfig, disc: str) -> None:
    rep = run(
        config,
        disc,
        model(
            "screen_result",
            f'{CID} carries the warnings "{{{{risk.warnings|list}}}}"; its realistic loss is '
            f"{{{{positions[{CID}].realistic_loss|money}}}}.",
        ),
    )
    assert check(rep).passed, check(rep).detail
