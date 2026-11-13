"""Phase 12 step 12.6: the Tax & Accounts agent, the ``tax`` intent and compliance check 11."""

from __future__ import annotations

import json

import pytest

from options_scout.agent.chat import ChatSession
from options_scout.agent.deps import Deps
from options_scout.agent.graph import build_agents, initial_state, thread_config
from options_scout.agent.nodes.tax_retrieval import MAX_SOURCES, expand, fuse_documents
from options_scout.config import AppConfig, load_config
from options_scout.core import compliance as cc
from options_scout.core.models import Narrative, Paragraph
from options_scout.llm.rules import is_tax_message, rule_route
from tests.conftest import REPO_ROOT

DATASETS = REPO_ROOT / "evals" / "datasets" / "dev"


@pytest.fixture(scope="module")
def config_module() -> AppConfig:
    return load_config(REPO_ROOT)


@pytest.fixture(scope="module")
def deps(config_module: AppConfig, tmp_path_factory: pytest.TempPathFactory) -> Deps:
    from options_scout.social.pipeline import TrendStore

    d = Deps.from_config(config_module)
    d.trend_store = TrendStore(tmp_path_factory.mktemp("trends") / "t.sqlite")
    return d


def test_tax_rows_route_and_profiles_do_not() -> None:
    rows = [json.loads(line) for line in (DATASETS / "chat_routing.jsonl").read_text().splitlines()]
    assert sum(r["expected"] == "tax" for r in rows) >= 10
    for r in rows:
        ctx = "exists" if r["has_report"] else "does not exist yet"
        d = rule_route(f"<message>\n{r['message']}\n</message>\nContext: a report {ctx}")
        assert d.intent == r["expected"], (r["id"], d.intent)
    assert not is_tax_message("I have $60,000 in a cash account, conservative.")
    assert not is_tax_message("What if it were an IRA account?")


def test_check_tax_reply_rules(config_module: AppConfig) -> None:
    cfg = config_module.compliance
    disc = cfg.tax.disclaimer
    payload = {"tax": {"question": "q", "facts": {}}}

    def reply(*texts: str) -> Narrative:
        return Narrative(paragraphs=[Paragraph(mode="notice", text=t) for t in texts])

    assert cc.check_tax_reply(reply("The premium folds into the basis.", disc), payload, cfg).passed
    missing = cc.check_tax_reply(reply("The premium folds into the basis."), payload, cfg)
    assert not missing.passed and "0 time(s)" in missing.detail
    twice = cc.check_tax_reply(reply(disc, disc), payload, cfg)
    assert not twice.passed
    rate = cc.check_tax_reply(
        reply("Short-term gains are taxed at 37% for you.", disc), payload, cfg
    )
    assert not rate.passed and "rate is stated" in rate.detail
    imperative = cc.check_tax_reply(reply("File Form 8949 with your return.", disc), payload, cfg)
    assert not imperative.passed and "imperative" in imperative.detail
    descriptive = cc.check_tax_reply(
        reply("Form 8949 lists each sale; the broker's 1099-B feeds it.", disc), payload, cfg
    )
    assert descriptive.passed
    assert cc.check_tax_reply(reply("anything"), {}, cfg).passed  # not a tax reply


def test_tax_turns_through_the_chat_session(deps: Deps) -> None:
    session = ChatSession(deps)
    t = "t-tax"
    r1 = session.send(t, "$60,000 in a cash account, conservative, cash-secured puts only.")
    assert r1.status == "completed"
    r2 = session.send(t, "What happens to my taxes if I get assigned?")
    assert r2.status == "completed" and r2.turn.intent == "tax"
    assert r2.turn.compliance is not None and r2.turn.compliance.passed
    checks = {c.name: c for c in r2.turn.compliance.checks}
    assert checks["tax_reply"].passed and checks["check_citations"].passed
    assert r2.turn.text.count(deps.cfg.compliance.tax.disclaimer) == 1
    assert r2.turn.citations and all(c.kind == "tax" for c in r2.turn.citations)
    values = session.graph.get_state(thread_config(t)).values
    facts = values["tax_facts"]
    assert facts.ticker and facts.assigned_basis_per_share is not None
    assert facts.assigned_basis_per_share == pytest.approx(facts.strike - facts.premium, abs=0.01)
    assert f"{facts.ticker}" in r2.turn.text and "basis" in r2.turn.text.lower()
    assert values["agents_visited"][-3:] == ["orchestrator_agent", "tax_agent", "compliance_agent"]
    r3 = session.send(t, "Can I sell naked puts in my IRA?")
    assert r3.turn.intent == "tax" and r3.turn.compliance is not None and r3.turn.compliance.passed
    docs = {c.doc_id for c in r3.turn.citations}
    assert docs & {"options-in-an-ira", "account-types-for-options"}
    assert "margin" in r3.turn.text.lower()


def test_tax_agent_without_a_screen_explains_mechanics_only(deps: Deps) -> None:
    agent = build_agents(deps)["tax_agent"]
    out = agent.invoke(
        {**initial_state(), "intent": "tax", "tax_text": "Are SPY options Section 1256 contracts?"}
    )
    facts = out["tax_facts"]
    assert facts.ticker is None and any("no screen" in n for n in facts.notes)
    assert out["sources"] and out["sources"][0].kind == "tax"
    assert out["answer"].paragraphs[-1].mode == "notice"
    assert any(deps.cfg.compliance.tax.disclaimer == p.text for p in out["answer"].paragraphs)
    assert "section-1256-contracts" in {c.doc_id for c in out["citations"]}


# ----------------------------------------------- regressions found by the first full eval run
def test_expanded_query_counts_even_when_the_plain_one_matches(deps: Deps) -> None:
    """The question as asked finds a neighbouring document; the expansion into the documents'
    vocabulary finds the right one. Both rankings are fused, one chunk per document."""
    question = "When does the holding period of assigned shares start?"
    retriever = deps.knowledge()
    plain = retriever.retrieve(question, kind="tax", top_k=6)
    expanded = retriever.retrieve(expand(question), kind="tax", top_k=6)
    # the plain query leads with the neighbour; whether the right document also scrapes into
    # its top six depends on corpus-wide BM25 weights, so only the lead is asserted
    assert plain.hits[0].chunk.doc_id == "leaps-holding-period"
    assert expanded.hits[0].chunk.doc_id == "assignment-cost-basis"
    fused = fuse_documents([plain, expanded], MAX_SOURCES)
    docs = [c.doc_id for c in fused]
    assert "assignment-cost-basis" in docs[:2] and len(docs) == len(set(docs)) <= MAX_SOURCES
    assert fuse_documents([], MAX_SOURCES) == []


@pytest.mark.parametrize(
    ("question", "doc_id"),
    [
        ("Are SPY and QQQ options Section 1256 contracts?", "section-1256-contracts"),
        ("How do option trades appear on Form 1099-B and Form 8949?", "form-1099b-and-8949"),
        ("What is Form 6781 used for?", "section-1256-contracts"),
    ],
)
def test_questions_that_name_a_section_or_a_form_are_answered(
    deps: Deps, config_module: AppConfig, question: str, doc_id: str
) -> None:
    """A section or form number in the question is not run data, the tax documents' own
    disclaimer sentence is not repeated by an excerpt, and a form number is a tax cue."""
    r = ChatSession(deps).send(f"t-tax-form-{doc_id}-{len(question)}", question)
    assert r.turn.intent == "tax"
    assert doc_id in {c.doc_id for c in r.turn.citations}
    assert r.turn.compliance is not None and r.turn.compliance.passed
    assert r.turn.compliance.attempts == 1, "the first answer passes; no fallback sentence"
    assert r.turn.text.count(config_module.compliance.tax.disclaimer) == 1
    assert "could not produce an explanation" not in r.turn.text


def test_the_question_is_not_run_data_at_any_depth() -> None:
    edu = Paragraph(
        mode="education", text="Section 1256 contracts are marked to market [S1].", citations=["S1"]
    )
    nested = {"tax": {"question": "Are SPY options Section 1256 contracts?", "facts": {}}}
    assert cc.check_education_only(Narrative(paragraphs=[edu]), nested, []).passed
    # a number that does come from the run is still caught
    leaked = {"tax": {"question": "q", "facts": {"cash_paid_at_assignment": 1256}}}
    assert not cc.check_education_only(Narrative(paragraphs=[edu]), leaked, []).passed
