"""W14: number grounding. Each sentence the audit showed passing the old bag-of-numbers check
must now fail, and slot-filled figures are tied to the field they name."""

from __future__ import annotations

from typing import Any

import pytest

from options_scout.config import AppConfig, GroundingConfig
from options_scout.core import grounding as g
from options_scout.core.compliance import verify_narrative
from options_scout.core.models import Narrative, Paragraph

CSP = "CSP-NKE-2026-11-20-35P"
DISC = "Educational screening tool. Not investment, tax or legal advice."
PAYLOAD: dict[str, Any] = {
    "profile": {"buying_power": 100000, "account_type": "margin", "risk_profile": "balanced"},
    "allocation": {"csp_pct": 45, "csp_dollars": 45000},
    "positions": [
        {
            "candidate_id": CSP,
            "strategy": "csp",
            "expiry": "2026-11-20",
            "ticker": "NKE",
            "contracts": 3,
            "strike": 35.0,
            "mid": 0.56,
            "capital_used": 10500,
            "margin_used": 1700,
            "realistic_loss": 2443,
            "premium": 169,
            "payoff": {"breakeven": 34.44, "max_loss": 10330, "max_gain": 169},
        }
    ],
    "portfolio": {"capital_used": 10500, "margin_used": 1700, "realistic_loss": 2443},
    "risk": {
        "checks_passed": 8,
        "checks_total": 8,
        "realistic_loss_drop_pct": 30,
        "checks": [
            {"name": "margin_usage", "value": 0.017, "limit": 0.4, "passed": True},
            {"name": "portfolio_loss", "value": 0.024, "limit": 0.2, "passed": True},
        ],
        "stress": [
            {"shock": "-10%", "iv_shock": "+50%", "pnl": -1012},
            {"shock": "-30%", "iv_shock": "+50%", "pnl": -3140},
        ],
        "warnings": [
            "Only $10,500 of the $45,000 set aside is used (23%); the rest stays in cash."
        ],
    },
    "disclaimer": DISC,
    "sources": [{"tag": "S1", "kind": "concepts", "text": "Sell 30–45 DTE puts; 100 shares."}],
}


@pytest.fixture
def gcfg(config: AppConfig) -> GroundingConfig:
    return config.compliance.grounding


def _free(text: str, gcfg: GroundingConfig, payload: dict[str, Any] = PAYLOAD) -> list[str]:
    n = Narrative(paragraphs=[Paragraph(mode="screen_result", text=text)])
    return g.ground_narrative(n, payload, cfg=gcfg).problems


def _slots(text: str, gcfg: GroundingConfig, mode: str = "screen_result") -> list[str]:
    n = g.render_narrative(Narrative(paragraphs=[Paragraph(mode=mode, text=text)]), PAYLOAD)  # type: ignore[arg-type]
    return g.ground_narrative(n, PAYLOAD, cfg=gcfg).problems


# ------------------------------------------------------------ the audit's passing sentences
AUDIT_SENTENCES = {
    "swapped fields": f"For {CSP} the maximum loss on this position is 169 … the premium "
    "collected is 10330.",
    "sign ignored": "A −30% move gives +3140, a gain of 3140.",
    "unit suffixes": "The account could plausibly grow to $3M within 2 years, a 10x return.",
    "number words": "There is a ninety-nine percent chance of profit.",
    "limit read as usage": "Margin usage is 40% of the account.",
    "code span": "The realistic loss is `98765`.",
    "digits glued to letters": "The realistic loss is USD98765.",
}


@pytest.mark.parametrize("case", list(AUDIT_SENTENCES))
def test_each_audit_sentence_now_fails(case: str, gcfg: GroundingConfig) -> None:
    assert _free(AUDIT_SENTENCES[case], gcfg), case


def test_the_right_figures_pass(gcfg: GroundingConfig) -> None:
    assert (
        _free(f"For {CSP} the maximum loss is 10330 and the premium collected is 169.", gcfg) == []
    )
    assert _free("A −30% move gives -3,140, a loss of 3,140.", gcfg) == []
    assert _free("Margin usage is 1.7% of the account, under its 40% limit.", gcfg) == []
    assert _free(f"{CSP}: a realistic loss of $2,443 if the stock falls 30%.", gcfg) == []
    assert _free(f"{CSP} breaks even at 34.44.", gcfg) == []


def test_swapped_fields_are_named_in_the_problem(gcfg: GroundingConfig) -> None:
    problems = _free(AUDIT_SENTENCES["swapped fields"], gcfg)
    assert any("169 is not the maximum loss of " + CSP in p for p in problems)
    assert any("10330 is not the premium of " + CSP in p for p in problems)


def test_a_label_the_run_never_computes_fails_whatever_the_figure(gcfg: GroundingConfig) -> None:
    # 8 is in the payload (checks_passed), but no field is a probability
    assert any("probability" in p for p in _free("The chance of profit is 8%.", gcfg))


def test_the_question_and_retrieved_text_do_not_ground_a_screen_result(
    gcfg: GroundingConfig,
) -> None:
    payload = {**PAYLOAD, "question": "is 777 a good strike?"}
    assert _free("The strike is 777.", gcfg, payload) == ["777"]
    assert _free("Hold 100 shares.", gcfg) == ["100"]  # in a source, not in the run
    n = Narrative(paragraphs=[Paragraph(mode="education", text="It is 100 shares [S1].")])
    assert g.ground_narrative(n, PAYLOAD, cfg=gcfg).problems == []  # education may cite it


def test_the_old_absolute_tolerance_is_gone() -> None:
    v = verify_narrative(f"It is 0.004. {DISC}", {"x": 0.0}, disclaimer=DISC)
    assert v.ungrounded_numbers == ["0.004"]


# ------------------------------------------------------------------------------ slots
def test_render_slots_fills_and_formats() -> None:
    out = g.render_slots(
        f"{{{{positions[{CSP}].realistic_loss|money}}}}, {{{{positions[0].mid|money}}}}, "
        "{{risk.stress[-30%].pnl|money}}, {{risk.stress[-0.30].shock}}, "
        "{{risk.checks[margin_usage].value|percent}}, {{allocation.csp_pct|pct}}, "
        "{{positions|count}}, {{risk.stress[-10%].pnl|abs|money}}, {{ disclaimer }}",
        PAYLOAD,
    )
    assert out == f"$2,443, $0.56, -$3,140, -30%, 1.7%, 45%, 1, $1,012, {DISC}"


@pytest.mark.parametrize(
    "slot",
    [
        "{{positions[CSP-XYZ-2026-11-20-35P].premium}}",
        "{{positions[0].premiums}}",
        "{{positions[5].premium}}",
        "{{sources[0].text}}",  # retrieved text never supplies a figure
        "{{question}}",
        "{{positions[0].premium|round}}",
        "{{positions}}",
    ],
)
def test_render_slots_raises_on_an_unknown_or_forbidden_slot(slot: str) -> None:
    with pytest.raises(g.SlotError):
        g.render_slots(slot, PAYLOAD)


def test_slot_mode_passes_when_every_figure_is_the_right_slot(gcfg: GroundingConfig) -> None:
    at = f"positions[{CSP}]"
    text = (
        f"{CSP} uses {{{{{at}.capital_used|money}}}} with a realistic loss of "
        f"{{{{{at}.realistic_loss|money}}}} if the stock falls {{{{risk.realistic_loss_drop_pct|pct}}}}. "
        f"Its maximum loss is {{{{{at}.payoff.max_loss|money}}}}, premium {{{{{at}.premium|money}}}}. "
        "A {{risk.stress[-30%].shock}} move gives {{risk.stress[-30%].pnl|money}}, a loss of "
        "{{risk.stress[-30%].pnl|abs|money}}. Margin usage is "
        "{{risk.checks[margin_usage].value|percent}}. Screened at 30–45 DTE."
    )
    assert _slots(text, gcfg) == []


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        (f"{CSP} premium {{{{positions[{CSP}].payoff.max_loss|money}}}}.", "is not the premium"),
        ("Margin usage is {{risk.checks[margin_usage].limit|percent}}.", "is not the margin"),
        (f"{CSP} premium is 169.", "typed, not a slot"),
        ("Three positions were sized.", "typed, not a slot"),
        ("A gain of {{risk.stress[-30%].pnl|money}}.", "described as a gain"),
        ("It moved {{risk.stress[-30%].pnl|abs|money}}.", "drops the sign"),
        ("{{positions[0].premiums}}", "no field"),
    ],
)
def test_slot_mode_failures(text: str, needle: str, gcfg: GroundingConfig) -> None:
    assert any(needle in p for p in _slots(text, gcfg)), _slots(text, gcfg)


def test_slots_do_not_belong_in_education(gcfg: GroundingConfig) -> None:
    problems = _slots("A put writer holds {{positions[0].capital_used}} [S1].", gcfg, "education")
    assert any("slot in an education paragraph" in p for p in problems)
    assert _slots("A contract is 100 shares [S1].", gcfg, "education") == []


def test_a_text_edited_after_rendering_fails(gcfg: GroundingConfig) -> None:
    n = g.render_narrative(
        Narrative(
            paragraphs=[Paragraph(mode="screen_result", text="Loss {{portfolio.realistic_loss}}.")]
        ),
        PAYLOAD,
    )
    tampered = Narrative(paragraphs=[n.paragraphs[0].model_copy(update={"text": "Loss 99,999."})])
    assert any(
        "differs from its rendered template" in p
        for p in g.ground_narrative(tampered, PAYLOAD, cfg=gcfg).problems
    )


def test_render_narrative_is_idempotent() -> None:
    once = g.render_narrative(
        Narrative(paragraphs=[Paragraph(mode="notice", text="{{disclaimer}}")]), PAYLOAD
    )
    assert once.paragraphs[0].text == DISC and once.paragraphs[0].template == "{{disclaimer}}"
    assert g.render_narrative(once, PAYLOAD) == once


def test_the_model_never_sees_the_template_field() -> None:
    from options_scout.llm.client import _LLM_SCHEMAS

    wire = _LLM_SCHEMAS[Narrative].model_json_schema()["$defs"]["ParagraphDraft"]["properties"]
    public = Narrative.model_json_schema()["$defs"]["Paragraph"]["properties"]
    assert "template" not in wire and "template" in public  # the public schema stays truthful


def test_the_rule_writer_types_no_figure(config: AppConfig) -> None:
    """The deterministic writer exercises the same slot path the model does."""
    import json

    from options_scout.llm.rules import rule_explain

    payload = {
        **PAYLOAD,
        "allocation": {
            **PAYLOAD["allocation"],
            "leaps_dollars": 25000,
            "cash_dollars": 30000,
            "tilt": "none",
        },
        "regime": {"vix": 17.51, "vix_percentile": 57, "label": "normal"},
        "quality_screen": {
            "passed_count": 1,
            "drawdown_lookback_days": 90,
            "passed": [{"ticker": "NKE", "quality_score": 46}],
            "excluded": [{"ticker": "XYZ", "reasons": ["HV30 61% above the 45% limit"]}],
        },
        "trends": [{"entity": "On Cloud", "ticker": "ONON", "score": 89}],
    }
    n = g.render_narrative(rule_explain(f"<payload>\n{json.dumps(payload)}\n</payload>"), payload)
    assert all(p.template is not None for p in n.paragraphs)
    assert g.ground_narrative(n, payload, cfg=config.compliance.grounding).problems == []
    assert "$2,443" in n.markdown and "{{" not in n.markdown


def test_retry_feedback_with_braces_does_not_break_the_prompt(config: AppConfig) -> None:
    """A retry hands the problems back inside the payload; braces in it are data, not
    placeholders (the first live run of prompt 3.0.0 crashed every retry on this)."""
    from options_scout.llm.prompts import load_prompt

    prompt = load_prompt(config.paths.prompts_dir, "explain_report")
    out = prompt.render(payload='{"problems": "write {{path}}"}', sources="", audience="a")
    assert "write {{path}}" in out
    with pytest.raises(KeyError):
        prompt.render(payload="{}", sources="")  # a placeholder of the body itself is still owed


def test_a_slot_followed_by_a_typed_percent_is_a_percent(gcfg: GroundingConfig) -> None:
    text = (
        "The combined realistic loss at a {{risk.realistic_loss_drop_pct}}% drop is "
        "{{portfolio.realistic_loss|money}}."
    )
    assert _slots(text, gcfg) == []


def test_a_verbatim_quote_of_a_payload_text_may_carry_its_figures(gcfg: GroundingConfig) -> None:
    warning = PAYLOAD["risk"]["warnings"][0]
    assert _slots(f"The sizer warned: “{warning}”", gcfg) == []
    altered = warning.replace("23%", "33%")
    assert any("typed" in p for p in _slots(f"The sizer warned: “{altered}”", gcfg))


# ------------------------------------------------- 2026-11-12: method terms, list filter, repair
@pytest.mark.parametrize(
    "text",
    [
        "Historical volatility is proxied by a 30-day measure.",
        "The quality gate uses a 90-day drawdown lookback and the 90-day high.",
        "IV rank is an HV proxy where fewer than 30 IV snapshots are stored.",
        "It measures 30-day realised volatility.",
    ],
)
def test_the_names_of_fixed_measures_may_be_written_out(text: str, gcfg: GroundingConfig) -> None:
    assert _slots(text, gcfg) == []


@pytest.mark.parametrize(
    ("text", "figure"),
    [
        ("The stock sits 30 days from expiry.", "30"),
        ("A 90-day return of 12%.", "12%"),
        ("31 IV snapshots are stored.", "31"),
    ],
)
def test_other_figures_near_those_words_stay_typed(
    text: str, figure: str, gcfg: GroundingConfig
) -> None:
    assert any(repr(figure) in p for p in _slots(text, gcfg)), _slots(text, gcfg)


def test_the_method_terms_match_the_constants_in_code() -> None:
    """The allowed phrases name these constants; a change to one must change the config."""
    import inspect

    from options_scout.core.volatility import hist_vol
    from options_scout.jobs.snapshot_iv import MIN_HISTORY

    assert MIN_HISTORY == 30
    assert inspect.signature(hist_vol).parameters["window"].default == 30
    from options_scout.agent.nodes import explainer

    assert '"drawdown_lookback_days": 90' in inspect.getsource(explainer._quality_section)


FLAGGED: dict[str, Any] = {
    **PAYLOAD,
    "bottlenecks": {
        "companies": [
            {"ticker": "NVDA", "score": 81, "flags": ["bottleneck_support", "catalyst_inside_dte"]},
            {"ticker": "AMD", "score": 60, "flags": []},
        ]
    },
}


def test_the_list_filter_joins_text_items(gcfg: GroundingConfig) -> None:
    assert g.render_slots("{{bottlenecks.companies[NVDA].flags|list}}", FLAGGED) == (
        "bottleneck_support, catalyst_inside_dte"
    )
    assert g.render_slots("{{bottlenecks.companies[AMD].flags|list}}", FLAGGED) == "none"
    text = "NVDA carries {{bottlenecks.companies[NVDA].flags|list}}."
    narrative = g.render_narrative(
        Narrative(paragraphs=[Paragraph(mode="screen_result", text=text)]), FLAGGED
    )
    assert g.ground_narrative(narrative, FLAGGED, cfg=gcfg).problems == []


@pytest.mark.parametrize(
    ("slot", "needle"),
    [
        ("{{risk.stress|list}}", "list of text items"),
        ("{{bottlenecks.companies[NVDA].flags|list|count}}", "cannot be combined"),
        ("{{bottlenecks.companies[NVDA].score|list}}", "list of text items"),
        ("{{bottlenecks.companies[NVDA].flags}}", "list filter"),
    ],
)
def test_the_list_filter_refuses_what_it_cannot_join(slot: str, needle: str) -> None:
    with pytest.raises(g.SlotError, match=needle):
        g.render_slots(slot, FLAGGED)


SKIP = "CSP-AAPL-2026-11-20-230P"
WITH_SKIP: dict[str, Any] = {
    **PAYLOAD,
    "skipped_candidates": [{"candidate_id": SKIP, "rank": 1, "realistic_loss_per_contract": 6120}],
}


def _repair(text: str, mode: str = "screen_result") -> tuple[str, list[str]]:
    narrative, notes = g.add_missing_realistic_losses(
        Narrative(paragraphs=[Paragraph(mode=mode, text=text)]),  # type: ignore[arg-type]
        WITH_SKIP,
    )
    return narrative.paragraphs[0].text, notes


def test_a_short_option_without_its_loss_gets_the_slot_added(config: AppConfig) -> None:
    from options_scout.core.compliance import check_education_only

    text, notes = _repair(f"{CSP} was sized; {SKIP} did not fit.")
    assert f"Realistic loss of {CSP}: {{{{positions[{CSP}].realistic_loss|money}}}}." in text
    assert f"{{{{skipped_candidates[{SKIP}].realistic_loss_per_contract|money}}}}" in text
    assert notes == ["paragraph 1: realistic loss added (2 option(s))"]
    narrative = g.render_narrative(
        Narrative(paragraphs=[Paragraph(mode="screen_result", text=text)]), WITH_SKIP
    )
    assert "$2,443" in narrative.paragraphs[0].text and "$6,120" in narrative.paragraphs[0].text
    assert check_education_only(narrative, WITH_SKIP, ["NKE"]).passed
    assert g.ground_narrative(narrative, WITH_SKIP, cfg=config.compliance.grounding).problems == []


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        (
            f"{CSP} has a realistic loss of {{{{positions[{CSP}].realistic_loss|money}}}}.",
            "screen_result",
        ),
        (f"{CSP} could lose {{{{positions[{CSP}].realistic_loss|money}}}}.", "screen_result"),
        (f"{CSP} was sized.", "notice"),
        ("LEAPS-NKE-2027-01-15-30C was sized.", "screen_result"),
        ("CSP-XYZ-2026-11-20-10P is not in the payload.", "screen_result"),
    ],
)
def test_the_repair_leaves_other_paragraphs_alone(text: str, mode: str) -> None:
    assert _repair(text, mode) == (text, [])


def test_a_maximum_loss_at_expiry_does_not_state_the_realistic_loss() -> None:
    """The check once accepted "loss at" anywhere, so "maximum loss at expiry" passed."""
    from options_scout.core.compliance import check_education_only

    text = f"{CSP} has a maximum loss at expiry of {{{{positions[{CSP}].payoff.max_loss|money}}}}."

    def para(t: str) -> Narrative:
        return g.render_narrative(
            Narrative(paragraphs=[Paragraph(mode="screen_result", text=t)]), WITH_SKIP
        )

    assert not check_education_only(para(text), WITH_SKIP, ["NKE"]).passed
    repaired, notes = _repair(text)
    assert notes and "Realistic loss of" in repaired
    assert check_education_only(para(repaired), WITH_SKIP, ["NKE"]).passed
    modelled = f"{CSP}: the modelled loss is {{{{positions[{CSP}].realistic_loss|money}}}}."
    assert check_education_only(para(modelled), WITH_SKIP, ["NKE"]).passed


# ------------------------------------------- 2026-11-12 (2): implied pct, per-option losses
def test_a_pct_field_is_a_percent_without_the_filter(gcfg: GroundingConfig) -> None:
    assert g.render_slots("{{risk.realistic_loss_drop_pct}}", PAYLOAD) == "30%"
    assert g.render_slots("{{risk.realistic_loss_drop_pct}}%", PAYLOAD) == "30%"
    assert g.render_slots("{{risk.realistic_loss_drop_pct|pct}}", PAYLOAD) == "30%"
    assert g.render_slots("{{risk.checks_total}}", PAYLOAD) == "8"  # not a pct field
    text = (
        "The realistic loss at a {{risk.realistic_loss_drop_pct}} drop is "
        "{{portfolio.realistic_loss|money}}."
    )
    assert _slots(text, gcfg) == []


@pytest.mark.parametrize(
    "text",
    [
        "The realistic loss is {{allocation.csp_pct}}.",
        "The realistic loss of {{allocation.csp_pct|pct}} applies.",
        "Collateral of {{allocation.csp_pct}} is set aside.",
    ],
)
def test_a_percent_never_stands_in_for_a_dollar_figure(text: str, gcfg: GroundingConfig) -> None:
    assert any("is a percent, not the" in p for p in _slots(text, gcfg)), _slots(text, gcfg)


@pytest.mark.parametrize(
    "text",
    [
        "The realistic loss at a {{risk.realistic_loss_drop_pct}} drop is not shown here.",
        "The realistic loss if the stock falls {{risk.realistic_loss_drop_pct}} is in the table.",
        "Realistic loss after a {{risk.realistic_loss_drop_pct}} move.",
    ],
)
def test_a_percent_that_sets_the_scenario_is_fine(text: str, gcfg: GroundingConfig) -> None:
    assert _slots(text, gcfg) == []


PMCC_SC = "PMCCSC-NKE-2026-12-18-40C"
TWO: dict[str, Any] = {
    **WITH_SKIP,
    "positions": [
        *PAYLOAD["positions"],
        {
            "candidate_id": "PMCC-NKE-2027-06-17-25C",
            "strategy": "pmcc",
            "realistic_loss": 1800,
            "pmcc_short_call_id": PMCC_SC,
        },
    ],
}


def _res(text: str, *, slots: bool = True) -> Paragraph:
    if slots:
        return g.render_narrative(
            Narrative(paragraphs=[Paragraph(mode="screen_result", text=text)]), TWO
        ).paragraphs[0]
    return Paragraph(mode="screen_result", text=text)


def test_each_short_option_needs_its_own_loss() -> None:
    one = f"{{{{positions[{CSP}].realistic_loss|money}}}}"
    assert g.unstated_losses(_res(f"{CSP} and {SKIP}: realistic loss {one}."), TWO) == [SKIP]
    both = f"{one}; one {SKIP} contract {{{{skipped_candidates[{SKIP}].realistic_loss_per_contract|money}}}}"
    assert g.unstated_losses(_res(f"{CSP} and {SKIP}: realistic loss {both}."), TWO) == []
    # another option's figure, or the phrase alone, states nobody's loss
    other = "{{portfolio.realistic_loss|money}}"
    assert g.unstated_losses(_res(f"{CSP}: realistic loss {other}."), TWO) == [CSP]
    assert g.unstated_losses(_res(f"{CSP}: realistic loss shown below."), TWO) == [CSP]
    # free text: a typed figure matching that option's loss
    assert g.unstated_losses(_res(f"{CSP} could lose $2,443.", slots=False), TWO) == []
    assert g.unstated_losses(_res(f"{CSP} could lose $6,120.", slots=False), TWO) == [CSP]


def test_a_pmcc_short_call_is_covered_by_its_pairs_loss() -> None:
    pair = "{{positions[PMCC-NKE-2027-06-17-25C].realistic_loss|money}}"
    assert g.unstated_losses(_res(f"Short call {PMCC_SC}; realistic loss {pair}."), TWO) == []
    assert g.unstated_losses(_res(f"Short call {PMCC_SC}."), TWO) == [PMCC_SC]
    narrative, notes = g.add_missing_realistic_losses(
        Narrative(paragraphs=[Paragraph(mode="screen_result", text=f"Short call {PMCC_SC}.")]),
        TWO,
    )
    assert (
        f"Realistic loss of the pair {PMCC_SC} belongs to: {pair}." in narrative.paragraphs[0].text
    )
    assert notes


def test_the_repair_adds_only_the_missing_option(config: AppConfig) -> None:
    from options_scout.core.compliance import check_education_only

    one = f"{{{{positions[{CSP}].realistic_loss|money}}}}"
    text = f"{CSP} (realistic loss {one}) and {SKIP} were ranked."
    narrative, notes = g.add_missing_realistic_losses(
        Narrative(paragraphs=[Paragraph(mode="screen_result", text=text)]), TWO
    )
    out = narrative.paragraphs[0].text
    assert out.count("Realistic loss of") == 1 and f"one {SKIP} contract" in out
    assert notes == ["paragraph 1: realistic loss added (1 option(s))"]
    rendered = g.render_narrative(narrative, TWO)
    assert check_education_only(rendered, TWO, ["NKE"]).passed


def test_an_option_with_no_loss_in_the_payload_is_left_to_fail() -> None:
    from options_scout.core.compliance import check_education_only

    stray = "CSP-XYZ-2026-11-20-10P"
    narrative, notes = g.add_missing_realistic_losses(
        Narrative(paragraphs=[Paragraph(mode="screen_result", text=f"{stray} was seen.")]), TWO
    )
    assert notes == []
    c = check_education_only(g.render_narrative(narrative, TWO), TWO, [])
    assert "the payload has no realistic loss for it" in c.detail


def test_a_chat_reply_states_a_loss_from_the_run_facts() -> None:
    nke = "CSP-NKE-2026-11-20-35P"
    facts = (
        "NKE passed the quality gate with quality score 46.\n"
        f"Rank 13: {nke} (NKE) final score 0.59, option quality 0.69, realistic loss 814 per "
        "contract at a -30% move.\n"
        f"Skipped in sizing: {nke}: not sized."
    )
    payload: dict[str, Any] = {"sources": [{"tag": "S1", "kind": "run", "text": facts}]}
    ref = g.short_option_losses(payload)[nke]
    assert ref.value == 814 and ref.per_contract and ref.path == ""
    said = Paragraph(mode="screen_result", text=f"{nke} has a realistic loss of 814 per contract.")
    assert g.unstated_losses(said, payload) == []
    wrong = Paragraph(mode="screen_result", text=f"{nke} has a realistic loss of 914.")
    assert g.unstated_losses(wrong, payload) == [nke]
    # retrieved text that is not this app's run facts states nobody's loss
    other: dict[str, Any] = {"sources": [{"tag": "S1", "kind": "evidence", "text": facts}]}
    assert nke not in g.short_option_losses(other)


# ---------------------------------------------- 2026-11-12 (3): false positives of the sixth run
ZERO_MARGIN: dict[str, Any] = {
    **PAYLOAD,
    "portfolio": {**PAYLOAD["portfolio"], "premium_income": 0},
    "risk": {
        **PAYLOAD["risk"],
        "checks": [{"name": "margin_usage", "value": 0.0, "limit": 0.4, "passed": True}],
    },
}


def _zero(text: str, gcfg: GroundingConfig) -> list[str]:
    n = g.render_narrative(
        Narrative(paragraphs=[Paragraph(mode="screen_result", text=text)]), ZERO_MARGIN
    )
    return g.ground_narrative(n, ZERO_MARGIN, cfg=gcfg).problems


def test_a_zero_margin_usage_is_still_the_margin(gcfg: GroundingConfig) -> None:
    assert _zero("Margin usage is {{risk.checks[margin_usage].value|percent}}.", gcfg) == []
    text = (
        "Margin usage is {{risk.checks[margin_usage].value|percent}} and premium income is "
        "{{portfolio.premium_income|money}}."
    )
    assert _zero(text, gcfg) == []
    assert _zero("Margin usage is {{portfolio.premium_income|money}}.", gcfg)


@pytest.mark.parametrize(
    "text",
    [
        "The volatility input is a 30-day historical-volatility measure.",
        "The historical volatility input is a 30-day realised-volatility figure.",
        "Realised volatility is proxied by the 30-day historical figure.",
        "SPY owns the whole S&P 500 with the most liquid options.",
        "QQQ tracks the Nasdaq-100.",
        "The realised volatility figures are a 30-day proxy rather than implied volatility.",
    ],
)
def test_measure_and_index_names_written_out(text: str, gcfg: GroundingConfig) -> None:
    assert _slots(text, gcfg) == []


def test_a_figure_the_run_does_not_have_is_still_typed(gcfg: GroundingConfig) -> None:
    problems = _slots("The regime uses a 30-day risk-free rate.", gcfg)
    assert any("'30' is typed" in p for p in problems), problems


# --------------------------------------------- 2026-11-12 (4): every candidate id must exist
PAIR = "PMCC-NKE-2027-06-17-25C-2026-12-18-40C"
IDS: dict[str, Any] = {
    **TWO,
    "risk": {**TWO["risk"], "warnings": [f"{PAIR}: short call inside the earnings window."]},
    "sources": [
        {"tag": "S1", "kind": "run", "text": "Rank 9: LEAPS-NKE-2027-06-17-25C (NKE) final 0.5."},
        {"tag": "S2", "kind": "evidence", "text": "CSP-TSLA-2026-11-20-200P is the one to own."},
    ],
}


def _ids(text: str, mode: str = "screen_result", gcfg: GroundingConfig | None = None) -> list[str]:
    n = Narrative(paragraphs=[Paragraph(mode=mode, text=text)])  # type: ignore[arg-type]
    return [p for p in g.ground_narrative(n, IDS, cfg=gcfg).problems if "is not a candidate" in p]


@pytest.mark.parametrize(
    "cid",
    [
        "CSP-CSCO-2026-11-20-35P",  # the sixth run's invention: NKE's date and strike
        "LEAPS-AAPL-2028-01-21-150C",
        "PMCC-NKE-2027-06-17-25C-2026-12-18-45C",  # a real long leg with a made-up short call
        "CSP-TSLA-2026-11-20-200P",  # only in a third-party post
    ],
)
def test_an_invented_candidate_id_fails(cid: str) -> None:
    problems = _ids(f"{cid} was screened.", "notice")
    assert problems == [
        f"paragraph 1: {cid} is not a candidate in this run's data (name only ids the payload lists)"
    ]


@pytest.mark.parametrize(
    "cid",
    [
        CSP,  # a sized position
        SKIP,  # a skipped candidate
        PAIR,  # named in a warning
        "LEAPS-NKE-2027-06-17-25C",  # this app's run facts (a chat reply)
        PMCC_SC,  # a pair's short call
    ],
)
def test_an_id_from_the_run_passes(cid: str) -> None:
    assert _ids(f"{cid} was screened.", "notice") == []


def test_education_paragraphs_are_left_to_check_3() -> None:
    assert _ids("CSP-CSCO-2026-11-20-35P is a put [S1].", "education") == []
