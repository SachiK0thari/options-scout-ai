"""Phase 10 step 10.4: the eight checks of PRD section 13.1, one test per check, plus the matrix."""

from __future__ import annotations

from datetime import date

import pytest

from options_scout.config import AppConfig, ComplianceConfig
from options_scout.core import compliance as cc
from options_scout.core.models import (
    Citation,
    Narrative,
    Paragraph,
    SuitabilityFacts,
    VerificationResult,
)

DISC = (
    "Educational screening tool. Not investment, tax or legal advice. Options involve "
    "significant risk, including loss exceeding the premium received on margin. Data may be "
    "delayed or inaccurate."
)
PAYLOAD = {
    "positions": [
        {
            "candidate_id": "CSP-COST-2026-12-18-850P",
            "strike": 850,
            "premium": 1250,
            "realistic_loss": 12345,
        }
    ],
    "portfolio": {"capital_used": 85000},
    "sources": [
        {"tag": "S1", "text": "20% of the stock price or 10% of the strike, times 100 shares"}
    ],
    "disclaimer": DISC,
}
SOURCES = [
    Citation(
        chunk_id="reg-t-margin#0",
        doc_id="reg-t-margin",
        title="Reg T",
        url="https://www.ecfr.gov/",
        quote="Regulation T is the Federal Reserve Board rule.",
        kind="rules",
        tag="S1",
        as_of=date(2026, 11, 3),
    )
]


def edu(text: str, *cites: str) -> Paragraph:
    return Paragraph(mode="education", text=text, citations=list(cites))


def res(text: str) -> Paragraph:
    return Paragraph(mode="screen_result", text=text)


def notice(text: str = DISC) -> Paragraph:
    return Paragraph(mode="notice", text=text)


def facts(**over: object) -> SuitabilityFacts:
    base: dict[str, object] = {
        "account_type": "margin",
        "risk_profile": "balanced",
        "buying_power": 100_000,
        "account_value": 100_000,
        "strategies_requested": ["csp", "leaps", "pmcc"],
        "strategies_present": ["csp", "leaps"],
        "margin_used": 1655,
        "realistic_loss_pct": 0.04,
        "max_position_loss_pct": 0.024,
        "loss_limit_pct": 0.03,
        "position_count": 2,
        "max_positions": 8,
    }
    return SuitabilityFacts.model_validate({**base, **over})


@pytest.fixture
def ccfg(config: AppConfig) -> ComplianceConfig:
    return config.compliance


# ---------------------------------------------------------------------------- 1 numbers
def test_check_numbers_reports_ungrounded() -> None:
    ok = cc.verify_narrative("Realistic loss 12345. " + DISC, PAYLOAD, disclaimer=DISC)
    assert cc.check_numbers(ok).passed
    bad = cc.verify_narrative("Expect 23.7% a year. " + DISC, PAYLOAD, disclaimer=DISC)
    check = cc.check_numbers(bad)
    assert not check.passed and check.locations == ["23.7%"] and check.severity == "block"


# -------------------------------------------------------------------------- 2 citations
def test_check_citations_tags_and_uncited_education() -> None:
    good = Narrative(paragraphs=[edu("Reg T sets the rules [S1].", "S1"), notice()])
    assert cc.check_citations(good, SOURCES).passed
    unknown = Narrative(paragraphs=[edu("Reg T sets the rules [S3].", "S3"), notice()])
    c = cc.check_citations(unknown, SOURCES)
    assert not c.passed and "S3" in c.detail
    uncited = Narrative(paragraphs=[edu("Reg T sets the rules."), notice()])
    c = cc.check_citations(uncited, SOURCES)
    assert not c.passed and "without a citation" in c.detail and c.locations == ["paragraph 1"]


# --------------------------------------------------------------------- 3 education-only
def test_check_education_only_rejects_run_data_in_education() -> None:
    tickers = ["COST", "NKE"]
    for text in (
        "A put on CSP-COST-2026-12-18-850P obliges the writer [S1].",
        "COST passed the gate because of its membership model [S1].",
        "The collateral of 85000 is reserved for the position [S1].",
    ):
        c = cc.check_education_only(Narrative(paragraphs=[edu(text, "S1")]), PAYLOAD, tickers)
        assert not c.passed, text
    fine = cc.check_education_only(
        Narrative(
            paragraphs=[
                edu("The requirement is 20% of the stock price or 10% of the strike [S1].", "S1")
            ]
        ),
        PAYLOAD,
        tickers,
    )
    assert fine.passed  # percentages and source numbers are allowed


def test_check_education_only_requires_realistic_loss_for_short_options() -> None:
    missing = res("CSP-COST-2026-12-18-850P: strike 850 expiring 2026-12-18 for 1250.")
    c = cc.check_education_only(Narrative(paragraphs=[missing]), PAYLOAD, [])
    assert not c.passed and "realistic loss" in c.detail
    by_phrase = res("CSP-COST-2026-12-18-850P: strike 850, realistic loss 12345.")
    by_number = res("CSP-COST-2026-12-18-850P: strike 850; a 30% fall costs 12345.")
    long_leg = res("LEAPS-NKE-2028-12-15-20C: 1 contract for 1808.")  # not a short option
    for p in (by_phrase, by_number, long_leg):
        assert cc.check_education_only(Narrative(paragraphs=[p]), PAYLOAD, []).passed, p.text


# ------------------------------------------------------------------------ 4 suitability
@pytest.mark.parametrize(
    ("over", "text", "code"),
    [
        ({}, "x", None),
        ({"account_type": "cash", "margin_used": 10.0}, "x", "margin_on_cash"),
        ({"max_position_loss_pct": 0.031}, "x", "loss_over_limit"),
        ({"position_count": 9}, "x", "too_many_positions"),
        (
            {
                "strategies_requested": ["csp"],
                "strategies_present": ["csp", "pmcc"],
                "pmcc_present": True,
                "leaps_requested": False,
            },
            "x",
            "pmcc_without_leaps",
        ),
        (
            {"buying_power": 2000.0, "strategies_present": ["csp"]},
            "x",
            "buying_power_below_minimum",
        ),
        ({"buying_power": 1500.0, "strategies_present": ["leaps"]}, "x", None),
        (
            {
                "risk_profile": "conservative",
                "loss_limit_pct": 0.02,
                "max_position_loss_pct": 0.01,
                "earnings_flagged": ["CSP-COST-2026-12-18-850P"],
            },
            "CSP-COST-2026-12-18-850P met the criteria.",
            "earnings_unflagged_conservative",
        ),
        (
            {
                "risk_profile": "conservative",
                "loss_limit_pct": 0.02,
                "max_position_loss_pct": 0.01,
                "earnings_flagged": ["CSP-COST-2026-12-18-850P"],
            },
            "CSP-COST-2026-12-18-850P met the criteria and has earnings before expiry.",
            None,
        ),
        (
            {"earnings_flagged": ["CSP-COST-2026-12-18-850P"]},
            "CSP-COST-2026-12-18-850P met the criteria.",
            None,
        ),
        ({"account_type": "cash", "margin_used": 0.0}, "This naked put…", "naked_language_on_cash"),
        ({}, "This naked put…", None),
        (
            {"risk_profile": "conservative", "loss_limit_pct": 0.02, "max_position_loss_pct": 0.01},
            "Margin leverage is an opportunity to boost yield.",
            "leverage_as_opportunity",
        ),
    ],
)
def test_suitability_matrix(
    ccfg: ComplianceConfig, over: dict[str, object], text: str, code: str | None
) -> None:
    codes = [c for c, _ in cc.suitability_problems(facts(**over), text, ccfg)]
    assert codes == ([] if code is None else [code]), codes
    check = cc.check_suitability(facts(**over), text, ccfg)
    assert check.passed is (code is None)
    assert cc.check_suitability(None, text, ccfg).passed  # concept answers carry no facts


# --------------------------------------------------------------------------- 5 language
def test_check_language_catches_every_category(ccfg: ComplianceConfig) -> None:
    samples = {
        "certainty": "This is guaranteed income.",
        "directive": "You should sell the 95 put here.",
        "directive-imperative": "Buy the COST put before Friday.",
        "superlative": "A no-brainer at this premium.",
        "urgency": "Don't miss this one.",
    }
    for label, text in samples.items():
        c = cc.check_language(Narrative(paragraphs=[res(text)]), ccfg)
        assert not c.passed, label
    clean = Narrative(
        paragraphs=[
            res(
                "CSP-COST-2026-12-18-850P met the criteria; the writer sells a put and may be assigned."
            ),
            edu(
                "The obligation to buy 100 shares per contract at the strike is what the collateral secures [S1].",
                "S1",
            ),
        ]
    )
    assert cc.check_language(clean, ccfg).passed


def test_allow_list_only_inside_cited_education(ccfg: ComplianceConfig) -> None:
    text = "Sell-to-open is the term for the order a put writer places; sell the put is how brokers label it [S1]."
    cited = Narrative(paragraphs=[edu(text, "S1")])
    assert cc.check_language(cited, ccfg).passed
    uncited = Narrative(paragraphs=[Paragraph(mode="education", text=text.replace(" [S1]", ""))])
    assert not cc.check_language(uncited, ccfg).passed
    as_result = Narrative(paragraphs=[res(text)])
    assert not cc.check_language(as_result, ccfg).passed
    quoted = Narrative(
        paragraphs=[edu('The phrase "buy the call" describes the long leg [S1].', "S1")]
    )
    assert cc.check_language(quoted, ccfg).passed
    rate = Narrative(paragraphs=[edu("d1 uses the risk-free rate r [S1].", "S1")])
    assert cc.check_language(rate, ccfg).passed


def test_concept_docs_pass_the_language_check_as_cited_education(
    ccfg: ComplianceConfig, config: AppConfig
) -> None:
    """The knowledge base is quoted into education paragraphs; none of it may read as advice."""
    from options_scout.rag.corpus import load_corpus

    for doc in load_corpus(config.rag.knowledge_dir, kinds=("concepts",)):
        paragraphs = [edu(t, "S1") for t in doc.body.split("\n\n") if t.strip()]
        c = cc.check_language(Narrative(paragraphs=paragraphs), ccfg)
        assert c.passed, (doc.id, c.detail)


# ------------------------------------------------------------------------- 6 disclaimer
def test_check_disclaimer_once_reminder_and_delayed(ccfg: ComplianceConfig) -> None:
    ok = Narrative(paragraphs=[res("Screen done."), notice("Market data is delayed."), notice()])
    assert cc.check_disclaimer(
        ok, disclaimer=DISC, cfg=ccfg, text_kind="report", delayed_data=True
    ).passed
    twice = Narrative(paragraphs=[notice(), notice("Market data is delayed."), notice()])
    c = cc.check_disclaimer(twice, disclaimer=DISC, cfg=ccfg, text_kind="report", delayed_data=True)
    assert not c.passed and "2 time(s)" in c.detail
    no_delay = Narrative(paragraphs=[res("Screen done."), notice()])
    assert not cc.check_disclaimer(
        no_delay, disclaimer=DISC, cfg=ccfg, text_kind="report", delayed_data=True
    ).passed
    assert cc.check_disclaimer(
        no_delay, disclaimer=DISC, cfg=ccfg, text_kind="answer", delayed_data=True
    ).passed
    names_option = Narrative(
        paragraphs=[notice(), res("CSP-COST-2026-12-18-850P was screened in.")]
    )
    c = cc.check_disclaimer(
        names_option, disclaimer=DISC, cfg=ccfg, text_kind="answer", delayed_data=False
    )
    assert not c.passed and "reminder" in c.detail
    closes = Narrative(
        paragraphs=[
            res("CSP-COST-2026-12-18-850P was screened in."),
            notice(f"{ccfg.reminder} {DISC}"),
        ]
    )
    assert cc.check_disclaimer(
        closes, disclaimer=DISC, cfg=ccfg, text_kind="answer", delayed_data=False
    ).passed


# ---------------------------------------------------------------------- 7 sources fresh
def test_check_sources_fresh_warns_only(ccfg: ComplianceConfig) -> None:
    today = date(2026, 11, 3)
    fresh = cc.check_sources_fresh(SOURCES, ccfg, today)
    assert fresh.passed and fresh.severity == "warn"
    old = SOURCES[0].model_copy(update={"as_of": date(2024, 1, 1), "kind": "filings"})
    stale = cc.check_sources_fresh([old], ccfg, today)
    assert not stale.passed and "out of date" in stale.detail and stale.locations == ["S1"]
    concept_old = old.model_copy(update={"kind": "concepts"})
    assert cc.check_sources_fresh([concept_old], ccfg, today).passed  # concepts do not age


# ----------------------------------------------------------------------------- 8 no PII
def test_check_no_pii() -> None:
    assert (
        cc.check_no_pii(Narrative(paragraphs=[res("Posts in r/Costco mention the deal.")])).passed
        is False
    )
    for text in ("as @hoka_runner said", "contact me at a.b@example.com", "see u/throwaway123"):
        assert not cc.check_no_pii(Narrative(paragraphs=[res(text)])).passed, text
    assert cc.check_no_pii(
        Narrative(paragraphs=[res("Reddit posts about Kirkland olive oil.")])
    ).passed


# ------------------------------------------------------------------------------ outcome
def test_run_compliance_report_and_feedback(ccfg: ComplianceConfig) -> None:
    narrative = Narrative(
        paragraphs=[
            res("CSP-COST-2026-12-18-850P met the criteria with a realistic loss of 12345."),
            edu(
                "Regulation T is the Federal Reserve Board rule; the minimum is 20% of the stock price or 10% of the strike [S1].",
                "S1",
            ),
            notice("Market data is delayed and Greeks are model-derived."),
            notice(),
        ]
    )
    rep = cc.run_compliance(
        narrative,
        payload=PAYLOAD,
        sources=SOURCES,
        facts=facts(),
        cfg=ccfg,
        disclaimer=DISC,
        run_tickers=["COST"],
        today=date(2026, 11, 3),
    )
    assert rep.passed and [c.name for c in rep.checks] == [
        "check_numbers",
        "check_citations",
        "check_education_only",
        "check_suitability",
        "check_language",
        "check_disclaimer",
        "check_sources_fresh",
        "check_no_pii",
    ]
    assert rep.retry_feedback == "" and len(rep.audit_id) == 10 and rep.text_kind == "report"
    assert isinstance(rep.verification, VerificationResult) and rep.verification.passed
    bad = Narrative(
        paragraphs=[res("You should buy CSP-COST-2026-12-18-850P, it will profit 23.7%."), notice()]
    )
    rep = cc.run_compliance(
        bad, payload=PAYLOAD, sources=SOURCES, facts=facts(), cfg=ccfg, disclaimer=DISC, attempts=2
    )
    assert not rep.passed and rep.attempts == 2
    names = [c.name for c in rep.failed_checks]
    assert {"check_numbers", "check_education_only", "check_language", "check_disclaimer"} <= set(
        names
    )
    assert "check_language:" in rep.retry_feedback and "23.7%" in rep.retry_feedback
    assert not rep.verification.passed  # kept consistent with the full set of checks
