"""Mutation-testing gaps in ``core/compliance.py``: exact outputs of every check, so a check that
stops firing, fires on the wrong input or garbles the text fed back to the writer is caught."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from options_scout.config import AppConfig, ComplianceConfig
from options_scout.core import compliance as cc
from options_scout.core.models import (
    BOTTLENECK_BOARD_DOC_ID,
    Citation,
    ComplianceCheck,
    ComplianceReport,
    Narrative,
    Paragraph,
    VerificationResult,
)
from tests.unit.test_compliance import DISC, edu, facts, notice, res

CSP = "CSP-COST-2026-12-18-850P"
PMCC = "PMCC-AAPL-2027-01-15-150C-2026-12-18-200C"


@pytest.fixture
def ccfg(config: AppConfig) -> ComplianceConfig:
    return config.compliance


def cite(n: int = 1, **over: Any) -> Citation:
    base: dict[str, Any] = {
        "chunk_id": f"doc{n}#0",
        "doc_id": f"doc{n}",
        "title": f"Doc {n}",
        "url": "https://example.org/",
        "quote": f"quote {n}",
        "kind": "concepts",
    }
    return Citation.model_validate({**base, **over})


def _vr(**over: Any) -> VerificationResult:
    base: dict[str, Any] = {
        "passed": True,
        "numbers_checked": 3,
        "ungrounded_numbers": [],
        "banned_phrases_found": [],
        "disclaimer_present": True,
        "cited_candidate_ids": [],
        "attempts": 1,
    }
    return VerificationResult.model_validate({**base, **over})


# ------------------------------------------------------------------------------- numbers
@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("−5", (-5.0, False)),
        ("$5", (5.0, False)),
        ("1,250", (1250.0, False)),
        ("-$ 5", (-5.0, False)),
        ("12%", (12.0, True)),
        ("-$1,234.5%", (-1234.5, True)),
    ],
)
def test_to_float_parses_display_forms(token: str, expected: tuple[float, bool]) -> None:
    assert cc._to_float(token) == expected


def test_collect_payload_numbers_exact_variants() -> None:
    assert cc.collect_payload_numbers(1234.567891) == {
        1234.567891,
        1235.0,
        1234.6,
        1234.57,
        1234.568,
        1234.5679,
    }
    # fractions up to 1.5 also appear as percents at 2, 1 and 0 decimals
    assert cc.collect_payload_numbers(0.123456) == {
        0.123456,
        0.0,
        0.1,
        0.12,
        0.123,
        0.1235,
        12.35,
        12.3,
        12.0,
    }
    assert cc.collect_payload_numbers(1.5) == {1.5, 2.0, 150.0}
    assert cc.collect_payload_numbers(2.0) == {2.0}
    assert cc.collect_payload_numbers("price -42") == {-42.0, 42.0}


@pytest.mark.parametrize(
    "text",
    [
        "`run-7`$5",
        f"{PMCC}$5",
        "[S1]$5",
        f"{CSP}$5",
        "2026-11-10$5",
        "the 3rd$5",
        "__$5__",
    ],
)
def test_extract_numbers_scrubbed_spans_leave_a_single_space(text: str) -> None:
    assert cc.extract_narrative_numbers(text) == [("$5", 5.0, False)]


def test_extract_numbers_bold_underscores_and_years() -> None:
    assert cc.extract_narrative_numbers("__5__") == [("5", 5.0, False)]
    assert cc.extract_narrative_numbers("$2,000 of cash") == [("$2,000", 2000.0, False)]
    assert cc.extract_narrative_numbers("in $2026") == []
    assert cc.extract_narrative_numbers("since 1990") == []
    assert cc.extract_narrative_numbers("since 1989") == [("1989", 1989.0, False)]
    assert cc.extract_narrative_numbers("In 2026 the premium was $5") == [("$5", 5.0, False)]


def test_matches_tolerances() -> None:
    assert cc._matches(5.0, [5.0], 0.0)
    assert cc._matches(100.5, [100.0], 0.01)  # relative tolerance
    assert cc._matches(0.005, [0.0], 0.01)  # absolute tolerance near zero
    assert not cc._matches(0.5, [0.0], 0.01)


# --------------------------------------------------------------------- verbatim quotes (W13)
EVIDENCE = {
    "kind": "evidence",
    "text": "Shares   jumped 37% after\nthe earnings call",
}
QUOTE_PAYLOAD: dict[str, Any] = {
    "sources": [EVIDENCE, {"kind": "concepts", "text": "the 42 rule says so"}],
}


def _ungrounded(narrative: str, payload: dict[str, Any] = QUOTE_PAYLOAD) -> list[str]:
    return cc.verify_narrative(narrative, payload, disclaimer=DISC).ungrounded_numbers


@pytest.mark.parametrize(
    "quote",
    [
        "“Shares jumped 37% after the earnings call”",
        '"Shares jumped 37% after the earnings call"',
        "“Shares jumped 37% after the…”",
        '"Shares jumped 37% after."',
    ],
)
def test_a_verbatim_evidence_quote_is_not_a_claim(quote: str) -> None:
    r = cc.verify_narrative(f"The post said {quote}. {DISC}", QUOTE_PAYLOAD, disclaimer=DISC)
    assert r.ungrounded_numbers == [] and r.numbers_checked == 0


def test_evidence_numbers_do_not_ground_claims_outside_a_quote() -> None:
    assert _ungrounded(f"Shares rose 37%. {DISC}") == ["37%"]
    assert _ungrounded(f"The 42 rule. {DISC}") == []  # knowledge-base text keeps its numbers
    # an altered quote stays in and is checked
    assert _ungrounded(f"It said “Shares jumped 73% after the earnings call”. {DISC}") == ["73%"]
    assert _ungrounded(f'It said "Shares jumped 73% after the earnings call". {DISC}') == ["73%"]
    # the blanked quote leaves a single space behind
    assert _ungrounded(f"It said “Shares jumped 37% after the earnings call”$5. {DISC}") == ["$5"]


def test_quoting_a_knowledge_base_source_is_still_checked() -> None:
    r = cc.verify_narrative(
        f"It says “the 42 rule says so”. {DISC}", QUOTE_PAYLOAD, disclaimer=DISC
    )
    assert r.numbers_checked == 1 and r.ungrounded_numbers == []


def test_verbatim_quote_minimum_length_is_twelve_characters() -> None:
    payload = {"sources": [{"kind": "evidence", "text": "Volume was up 5% on TSX"}]}
    assert _ungrounded(f"A post said “up 5% on TSX”. {DISC}", payload) == []  # 12 characters
    assert _ungrounded(f"A post said “up 5% on TS”. {DISC}", payload) == ["5%"]  # 11


def test_evidence_source_without_text_or_a_non_dict_source() -> None:
    payload: dict[str, Any] = {"sources": [{"kind": "evidence"}, "S2 raw"]}
    assert _ungrounded(f"It said “Shares jumped 37% today”. {DISC}", payload) == ["37%"]


# ------------------------------------------------------------------------- verify_narrative
def test_verify_narrative_signed_and_percent_candidates() -> None:
    payload = {"x": 5, "f": 2.5}
    assert _ungrounded(f"It fell -5. {DISC}", payload) == []
    assert _ungrounded(f"Up 250%. {DISC}", payload) == []
    assert _ungrounded(f"Down -250%. {DISC}", payload) == []
    r = cc.verify_narrative(f"Up 250%. Down -250%. {DISC}", payload, disclaimer=DISC, rel_tol=0.001)
    assert r.ungrounded_numbers == []
    r = cc.verify_narrative(f"Up 249%. {DISC}", payload, disclaimer=DISC, rel_tol=0.001)
    assert r.ungrounded_numbers == ["249%"]


def test_verify_narrative_result_fields() -> None:
    payload = {"sources": [{"kind": "concepts"}, {"kind": "concepts"}], "x": 1}
    text = f"This is Guaranteed [S2] [S2]. {CSP} {PMCC} {DISC}"
    r = cc.verify_narrative(text, payload, disclaimer=DISC)
    assert r.attempts == 1
    assert r.banned_phrases_found == ["guarantee", "guaranteed"]
    assert r.unknown_citations == [] and r.citations_checked == 2
    assert r.cited_candidate_ids == [CSP, "PMCC-AAPL-2027-01-15-150C", PMCC]
    assert not r.passed
    r = cc.verify_narrative(f"Fine [S2]. {DISC}", payload, disclaimer=DISC, source_count=1)
    assert r.unknown_citations == ["S2"] and not r.passed


@pytest.mark.parametrize(
    ("text", "passed"),
    [
        (f"Plain text. {DISC}", True),
        ("Plain text.", False),  # disclaimer missing only
        (f"A sure thing. {DISC}", False),  # banned only
        (f"Up 99. {DISC}", False),  # ungrounded only
        (f"Plain [S9]. {DISC}", False),  # unknown tag only
    ],
)
def test_verify_narrative_each_failure_alone_fails(text: str, passed: bool) -> None:
    assert cc.verify_narrative(text, {}, disclaimer=DISC).passed is passed


def test_disclaimer_prefix_is_sixty_normalised_characters() -> None:
    disc = "abcdefghij" * 7
    assert cc.verify_narrative(disc[:60] + "Z", {}, disclaimer=disc).disclaimer_present
    assert cc.verify_narrative("x " + DISC.replace(" ", "\n", 3), {}, disclaimer=DISC).passed
    letters = " ".join("abcdefghijklmnopqrstuvwxyzabcdefgh")
    assert not cc.verify_narrative(letters[:30], {}, disclaimer=letters).disclaimer_present


# ----------------------------------------------------------------------- 1 check_numbers
def test_check_numbers_detail() -> None:
    assert cc.check_numbers(_vr()).detail == "3 numbers checked, all grounded"
    bad = cc.check_numbers(_vr(ungrounded_numbers=["23.7%", "99"]))
    assert bad.detail == "3 numbers checked, not in payload: 23.7%, 99"


# --------------------------------------------------------------------- 2 check_citations
def test_resolve_citations_numbers_from_s1_in_source_order() -> None:
    sources = [cite(1), cite(2), cite(3)]
    n = Narrative(paragraphs=[edu("See [S3].", "S1")])
    got = cc.resolve_citations(n, sources)
    assert [(c.doc_id, c.tag) for c in got] == [("doc1", "S1"), ("doc3", "S3")]


def test_check_citations_detail_and_locations() -> None:
    sources = [cite(1)]
    declared = Narrative(paragraphs=[edu("No inline tag.", "S5")])
    c = cc.check_citations(declared, sources)
    assert not c.passed and c.locations == ["S5"]
    two = Narrative(paragraphs=[edu("See [S4] and [S3].", "S1")])
    c = cc.check_citations(two, sources)
    assert c.detail == "tags not in sources: S3, S4" and c.locations == ["S3", "S4"]
    empty = Narrative(paragraphs=[edu("See [S1]."), edu("Uncited.")])
    c = cc.check_citations(empty, [cite(1, quote="  ")])
    assert c.detail == "paragraph 2: education paragraph without a citation; S1: empty quote"
    assert c.locations == ["paragraph 2", "S1"]


# ---------------------------------------------------------------- 3 check_education_only
EDU_PAYLOAD: dict[str, Any] = {
    "positions": [{"candidate_id": CSP, "realistic_loss": 12345, "contracts": 1000}],
    "portfolio": {"capital_used": 85000},
}


def _edu_check(text: str, tickers: list[str] | None = None, **kw: Any) -> ComplianceCheck:
    n = Narrative(paragraphs=[edu(text, "S1")])
    return cc.check_education_only(n, EDU_PAYLOAD, tickers or [], **kw)


def test_education_only_run_data() -> None:
    assert not _edu_check("A contract of 1000 shares [S1].").passed  # 1000 is a run number
    assert _edu_check("A contract of 980 shares [S1].").passed
    c = _edu_check("GE is an industrial [S1].", ["GE"])
    assert c.detail == "paragraph 1: run ticker GE in education paragraph"
    assert _edu_check("A put obliges the writer [S1].", ["A"]).passed
    assert _edu_check("Words only [S1].", []).passed
    c = _edu_check(f"A put on {CSP} obliges the writer [S1].")
    assert c.detail == f"paragraph 1: candidate id in education paragraph ({CSP})"
    c = _edu_check("A 25% drop of 85000 [S1].")
    assert c.detail == "paragraph 1: run number 85000 in education paragraph"
    assert c.locations == ["paragraph 1"]
    assert _edu_check("About 85,500 [S1].", rel_tol=0.001).passed


@pytest.mark.parametrize("phrase", ["Realistic Loss", "Loss At", "Modelled Loss"])
def test_short_option_loss_phrases(phrase: str) -> None:
    n = Narrative(paragraphs=[res(f"{CSP} passed; {phrase} shown in the table.")])
    assert cc.check_education_only(n, EDU_PAYLOAD, []).passed


def test_education_only_detail_join_and_pass_text() -> None:
    n = Narrative(paragraphs=[edu(f"{CSP} [S1]."), res(f"{CSP} passed.")])
    c = cc.check_education_only(n, EDU_PAYLOAD, [])
    assert c.detail == (
        f"paragraph 1: candidate id in education paragraph ({CSP}); "
        f"paragraph 2: short option {CSP} described without its realistic loss"
    )
    assert c.locations == ["paragraph 1", "paragraph 2"]
    ok = cc.check_education_only(Narrative(paragraphs=[notice()]), EDU_PAYLOAD, [])
    assert ok.detail == "education paragraphs carry no run data; short options show their loss"


# --------------------------------------------------------------------- 4 check_suitability
def _report(*checks: ComplianceCheck) -> ComplianceReport:
    return ComplianceReport(
        passed=False, checks=list(checks), audit_id="a", verification=_vr(passed=False)
    )


def test_fact_suitability_codes_only_from_failed_suitability_checks() -> None:
    other = ComplianceCheck(name="check_citations", passed=False, locations=["margin_on_cash"])
    s1 = ComplianceCheck(name="check_suitability", passed=False, locations=["loss_over_limit"])
    s2 = ComplianceCheck(
        name="check_suitability", passed=False, locations=["too_many_positions", "x"]
    )
    assert cc.fact_suitability_codes(_report(other, s1, s2)) == [
        "loss_over_limit",
        "too_many_positions",
    ]


SUIT_DETAILS: list[tuple[dict[str, Any], str, str]] = [
    (
        {"account_type": "cash", "margin_used": 0.5},
        "x",
        "margin_on_cash: margin $0 used in a cash account",
    ),
    (
        {"strategies_present": ["csp"], "pmcc_present": True, "leaps_requested": False},
        "x",
        "pmcc_without_leaps: a PMCC is described but LEAPS were not requested",
    ),
    (
        {
            "risk_profile": "conservative",
            "loss_limit_pct": 0.02,
            "max_position_loss_pct": 0.01,
            "earnings_flagged": [CSP],
        },
        f"{CSP} met the criteria.",
        f"earnings_unflagged_conservative: {CSP} has earnings before expiry but the text does "
        "not say so in the same sentence",
    ),
    (
        {"earnings_unknown_ids": [CSP]},
        f"{CSP} met the criteria.",
        f"earnings_unknown_unflagged: {CSP} has no confirmed earnings date but the text does not "
        "say so in the same sentence",
    ),
    (
        {
            "risk_profile": "conservative",
            "loss_limit_pct": 0.02,
            "max_position_loss_pct": 0.01,
            "bottleneck_easing_flagged": [CSP],
        },
        f"{CSP} met the criteria.",
        f"bottleneck_easing_unflagged_conservative: {CSP} carries the bottleneck_easing flag "
        "(new supply or decelerating prices in its layer) but the text does not say so in the "
        "same sentence",
    ),
    (
        {"account_too_small": True},
        "Nothing was sized.",
        "account_too_small_unstated: nothing was sized because the account is too small for the "
        "top-ranked underlyings, but the text does not say the account is too small",
    ),
    (
        {"single_ticker": "COST"},
        "All on COST.",
        "single_name_unstated: every sized position is on COST but no sentence names it as a "
        "one-stock (single-name) portfolio",
    ),
    (
        {"ranking_not_followed": True},
        "Sized.",
        "ranking_not_followed_unstated: higher-ranked underlyings did not fit this account size "
        "and the text does not say they did not fit",
    ),
    (
        {"account_type": "cash", "margin_used": 0.0},
        "A naked put.",
        "naked_language_on_cash: naked-put language for a cash account",
    ),
    (
        {"risk_profile": "conservative", "loss_limit_pct": 0.02, "max_position_loss_pct": 0.01},
        "Margin leverage is an opportunity.",
        "leverage_as_opportunity: margin leverage described as an opportunity for a "
        "conservative profile",
    ),
]


@pytest.mark.parametrize(("over", "text", "detail"), SUIT_DETAILS)
def test_suitability_detail_text(
    ccfg: ComplianceConfig, over: dict[str, Any], text: str, detail: str
) -> None:
    c = cc.check_suitability(facts(**over), text, ccfg)
    assert not c.passed and c.detail == detail and c.locations == [detail.split(":")[0]]


def test_suitability_boundaries(ccfg: ComplianceConfig) -> None:
    def codes(**over: Any) -> list[str]:
        return [c for c, _ in cc.suitability_problems(facts(**over), "x", ccfg)]

    assert codes(max_position_loss_pct=0.03, loss_limit_pct=0.03) == []
    assert codes(max_position_loss_pct=0.03 + 1e-9, loss_limit_pct=0.03) == []
    assert codes(position_count=8, max_positions=8) == []
    assert codes(buying_power=2500.0, strategies_present=["csp"]) == []
    too_small = cc.suitability_problems(facts(account_too_small=True), "Too small.", ccfg)
    assert too_small == []


def test_check_suitability_details_and_join(ccfg: ComplianceConfig) -> None:
    none = cc.check_suitability(None, "x", ccfg)
    assert none.name == "check_suitability"
    assert none.detail == "no screen in this text (concept answer)"
    ok = cc.check_suitability(facts(), "x", ccfg)
    assert ok.detail == "suits the profile" and ok.locations == []
    two = cc.check_suitability(facts(position_count=9, ranking_not_followed=True), "x", ccfg)
    assert two.detail.startswith("too_many_positions: 9 positions > max 8; ranking_not_followed")
    assert two.locations == ["too_many_positions", "ranking_not_followed_unstated"]


# ------------------------------------------------------------------------ 5 check_language
def test_language_scrub_keeps_single_spaces(ccfg: ComplianceConfig) -> None:
    quoted = Narrative(paragraphs=[edu('Traders buy the "protective" puts [S1].', "S1")])
    assert cc.check_language(quoted, ccfg).passed
    allowed = Narrative(paragraphs=[edu("Some buy the risk-free rate calls [S1].", "S1")])
    assert cc.check_language(allowed, ccfg).passed
    upper = Narrative(paragraphs=[edu("The Risk-Free Rate is a benchmark [S1].", "S1")])
    assert cc.check_language(upper, ccfg).passed


def test_check_language_detail(ccfg: ComplianceConfig) -> None:
    n = Narrative(paragraphs=[res("This is guaranteed."), res("You should look.")])
    c = cc.check_language(n, ccfg)
    assert c.detail == (
        "paragraph 1: certainty ('guaranteed'); paragraph 2: directive ('You should')"
    )
    assert c.locations == ["paragraph 1", "paragraph 2"]
    ok = cc.check_language(Narrative(paragraphs=[res("Calm.")]), ccfg)
    assert ok.detail == "no directive, certainty, superlative or urgency language"


# ---------------------------------------------------------------------- 6 check_disclaimer
def _disc(
    paragraphs: list[Paragraph],
    ccfg: ComplianceConfig,
    kind: str = "answer",
    disclaimer: str = DISC,
    delayed: bool = False,
) -> ComplianceCheck:
    return cc.check_disclaimer(
        Narrative(paragraphs=paragraphs),
        disclaimer=disclaimer,
        cfg=ccfg,
        text_kind=kind,  # type: ignore[arg-type]
        delayed_data=delayed,
    )


def test_check_disclaimer_reminder_rules(ccfg: ComplianceConfig) -> None:
    rem = ccfg.reminder
    assert _disc([notice(), res("No option named.")], ccfg).passed
    assert _disc([notice(), res(f"{CSP} passed.")], ccfg, kind="report").passed
    assert _disc([notice(), res(f"{CSP} passed."), res(rem)], ccfg).passed
    c = _disc([res(f"{CSP} passed."), res(rem), notice(), res("Bye.")], ccfg)
    assert c.detail == "reply names an option but does not close with the reminder"
    disc = "abcdefghij" * 7
    trunc = disc[:60] + "Z"
    assert _disc([res(f"{CSP} passed."), res(trunc)], ccfg, disclaimer=disc).passed


def test_check_disclaimer_counts_and_details(ccfg: ComplianceConfig) -> None:
    disc = "abcdefghij" * 7
    assert _disc([res("x"), res(disc[:60] + "Z")], ccfg, disclaimer=disc).passed
    ok = _disc([res("x"), notice()], ccfg)
    assert ok.detail == "disclaimer present once"
    twice = _disc([notice(), notice()], ccfg, kind="report", delayed=True)
    assert twice.detail == (
        "disclaimer appears 2 time(s), expected exactly once; "
        "no statement that market data is delayed"
    )
    joined = _disc([res("Data is dela" + DISC + "yed.")], ccfg, kind="report", delayed=True)
    assert joined.passed


# ------------------------------------------------------------------- 7 check_sources_fresh
def test_check_sources_fresh_boundaries_and_details(ccfg: ComplianceConfig) -> None:
    today = date(2026, 11, 10)
    old = today - timedelta(days=ccfg.max_age_days + 1)
    edge = today - timedelta(days=ccfg.max_age_days)
    board_edge = today - timedelta(days=ccfg.max_snapshot_age_days)
    board_old = today - timedelta(days=ccfg.max_snapshot_age_days + 1)
    cits = [
        cite(1, kind="rules", tag="S1"),  # no date: skipped, the loop goes on
        cite(2, kind="rules", tag="S2", as_of=old),
        cite(3, kind="filings", tag="S3", as_of=old),
        cite(4, kind="rules", tag="S4", as_of=edge),
        cite(5, kind="evidence", doc_id=BOTTLENECK_BOARD_DOC_ID, tag="S5", as_of=board_edge),
        cite(6, kind="evidence", doc_id=BOTTLENECK_BOARD_DOC_ID, tag="S6", as_of=board_old),
        cite(7, kind="evidence", doc_id=BOTTLENECK_BOARD_DOC_ID, tag="S7", as_of=board_old),
    ]
    c = cc.check_sources_fresh(cits, ccfg, today)
    assert c.locations == ["S2", "S3", "S6", "S7"]
    assert c.detail == (
        f"S2, S3 older than {ccfg.max_age_days} days (source may be out of date); "
        f"S6, S7 snapshot older than {ccfg.max_snapshot_age_days} days "
        "(bottleneck snapshot may be out of date)"
    )
    fresh = cc.check_sources_fresh([cits[3]], ccfg, today)
    assert fresh.detail == "cited rules and filings are current"


# -------------------------------------------------------------------------- 8 check_no_pii
def test_check_no_pii_detail() -> None:
    c = cc.check_no_pii(Narrative(paragraphs=[res("From @trader99 and a@b.com.")]))
    assert c.detail == "handles or emails present: @trader99, a@b.com"
    assert c.locations == ["@trader99", "a@b.com"]
    ok = cc.check_no_pii(Narrative(paragraphs=[res("Nobody.")]))
    assert ok.passed and ok.detail == "no handles or emails"


# ------------------------------------------------------------------------ 9 goal narrative
GOAL_PLAN: dict[str, Any] = {
    "goal_plan": {"projection": {"base": 1000}, "fire": {"variant": "lean"}},
}
BAD_GOAL = "It Will Reach 1000 and will hit the target."
GOOD_GOAL = (
    "This fits. The stress path is lower; it would reach 1000. Lean FIRE uses a withdrawal "
    "rate from diversified portfolio research."
)


def _goal(text: str, payload: dict[str, Any], ccfg: ComplianceConfig, **kw: Any) -> ComplianceCheck:
    return cc.check_goal_narrative(Narrative(paragraphs=[res(text)]), payload, ccfg, **kw)


def test_goal_narrative_detail(ccfg: ComplianceConfig) -> None:
    c = _goal(BAD_GOAL, GOAL_PLAN, ccfg)
    assert c.detail == (
        "the verdict (fits / stretch / does not fit) is not stated; "
        "a projection is shown without naming the stress path; "
        "projected figures are promised (will hit, will reach); use 'would'; "
        "the FIRE variant (lean) is not named; "
        "the withdrawal rate is not mentioned; "
        "the reply does not source the rate to diversified-portfolio research"
    )
    ok = _goal(GOOD_GOAL, GOAL_PLAN, ccfg)
    assert ok.passed and ok.detail == "verdict stated, stress path kept, no promises"


def test_goal_narrative_applicability(ccfg: ComplianceConfig) -> None:
    skip = "no goal reply to check"
    assert _goal(BAD_GOAL, GOAL_PLAN, ccfg, text_kind="report").detail == skip
    clar = {"goal_plan": {"clarification": "what is the target?"}}
    assert _goal(BAD_GOAL, clar, ccfg).detail == skip
    no_base = {"goal_plan": {"projection": {"stress": 900}}}
    assert _goal("It fits.", no_base, ccfg).passed
    unknown = {"goal_plan": {"fire": {"variant": "turbo"}}}
    assert _goal("It fits; withdrawal per diversified research.", unknown, ccfg).passed
    no_variant = {"goal_plan": {"fire": {}}}
    assert _goal("It fits; withdrawal per diversified research.", no_variant, ccfg).passed


# ------------------------------------------------------------------------ 10 news grounding
NEWS: dict[str, Any] = {
    "news": {"headlines": [{"title": "Costco beats estimates on membership"}, {"url": "u"}]}
}


def _news(*paragraphs: Paragraph, payload: dict[str, Any] = NEWS) -> ComplianceCheck:
    return cc.check_news_grounding(Narrative(paragraphs=list(paragraphs)), payload)


def test_news_grounding_detail_and_counts() -> None:
    assert _news(res("x"), payload={}).detail == "no headlines to check"
    ok = _news(
        res('"Costco beats estimates on membership" and "COSTCO beats estimates, on membership"')
    )
    assert ok.passed and ok.detail == "2 quoted headline(s) match the fetched items"
    assert _news(res("none quoted")).detail == "0 quoted headline(s) match the fetched items"
    long_span = "a" * 120
    bad = _news(
        edu('"An education quote is skipped here" [S1]', "S1"),
        res(f'"Costco misses estimates badly" and "{long_span}"'),
    )
    assert bad.locations == ["Costco misses estimates badly", "a" * 80]
    assert (
        bad.detail
        == f"quoted text is not a fetched headline: Costco misses estimates badly; {'a' * 80}"
    )
    # a headline without a title is the empty string, not the word "None" or a placeholder
    assert not _news(res('"None.........."')).passed
    assert not _news(res('"XXXX.........."')).passed


# ---------------------------------------------------------------------------- 11 tax reply
def test_tax_reply_detail(ccfg: ComplianceConfig) -> None:
    disc = ccfg.tax.disclaimer

    def tax(text: str, payload: dict[str, Any] | None = None) -> ComplianceCheck:
        return cc.check_tax_reply(
            Narrative(paragraphs=[res(text)]), {"tax": {}} if payload is None else payload, ccfg
        )

    assert tax("x", {}).detail == "no tax reply to check"
    assert tax(f"Neutral. {disc}").detail == "tax disclaimer once, no rate, no instruction"
    rates = "Taxed at 15%. Rate of 20%. Bracket is 24%. Tax rate is 32%."
    imp = "File your return. Report the gain. Claim the loss. Deduct the fee."
    c = tax(f"{imp} {rates} {disc}")
    assert c.detail == (
        "a tax rate is stated (Taxed at 15%; Rate of 20%; Bracket is 24%); "
        "filing instruction in the imperative (File your; . Report the; . Claim the)"
    )


# -------------------------------------------------------------------------- run_compliance
def _run(narr: Narrative, ccfg: ComplianceConfig, **kw: Any) -> ComplianceReport:
    base: dict[str, Any] = {
        "payload": {"sources": []},
        "sources": [cite(1, kind="rules", tag="S1", as_of=date(2020, 1, 1))],
        "facts": None,
        "cfg": ccfg,
        "disclaimer": DISC,
        "today": date(2020, 1, 2),
        "delayed_data": False,
    }
    return cc.run_compliance(narr, **{**base, **kw})


def test_run_compliance_passes_arguments_through(ccfg: ComplianceConfig) -> None:
    narr = Narrative(paragraphs=[edu("Reg T sets it [S1].", "S1"), notice()])
    r = _run(narr, ccfg)
    assert r.passed and r.attempts == 1 and r.verification.attempts == 1
    assert r.verification.unknown_citations == []
    assert r.warnings == []  # the data clock passed as today, not the wall clock
    answer = _run(narr, ccfg, text_kind="answer", attempts=3)
    assert answer.text_kind == "answer" and answer.verification.attempts == 3


def test_run_compliance_rel_tol_facts_and_text_kind(ccfg: ComplianceConfig) -> None:
    payload = {"sources": [], "portfolio": {"capital_used": 85000}}
    narr = Narrative(paragraphs=[edu("Collateral near 85,500 [S1].", "S1"), notice()])
    r = _run(narr, ccfg, payload=payload, rel_tol=0.001)
    assert [c.name for c in r.failed_checks] == ["check_numbers"]
    loose = _run(narr, ccfg, payload=payload, rel_tol=0.01)
    assert [c.name for c in loose.failed_checks] == ["check_education_only"]
    unsuited = _run(Narrative(paragraphs=[notice()]), ccfg, facts=facts(position_count=9))
    assert [c.name for c in unsuited.failed_checks] == ["check_suitability"]
    goal = _run(Narrative(paragraphs=[res(BAD_GOAL), notice()]), ccfg, payload=GOAL_PLAN)
    assert "goal_narrative" not in [c.name for c in goal.failed_checks]  # a report, not a reply


def test_run_compliance_feedback_and_verification(ccfg: ComplianceConfig) -> None:
    narr = Narrative(paragraphs=[res("You should look at @trader99."), notice()])
    r = _run(narr, ccfg)
    assert r.retry_feedback == (
        "check_language: paragraph 1: directive ('You should'); "
        "check_no_pii: handles or emails present: @trader99"
    )
    assert r.verification.passed is False and not r.passed


# -------------------------------------------------------------------------- withheld notice
def test_withheld_narrative_exact_text() -> None:
    suit = ComplianceCheck(
        name="check_suitability", passed=False, locations=["margin_on_cash", "loss_over_limit"]
    )
    lang = ComplianceCheck(name="check_language", passed=False, locations=["paragraph 1"])
    n = cc.withheld_narrative(_report(suit, lang), "DISCLAIMER")
    assert [(p.mode, p.text) for p in n.paragraphs] == [
        (
            "notice",
            f"{cc.WITHHELD_NOTICE} Reason codes: margin_on_cash, loss_over_limit. Failed checks: "
            "check_suitability, check_language. The candidate tables and the constraint checks "
            "are computed facts and are shown; the sized positions and the explanation are not.",
        ),
        ("notice", "DISCLAIMER"),
    ]
    nothing = cc.withheld_narrative(_report(), "D")
    assert "Reason codes: . Failed checks: none." in nothing.paragraphs[0].text
    assert cc.withheld_reason_codes(_report(lang)) == ["check_language"]
