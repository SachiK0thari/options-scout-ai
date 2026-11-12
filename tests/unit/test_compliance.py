"""Phase 10 step 10.4: the eight checks of PRD section 13.1, one test per check, plus the matrix."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from options_scout.config import AppConfig, ComplianceConfig
from options_scout.core import compliance as cc
from options_scout.core.models import (
    BOTTLENECK_BOARD_DOC_ID,
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
        (  # Phase 11 (4A.8): a conservative reader is told a short put's layer is easing
            {
                "risk_profile": "conservative",
                "loss_limit_pct": 0.02,
                "max_position_loss_pct": 0.01,
                "bottleneck_easing_flagged": ["CSP-HON-2026-12-18-200P"],
            },
            "CSP-HON-2026-12-18-200P met the criteria. Its layer shows new supply arriving.",
            "bottleneck_easing_unflagged_conservative",
        ),
        (
            {
                "risk_profile": "conservative",
                "loss_limit_pct": 0.02,
                "max_position_loss_pct": 0.01,
                "bottleneck_easing_flagged": ["CSP-HON-2026-12-18-200P"],
            },
            "CSP-HON-2026-12-18-200P met the criteria, flagged bottleneck_easing (new supply in its layer).",
            None,
        ),
        (
            {"bottleneck_easing_flagged": ["CSP-HON-2026-12-18-200P"]},  # balanced: informational
            "CSP-HON-2026-12-18-200P met the criteria.",
            None,
        ),
        (  # W5: any profile must be told a sized position's earnings date is unknown
            {"earnings_unknown_ids": ["PMCC-NKE-2028-01-21-60C-2026-12-18-80C"]},
            "PMCC-NKE-2028-01-21-60C-2026-12-18-80C met the criteria.",
            "earnings_unknown_unflagged",
        ),
        (
            {"earnings_unknown_ids": ["PMCC-NKE-2028-01-21-60C-2026-12-18-80C"]},
            "PMCC-NKE-2028-01-21-60C-2026-12-18-80C met the criteria. The earnings date for "
            "PMCC-NKE-2028-01-21-60C-2026-12-18-80C is unknown and could fall before expiry.",
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


def test_allow_terms_only_inside_cited_education(ccfg: ComplianceConfig) -> None:
    """W15 step 3: only exact glossary terms are exempt, and only in cited education."""
    text = "Buy the call opens the long leg of the spread [S1]."
    assert cc.check_language(Narrative(paragraphs=[edu(text, "S1")]), ccfg).passed
    uncited = Paragraph(mode="education", text=text.replace(" [S1]", ""))
    assert not cc.check_language(Narrative(paragraphs=[uncited]), ccfg).passed
    assert not cc.check_language(Narrative(paragraphs=[res(text)]), ccfg).passed
    rate = Narrative(paragraphs=[edu("d1 uses the risk-free rate r [S1].", "S1")])
    assert cc.check_language(rate, ccfg).passed


@pytest.mark.parametrize(
    "text",
    [
        # any quoted span used to be scrubbed, so advice inside quotes passed
        'Writers say "you should buy now, guaranteed free money" [S1].',
        # everything after "is the term for" used to be scrubbed up to the full stop
        "Sell-to-open is the term for the order; you should buy now, it is guaranteed [S1].",
    ],
)
def test_allow_list_holes_are_closed(ccfg: ComplianceConfig, text: str) -> None:
    assert not cc.check_language(Narrative(paragraphs=[edu(text, "S1")]), ccfg).passed


@pytest.mark.parametrize(
    "text",
    [
        "You can’t lose with this one.",  # typographic apostrophe
        "Don’t miss it.",
        "I’d go with NKE.",
        "You should sell the put.",  # non-breaking space
        "You  should sell the put.",  # doubled space
        "This is guaran​teed income.",  # zero-width space
        "This is guaran­teed income.",  # soft hyphen
        "You *should* sell the put.",
        "You **should** sell the put.",
        "You <b>should</b> sell the put.",
        "Yоu shоuld sell the put.",  # Cyrillic o
        "This is guаrаnteed income.",  # Cyrillic a
        "ｙｏｕ ｓｈｏｕｌｄ sell it.",  # fullwidth letters
        "Risk‑free income.",  # non-breaking hyphen
        "Deberías vender la opción de venta de COST antes del viernes para cobrar la prima.",
        "Вам стоит продать этот пут.",
    ],
)
def test_evasions_are_caught(ccfg: ComplianceConfig, text: str) -> None:
    """W15 step 2 and 5: the text is normalised before matching; non-English text fails."""
    assert not cc.check_language(Narrative(paragraphs=[res(text)]), ccfg).passed, text


@pytest.mark.parametrize(
    "text",
    [  # the five held-out misses the audit quoted (W15)
        "Load up on COST here.",
        "The smart move here is the COST put.",
        "There is zero risk in this position.",
        "Recommendation: SELL TO OPEN the COST 850P. Rating: Buy.",
        "Pull the trigger on the COST put.",
    ],
)
def test_audit_misses_are_caught(ccfg: ComplianceConfig, text: str) -> None:
    assert not cc.check_language(Narrative(paragraphs=[res(text)]), ccfg).passed, text


def test_normalise_for_language() -> None:
    raw = "You  *should*​ <i>sell</i> “it” — аll"
    assert cc.normalise_for_language(raw) == 'You should sell "it" - all'
    assert cc.banned_phrases_in("guaran​teed") == ["guarantee", "guaranteed"]


def test_concept_docs_pass_the_language_check_as_cited_education(
    ccfg: ComplianceConfig, config: AppConfig
) -> None:
    """The knowledge base is quoted into education paragraphs; none of it may read as advice."""
    from options_scout.rag.corpus import load_corpus

    failures: list[tuple[str, str]] = []
    for doc in load_corpus(config.rag.knowledge_dir, kinds=("concepts", "basics", "tax")):
        paragraphs = [edu(t, "S1") for t in doc.body.split("\n\n") if t.strip()]
        c = cc.check_language(Narrative(paragraphs=paragraphs), ccfg)
        if not c.passed:
            failures.append((doc.id, c.detail))
    assert not failures, failures


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
        "goal_narrative",  # Phase 12 check 9; trivially passing without a goal plan
        "news_grounding",  # Phase 12 check 10; trivially passing without headlines
        "tax_reply",  # Phase 12 check 11; trivially passing without a tax reply
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


# ------------------------------------------------------- Phase 11, step 11.5: bottleneck board
def _board_citation(**over: object) -> Citation:
    base = Citation(
        chunk_id=f"{BOTTLENECK_BOARD_DOC_ID}#0",
        doc_id=BOTTLENECK_BOARD_DOC_ID,
        title="Bottleneck board (secondary signal)",
        url="",
        quote="Layer Power generation and grid equipment: layer score 79, thesis holding.",
        kind="evidence",
        tag="S2",
        as_of=date(2026, 10, 26),
    )
    return base.model_copy(update=over)


def test_check_sources_fresh_covers_the_bottleneck_snapshot(ccfg: ComplianceConfig) -> None:
    """A cited board whose snapshot is older than ``max_snapshot_age_days`` warns; the evidence
    pack ages like a filing; trend evidence posts never do."""
    today = date(2026, 10, 27)
    assert cc.check_sources_fresh([_board_citation()], ccfg, today).passed
    old = _board_citation(as_of=today - timedelta(days=ccfg.max_snapshot_age_days + 1))
    c = cc.check_sources_fresh([old], ccfg, today)
    assert not c.passed and c.severity == "warn"
    assert "bottleneck snapshot may be out of date" in c.detail and c.locations == ["S2"]
    filing = _board_citation(
        chunk_id="bottleneck-ai-datacenter-power#0",
        doc_id="bottleneck-ai-datacenter-power",
        title="Bottleneck evidence: Power generation and grid equipment",
        tag="S3",
        as_of=date(2026, 3, 1),
    )
    assert cc.check_sources_fresh([filing], ccfg, today).passed  # 240 days old, under max_age_days
    ancient = filing.model_copy(update={"as_of": date(2024, 1, 1)})
    c = cc.check_sources_fresh([ancient, old], ccfg, today)
    assert "source may be out of date" in c.detail and "bottleneck snapshot" in c.detail
    assert c.locations == ["S3", "S2"]
    trend = ancient.model_copy(
        update={"doc_id": "evidence-costco", "chunk_id": "evidence-costco#0"}
    )
    assert cc.check_sources_fresh(
        [trend], ccfg, today
    ).passed  # posts are dated context, not sources


def _golden_board_paragraphs() -> list[str]:
    from tests.conftest import REPO_ROOT

    text = (REPO_ROOT / "tests/fixtures/reports/phase9_demo_report.md").read_text(encoding="utf-8")
    start = text.index("## Bottleneck board")
    end = text.index("\n## ", start + 1)
    return [p for p in text[start:end].split("\n\n") if p.strip()]


def test_thesis_monitor_vocabulary_is_not_advice(ccfg: ComplianceConfig) -> None:
    """The allow-list was reviewed against the board's words (step 11.5): *holding*, *tripped
    since <date>*, *thesis weakening*, *easing*, *new supply* report state and match no banned
    pattern in any mode, so the rendered board passes check_language and check_no_pii as it is."""
    paragraphs = _golden_board_paragraphs()
    assert any("tripped since" in p for p in paragraphs) and any(
        "weakening" in p for p in paragraphs
    )
    as_result = Narrative(paragraphs=[res(p) for p in paragraphs])
    assert cc.check_language(as_result, ccfg).passed, cc.check_language(as_result, ccfg).detail
    assert cc.check_no_pii(as_result).passed
    as_uncited_education = Narrative(
        paragraphs=[Paragraph(mode="education", text=p) for p in paragraphs]
    )
    assert cc.check_language(as_uncited_education, ccfg).passed  # no allow-list entry needed
    # the board's own words, with the quoted filing excerpts and headlines removed (a 10-K may
    # say "average selling prices"; the monitor itself never says exit, sell or take profits)
    own_words = re.sub(r"“[^”]*”", " ", "\n".join(paragraphs)).lower()
    assert not re.search(r"\b(exit|sell|take profits|you should)\b", own_words)


def test_the_risk_free_rate_is_terminology_in_any_paragraph(ccfg: ComplianceConfig) -> None:
    """The payload hands the explainer ``risk_free_rate_pct``; naming that rate in a screen result
    is not a certainty claim, while calling a trade or income risk-free still is."""
    ok = [
        "The regime uses a risk-free rate of 4.04%.",
        "With the risk free interest rate at 4.04% the cash reserve earns T-bill yield.",
        "Risk-free rates were read from FRED.",
    ]
    for text in ok:
        assert cc.check_language(Narrative(paragraphs=[res(text)]), ccfg).passed, text
        assert cc.banned_phrases_in(text) == [], text
    bad = ["This is a risk-free trade.", "Premium is risk free income.", "Risk-free, rate or not."]
    for text in bad:
        assert not cc.check_language(Narrative(paragraphs=[res(text)]), ccfg).passed, text
        assert cc.banned_phrases_in(text), text


def test_verify_narrative_allows_the_risk_free_rate() -> None:
    v = cc.verify_narrative("The risk-free rate is 4.04%. " + DISC, PAYLOAD, disclaimer=DISC)
    assert v.banned_phrases_found == []
    v2 = cc.verify_narrative("A risk-free trade. " + DISC, PAYLOAD, disclaimer=DISC)
    assert v2.banned_phrases_found == ["risk-free"]


def test_a_skipped_candidate_is_described_with_its_per_contract_loss() -> None:
    """W11: the sizing warnings name the top-ranked candidate that did not fit; the payload now
    carries the realistic loss of one contract of it, and the check accepts that number."""
    cid = "CSP-SPY-2026-11-30-735P"
    payload = {
        **PAYLOAD,
        "skipped_candidates": [
            {
                "candidate_id": cid,
                "rank": 1,
                "reason": "max loss per position",
                "realistic_loss_per_contract": 20503,
                "fits_from_account": 640477,
            }
        ],
    }
    named = f"The top-ranked {cid} fits from an account of $640,477."
    assert not cc.check_education_only(Narrative(paragraphs=[res(named)]), payload, []).passed
    with_loss = named + " One contract has a downside of $20,503."
    assert cc.check_education_only(Narrative(paragraphs=[res(with_loss)]), payload, []).passed
    # without the payload entry there is still no number to accept
    assert not cc.check_education_only(Narrative(paragraphs=[res(with_loss)]), PAYLOAD, []).passed
