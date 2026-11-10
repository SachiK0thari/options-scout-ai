"""Phase 10 step 10.4: the Compliance agent in the graph: audit log, retry then fallback, guards."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    answer_question,
    build_graph,
    build_qa_graph,
    initial_state,
    question_state,
    stream_run,
    thread_config,
)
from options_scout.agent.nodes.audit import FALLBACK_SENTENCE
from options_scout.config import AppConfig, load_config
from options_scout.core.models import ComplianceReport, Narrative, Paragraph, ScreeningReport
from tests.conftest import REPO_ROOT

REQUEST = (
    "I have $100,000 of buying power in a margin account, balanced risk tolerance. "
    "Show me CSPs and LEAPS/PMCC ideas."
)
CHECKS = [
    "check_numbers",
    "check_citations",
    "check_education_only",
    "check_suitability",
    "check_language",
    "check_disclaimer",
    "check_sources_fresh",
    "check_no_pii",
    "goal_narrative",  # Phase 12 check 9 (trivially passing on a report)
    "news_grounding",  # Phase 12 check 10 (trivially passing without headlines)
    "tax_reply",  # Phase 12 check 11 (trivially passing without a tax reply)
]


@pytest.fixture(scope="module")
def config_module() -> AppConfig:
    return load_config(REPO_ROOT)


@pytest.fixture(scope="module")
def deps(config_module: AppConfig, tmp_path_factory: pytest.TempPathFactory) -> Deps:
    from options_scout.social.pipeline import TrendStore

    d = Deps.from_config(config_module)
    d.trend_store = TrendStore(tmp_path_factory.mktemp("trends") / "t.sqlite")
    return d


def _run(deps: Deps, text: str, thread: str) -> tuple[list[str], dict[str, Any]]:
    graph = build_graph(deps)
    visited: list[str] = []
    for u in stream_run(graph, initial_state(text), thread):
        visited += [k for k in u if k != "__interrupt__"]
    return visited, graph.get_state(thread_config(thread)).values


def test_report_carries_a_passing_compliance_report_and_audit_log(deps: Deps) -> None:
    visited, final = _run(deps, REQUEST, "t-comp")
    rep: ScreeningReport = final["report"]
    assert visited.count("compliance_node") == visited.count("audit_node") == 1
    assert (
        visited.index("compliance_node")
        < visited.index("audit_node")
        < visited.index("report_node")
    )
    comp = rep.compliance
    assert isinstance(comp, ComplianceReport) and comp.passed and comp.text_kind == "report"
    assert [c.name for c in comp.checks] == CHECKS
    assert all(c.passed for c in comp.checks)
    assert rep.audit_log == [comp] and final["audit_log"] == [comp]
    assert rep.verification == comp.verification and rep.verification.passed
    facts = final["suitability_facts"]
    assert (
        facts is not None
        and facts.account_type == "margin"
        and facts.position_count == len(rep.portfolio.positions)
    )
    assert (
        "## Compliance" in final["report_markdown"]
        and f"audit `{comp.audit_id}`" in final["report_markdown"]
    )
    assert comp.checks[3].detail == "suits the profile"


def test_report_retries_then_falls_back_and_rechecks(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def advice(payload: dict[str, Any], sources: str = "", audience: str = "") -> Narrative:
        calls["n"] += 1
        return Narrative(
            paragraphs=[
                Paragraph(
                    mode="screen_result",
                    text="You should buy every put on the list; it will profit 23.7%.",
                ),
                Paragraph(mode="notice", text=deps.cfg.settings.disclaimer),
            ]
        )

    monkeypatch.setattr(deps.llm, "explain", advice)
    visited, final = _run(deps, REQUEST, "t-comp-bad")
    rep: ScreeningReport = final["report"]
    budget = deps.cfg.settings.agent.max_explainer_retries + 1
    assert calls["n"] == budget
    assert visited.count("compliance_node") == visited.count("audit_node") == budget
    # every failed evaluation is on the audit log, then the deterministic fallback's passing one
    assert len(rep.audit_log) == budget + 1
    assert [e.passed for e in rep.audit_log] == [False] * budget + [True]
    assert rep.compliance is not None and rep.compliance.passed and rep.verification.passed
    assert "You should buy" not in rep.narrative_markdown
    assert any("deterministic narrative used (passed=True)" in e for e in rep.errors)
    failed = rep.audit_log[0]
    assert {"check_numbers", "check_language"} <= {c.name for c in failed.failed_checks}
    assert "check_language" in failed.retry_feedback
    assert "Audit trail:" in final["report_markdown"]


def test_answer_fallback_sentence_after_exhausted_retries(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        deps.llm,
        "answer_concept",
        lambda q, s, d, **kw: Narrative(
            paragraphs=[Paragraph(mode="education", text="Buy the call now, guaranteed [S1].")]
        ),
    )
    graph = build_qa_graph(deps)
    for _ in stream_run(graph, question_state("what is a LEAPS call"), "t-qa-fallback"):
        pass
    final = graph.get_state(thread_config("t-qa-fallback")).values
    answer: Narrative = final["answer"]
    assert answer.paragraphs[0].text == FALLBACK_SENTENCE
    assert answer.paragraphs[-1].text == deps.cfg.settings.disclaimer
    assert final["compliance"].passed and final["verification"].passed
    budget = deps.cfg.settings.agent.max_explainer_retries + 1
    assert len(final["audit_log"]) == budget + 1 and final["audit_log"][-1].passed
    assert final["citations"] == []


def test_answer_question_refuses_without_audit_entry(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    import options_scout.agent.graph as graph_mod

    class _NoAudit:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        def get_state(self, _cfg: Any) -> Any:
            class _Snap:
                values = {"answer": Narrative(), "compliance": None, "audit_log": []}

            return _Snap()

    monkeypatch.setattr(graph_mod, "build_qa_graph", lambda deps: _NoAudit())
    monkeypatch.setattr(graph_mod, "stream_run", lambda *a, **k: iter(()))
    with pytest.raises(RuntimeError, match="without a ComplianceReport"):
        answer_question(deps, "what is theta", "t-qa-guard")


def test_api_report_endpoint_requires_an_audit_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    import time

    from options_scout.api import main as api
    from options_scout.social.pipeline import TrendStore

    api._registry = None
    monkeypatch.setattr(api, "_RATE_LIMIT_PER_MIN", 10_000)
    api._hits.clear()
    monkeypatch.setenv("OPTIONS_SCOUT_API_KEY", "k")  # W37: required by default
    client = TestClient(api.app, headers={"X-API-Key": "k"})
    reg = api.registry()
    reg.deps.trend_store = TrendStore(tmp_path_factory.mktemp("api-comp") / "t.sqlite")
    r = client.post("/v1/screen", json={"request_text": REQUEST})
    assert r.status_code == 200
    thread = r.json()["thread_id"]
    client.headers["X-Thread-Token"] = r.json()["thread_token"]
    for _ in range(600):
        if client.get(f"/v1/runs/{thread}").json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    rep = client.get(f"/v1/runs/{thread}/report").json()
    assert rep["compliance"]["passed"] and rep["audit_log"]
    assert [c["name"] for c in rep["compliance"]["checks"]] == CHECKS
    stored: ScreeningReport = reg.state(thread)["report"]
    stripped = stored.model_copy(update={"compliance": None, "audit_log": []})
    monkeypatch.setattr(reg, "state", lambda t: {"report": stripped, "report_markdown": "x"})
    assert client.get(f"/v1/runs/{thread}/report").status_code == 500
    api._registry = None


# ------------------------------------------------------------ W12: unsuitable runs are withheld
def _unsuitable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the Risk agent's suitability facts fail on facts (a position losing half the account),
    which no rewrite of the narrative can fix."""
    from options_scout.core import risk as risk_core

    real = risk_core.suitability_facts

    def bad(*a: Any, **k: Any) -> Any:
        return real(*a, **k).model_copy(update={"max_position_loss_pct": 0.5})

    monkeypatch.setattr(risk_core, "suitability_facts", bad)


def test_an_unsuitable_screen_is_withheld_without_rewrites(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    from options_scout.core.compliance import WITHHELD_NOTICE

    _unsuitable(monkeypatch)
    visited, final = _run(deps, REQUEST, "t-comp-unsuitable")
    rep: ScreeningReport = final["report"]
    assert rep.withheld and rep.withheld_reasons == ["loss_over_limit"]
    # a fact failure goes straight to the withheld path: one evaluation, no rewrites
    assert visited.count("compliance_node") == 1 and visited.count("explainer_node") == 1
    assert rep.compliance is not None and not rep.compliance.passed
    assert "check_suitability" in {c.name for c in rep.compliance.failed_checks}
    # the narrative is the fixed notice; the sized positions and their goal plan are gone
    assert rep.narrative_markdown.startswith(WITHHELD_NOTICE)
    assert "loss_over_limit" in rep.narrative_markdown
    assert rep.portfolio.positions == [] and rep.goal_plan is None
    # the deterministic tables stay: candidates and the constraint checks
    assert rep.csp_candidates and rep.risk.checks
    md = final["report_markdown"]
    assert "## Sized portfolio\n" + WITHHELD_NOTICE in md.replace("\n\n", "\n")
    assert "FAIL" in md


def test_a_text_only_suitability_failure_still_gets_a_rewrite() -> None:
    from options_scout.core.compliance import fact_suitability_codes
    from options_scout.core.models import ComplianceCheck, VerificationResult

    def report(codes: list[str]) -> ComplianceReport:
        return ComplianceReport(
            passed=False,
            checks=[
                ComplianceCheck(name="check_suitability", passed=False, locations=codes),
            ],
            audit_id="x",
            verification=VerificationResult(
                passed=False,
                numbers_checked=0,
                ungrounded_numbers=[],
                banned_phrases_found=[],
                disclaimer_present=True,
                cited_candidate_ids=[],
                attempts=1,
            ),
        )

    assert fact_suitability_codes(report(["earnings_unflagged_conservative"])) == []
    assert fact_suitability_codes(
        report(["margin_on_cash", "earnings_unflagged_conservative"])
    ) == ["margin_on_cash"]


def test_api_withholds_an_unsuitable_report_with_409(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    import time

    from options_scout.api import main as api
    from options_scout.social.pipeline import TrendStore

    _unsuitable(monkeypatch)
    api._registry = None
    monkeypatch.setattr(api, "_RATE_LIMIT_PER_MIN", 10_000)
    api._hits.clear()
    monkeypatch.setenv("OPTIONS_SCOUT_API_KEY", "k")  # W37: required by default
    client = TestClient(api.app, headers={"X-API-Key": "k"})
    reg = api.registry()
    reg.deps.trend_store = TrendStore(tmp_path_factory.mktemp("api-withheld") / "t.sqlite")
    started = client.post("/v1/screen", json={"request_text": REQUEST}).json()
    thread = started["thread_id"]
    client.headers["X-Thread-Token"] = started["thread_token"]
    for _ in range(600):
        if client.get(f"/v1/runs/{thread}").json()["status"] in ("withheld", "completed", "failed"):
            break
        time.sleep(0.1)
    status = client.get(f"/v1/runs/{thread}").json()
    assert status["status"] == "withheld" and "portfolio" not in status["partial"]
    for fmt in ("json", "md"):
        r = client.get(f"/v1/runs/{thread}/report", params={"format": fmt})
        assert r.status_code == 409
        body = r.json()["detail"]
        assert body["status"] == "withheld" and body["reason_codes"] == ["loss_over_limit"]
        assert "check_suitability" in body["failed_checks"]
    api._registry = None


def test_chat_turn_for_a_withheld_screen_is_the_notice(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    from options_scout.agent.chat import ChatSession
    from options_scout.core.compliance import WITHHELD_NOTICE

    _unsuitable(monkeypatch)
    r = ChatSession(deps).send("t-chat-withheld", REQUEST)
    assert r.status == "completed"
    assert r.turn.text.startswith(WITHHELD_NOTICE) and "Screen complete" not in r.turn.text
    assert "loss_over_limit" in r.turn.text
    assert r.turn.compliance is not None and r.turn.compliance.passed  # the notice itself


def test_a_withheld_thread_drops_the_refused_positions_from_its_state(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The W12 leftover: a later goal turn on a withheld thread must not read the sized
    portfolio the gate refused."""
    from options_scout.agent.chat import ChatSession

    _unsuitable(monkeypatch)
    session = ChatSession(deps)
    t = "t-withheld-goal"
    session.send(t, REQUEST)
    values = session.graph.get_state({"configurable": {"thread_id": t}}).values
    assert values["report"].withheld
    assert values.get("portfolio") is None and values.get("goal_plan") is None
    r = session.send(t, "Can I make $400 a month from this account?")
    assert r.turn.intent == "goal"
    plan = session.graph.get_state({"configurable": {"thread_id": t}}).values["goal_plan"]
    assert any("withheld" in a for a in plan.assumptions)
