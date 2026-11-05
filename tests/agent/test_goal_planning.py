"""Phase 12 step 12.3: the Goal Planning agent, the ``goal`` intent and compliance check 9."""

from __future__ import annotations

import json
from typing import Any

import pytest

from options_scout.agent.chat import ChatSession
from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    AGENT_ORDER,
    build_agents,
    build_graph,
    initial_state,
    stream_run,
    thread_config,
)
from options_scout.config import AppConfig, load_config
from options_scout.core import compliance as cc
from options_scout.core.models import Goal, Narrative, Paragraph, ScreeningReport
from options_scout.llm.rules import is_goal_message, rule_parse_goal, rule_route
from tests.conftest import REPO_ROOT

DATASETS = REPO_ROOT / "evals" / "datasets"


@pytest.fixture(scope="module")
def config_module() -> AppConfig:
    return load_config(REPO_ROOT)


@pytest.fixture(scope="module")
def deps(config_module: AppConfig, tmp_path_factory: pytest.TempPathFactory) -> Deps:
    from options_scout.social.pipeline import TrendStore

    d = Deps.from_config(config_module)
    d.trend_store = TrendStore(tmp_path_factory.mktemp("trends") / "t.sqlite")
    return d


@pytest.fixture(scope="module")
def session(deps: Deps) -> ChatSession:
    return ChatSession(deps)


# ----------------------------------------------------------------------------- parsing
@pytest.mark.parametrize(
    ("text", "kind", "field", "value"),
    [
        (
            "I want $400 a month from puts on my $60k cash account",
            "income",
            "target_monthly_income",
            400,
        ),
        ("grow 40k to 55k in three years", "growth", "horizon_years", 3),
        ("grow 40k to 55k in three years", "growth", "start_balance", 40_000),
        (
            "I add $500 a month, can I reach 100k in 5 years?",
            "contribution",
            "monthly_contribution",
            500,
        ),
        (
            "I spend $48k a year, have $220k and add $2k a month.",
            "income",
            "annual_expenses",
            48_000,
        ),
        ("when could I lean fire? my minimum expenses are 36k a year", "fire", "variant", "lean"),
        (
            "when could I lean fire? my minimum expenses are 36k a year",
            "fire",
            "annual_expenses",
            36_000,
        ),
        (
            "I'm 35 and want to coast FIRE by 50, expenses 4k a month",
            "fire",
            "annual_expenses",
            48_000,
        ),
        ("I'm 35 and want to coast FIRE by 50, expenses 4k a month", "fire", "target_age", 50),
        (
            "barista fire with 20k a year part-time income, I spend 50k a year",
            "fire",
            "part_time_income",
            20_000,
        ),
        ("retire on 48k a year with a 3.5% withdrawal rule", "fire", "withdrawal_rate", 0.035),
    ],
)
def test_rule_parse_goal_reads_amounts_in_context(
    text: str, kind: str, field: str, value: Any
) -> None:
    parsed = rule_parse_goal(text)
    if kind != "income" or parsed.target_monthly_income is not None:
        assert parsed.kind == kind, parsed
    assert getattr(parsed, field) == value, parsed


def test_goal_intent_rows_route_to_goal_and_definitions_do_not() -> None:
    lines = (DATASETS / "chat_routing.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    goal_rows = [r for r in rows if r["expected"] == "goal"]
    assert len(goal_rows) >= 10
    for r in rows:
        ctx = "exists" if r["has_report"] else "does not exist yet"
        d = rule_route(f"<message>\n{r['message']}\n</message>\nContext: a report {ctx}")
        assert d.intent == r["expected"], (r["id"], d.intent)
    assert not is_goal_message("What is FIRE?")
    assert not is_goal_message("What if I only had 30k?")
    assert is_goal_message("Is 1.2 million enough to retire on 48k a year?")


# -------------------------------------------------------------------- compliance check 9
def _edu(text: str) -> Paragraph:
    return Paragraph(mode="screen_result", text=text)


def test_check_goal_narrative_rules(config_module: AppConfig) -> None:
    cfg = config_module.compliance
    payload = {"goal_plan": {"status_text": "does not fit", "projection": {"base": 70000}}}
    good = Narrative(
        paragraphs=[
            _edu(
                "Goal check: this goal does not fit. At the base yield it would reach $70,000; "
                "on the stress path less."
            )
        ]
    )
    assert cc.check_goal_narrative(good, payload, cfg).passed
    no_status = Narrative(paragraphs=[_edu("It would reach $70,000; the stress path is lower.")])
    c = cc.check_goal_narrative(no_status, payload, cfg)
    assert not c.passed and "verdict" in c.detail
    promise = Narrative(
        paragraphs=[_edu("This goal fits and the balance will reach $70,000 after stress.")]
    )
    c = cc.check_goal_narrative(promise, payload, cfg)
    assert not c.passed and "promised" in c.detail
    no_stress = Narrative(paragraphs=[_edu("This goal fits; the balance would be $70,000.")])
    assert "stress path" in cc.check_goal_narrative(no_stress, payload, cfg).detail
    fire_payload = {**payload, "goal_plan": {**payload["goal_plan"], "fire": {"variant": "lean"}}}
    fire_text = Narrative(
        paragraphs=[
            _edu(
                "This lean FIRE plan does not fit: the 4% withdrawal rate comes from "
                "diversified-portfolio research; the stress path is shown."
            )
        ]
    )
    assert cc.check_goal_narrative(fire_text, fire_payload, cfg).passed
    missing = Narrative(paragraphs=[_edu("This plan does not fit; see the stress path.")])
    c = cc.check_goal_narrative(missing, fire_payload, cfg)
    assert not c.passed and "lean" in c.detail and "withdrawal" in c.detail
    assert cc.check_goal_narrative(missing, {"goal_plan": {"clarification": "x"}}, cfg).passed
    assert cc.check_goal_narrative(missing, {}, cfg).passed
    # a screening report that carries a goal plan is not a goal reply
    assert cc.check_goal_narrative(missing, fire_payload, cfg, text_kind="report").passed


# ------------------------------------------------------------------------- the agent
def test_goal_agent_standalone_without_a_screen(deps: Deps) -> None:
    agent = build_agents(deps)["goal_planning_agent"]
    state = {
        **initial_state(),
        "intent": "goal",
        "goal_text": "I have 60k, can I make $400 a month?",
    }
    out = agent.invoke(state)
    plan = out["goal_plan"]
    assert out["goal"].kind == "income" and out["goal"].start_balance == 60_000
    assert plan.feasibility.required_return == pytest.approx(0.08)
    assert plan.feasibility.status == "does_not_fit"  # cash alone yields the T-bill rate
    assert any("no screen on this thread" in a for a in plan.assumptions)
    answer: Narrative = out["answer"]
    assert "does not fit" in answer.markdown and "stress" in answer.markdown.lower()
    assert answer.paragraphs[-1].mode == "notice"
    assert out["sources"] and all(c.kind == "basics" for c in out["sources"])
    assert out["citations"]


def test_goal_agent_asks_for_clarification(deps: Deps) -> None:
    agent = build_agents(deps)["goal_planning_agent"]
    state = {**initial_state(), "intent": "goal", "goal_text": "I want to reach my goal someday"}
    out = agent.invoke(state)
    assert out["goal"] is None and out["goal_plan"] is None
    assert out["goal_clarification"] and "could not tell" in out["goal_clarification"]
    assert out["answer"].paragraphs[0].mode == "notice"
    assert out["explain_payload"]["goal_plan"]["clarification"]


def test_goal_turns_through_the_chat_session(session: ChatSession) -> None:
    t = "t-goal"
    r1 = session.send(t, "$60,000 in a cash account, conservative, cash-secured puts only.")
    assert r1.status == "completed" and r1.turn.intent == "new_screen"
    r2 = session.send(t, "Can I make $400 a month from this account?")
    assert r2.status == "completed" and r2.turn.intent == "goal"
    assert r2.turn.compliance is not None and r2.turn.compliance.passed
    names = {c.name: c for c in r2.turn.compliance.checks}
    assert names["goal_narrative"].passed and r2.turn.compliance.text_kind == "answer"
    assert "does not fit" in r2.turn.text and "stress" in r2.turn.text.lower()
    assert r2.turn.citations and r2.turn.citations[0].kind == "basics"
    values = session.graph.get_state(thread_config(t)).values
    plan = values["goal_plan"]
    assert plan.goal.start_balance == 60_000 and plan.yield_estimate.capital_used > 0
    assert values["agents_visited"][-3:] == [
        "orchestrator_agent",
        "goal_planning_agent",
        "compliance_agent",
    ]
    r3 = session.send(
        t,
        "I spend 48k a year and add 2k a month. When could I lean FIRE if my minimum expenses are 36k a year? I'm 35, by 50.",
    )
    assert r3.turn.intent == "goal" and r3.turn.compliance is not None and r3.turn.compliance.passed
    fire = session.graph.get_state(thread_config(t)).values["goal_plan"].fire
    assert (
        fire is not None and fire.variant == "lean" and fire.fire_number == pytest.approx(900_000)
    )
    low = r3.turn.text.lower()
    assert "lean" in low and "withdrawal" in low and "diversified" in low
    assert "will reach" not in low
    history = session.history(t)
    assert [h.intent for h in history if h.role == "assistant"][-2:] == ["goal", "goal"]


def test_screen_seeded_with_a_goal_runs_goal_planning_between_risk_and_education(
    deps: Deps,
) -> None:
    graph = build_graph(deps)
    state = initial_state(
        "I have $100,000 of buying power in a margin account, balanced risk tolerance. "
        "Show me CSPs and LEAPS/PMCC ideas."
    )
    state["goal"] = Goal(kind="income", start_balance=100_000, target_monthly_income=500)
    updates = list(stream_run(graph, state, "t-goal-screen"))
    final = graph.get_state(thread_config("t-goal-screen")).values
    rep: ScreeningReport = final["report"]
    assert rep.goal_plan is not None and rep.goal_plan.goal.target_monthly_income == 500
    visited = [k for u in updates for k in u if k in AGENT_ORDER]
    chat_only = {"tax_agent"}  # Tax & Accounts never runs inside a screen
    assert visited == [a for a in AGENT_ORDER if a not in chat_only]  # Goal Planning included
    assert "## Goal plan" in final["report_markdown"]
    assert final["explain_payload"]["goal_plan"]["status_text"] in (
        "fits",
        "stretch",
        "does not fit",
    )
    assert rep.compliance is not None and rep.compliance.passed
