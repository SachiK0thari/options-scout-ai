"""Phase 10 step 10.3: Education agent with citations, concept Q&A, payoff goldens."""

from __future__ import annotations

import re
from typing import Any

import pytest

from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    answer_question,
    build_agents,
    build_graph,
    build_qa_graph,
    initial_state,
    question_state,
    stream_run,
    thread_config,
)
from options_scout.agent.nodes.evidence_retrieval import evidence_chunks
from options_scout.agent.nodes.explainer import render_sources_block, rule_prompt
from options_scout.agent.nodes.knowledge_retrieval import report_queries, select_sources
from options_scout.config import AppConfig, load_config
from options_scout.core import payoff
from options_scout.core.compliance import resolve_citations, unknown_source_tags, verify_narrative
from options_scout.core.models import (
    NO_SOURCE_SENTENCE,
    SOURCE_TAG,
    Citation,
    Narrative,
    Paragraph,
    ScreeningReport,
)
from options_scout.llm.rules import parse_sources_block, rule_answer_concept, rule_explain
from options_scout.rag.models import citation_of
from tests.conftest import REPO_ROOT

REQUEST = (
    "I have $100,000 of buying power in a margin account, balanced risk tolerance. "
    "Show me CSPs and LEAPS/PMCC ideas."
)


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
def report(deps: Deps) -> tuple[ScreeningReport, dict[str, Any]]:
    graph = build_graph(deps)
    for _ in stream_run(graph, initial_state(REQUEST), "t-edu"):
        pass
    final = graph.get_state(thread_config("t-edu")).values
    return final["report"], final


# ------------------------------------------------------------------------ report narrative


def test_every_education_paragraph_is_cited_and_every_tag_resolves(report: Any) -> None:
    rep, final = report
    edu = [p for p in rep.narrative.paragraphs if p.mode == "education"]
    assert edu, "fixture run produced no education paragraphs"
    for p in edu:
        assert p.citations, p.text
        assert re.search(SOURCE_TAG, p.text), p.text
    tags_in_text = {
        f"S{n}" for p in rep.narrative.paragraphs for n in re.findall(SOURCE_TAG, p.text)
    }
    assert tags_in_text == {c.tag for c in rep.citations}
    assert len(final["sources"]) >= len(rep.citations) >= 1
    assert rep.verification.passed and rep.verification.unknown_citations == []
    assert rep.verification.citations_checked >= len(rep.citations)
    # screen_result paragraphs carry the candidate ids and the realistic loss, education ones none
    screen = " ".join(p.text for p in rep.narrative.paragraphs if p.mode == "screen_result")
    assert rep.verification.cited_candidate_ids and "realistic loss" in screen
    for p in edu:
        assert not any(cid in p.text for cid in rep.verification.cited_candidate_ids)
    assert rep.narrative.paragraphs[-1].mode == "notice"
    assert rep.narrative.paragraphs[-1].text == rep.disclaimer


def test_report_markdown_has_sources_and_payoff_numbers(report: Any) -> None:
    rep, final = report
    md = final["report_markdown"]
    assert "## Sources" in md and all(f"[{c.tag}]" in md for c in rep.citations)
    for c in rep.citations:
        assert c.url and c.quote and c.chunk_id.startswith(c.doc_id + "#")
    payload = final["explain_payload"]
    assert payload["sources"] and payload["sources"][0]["tag"] == "S1"
    for pos in payload["positions"]:
        assert pos["payoff"]["breakeven"] is not None and pos["payoff"]["max_loss"] is not None
        assert str(pos["payoff"]["breakeven"]) in rep.narrative_markdown
    assert "Breakeven at expiry" in rep.narrative_markdown


def test_report_queries_follow_the_payload(report: Any) -> None:
    _rep, final = report
    qs = report_queries(final["explain_payload"])
    assert qs[0] == "what is a cash-secured put"
    assert "how this app's quality gate works" in qs
    assert "Reg T margin requirement for a naked put" in qs  # margin account
    assert len(qs) == len(set(qs))
    cash_only = {
        **final["explain_payload"],
        "profile": {"strategies": ["csp"], "account_type": "cash"},
    }
    assert "Reg T margin requirement for a naked put" not in report_queries(cash_only)


def test_select_sources_one_per_document_with_lead_chunk(deps: Deps) -> None:
    chunks, log = select_sources(
        deps.knowledge(), ["what is assignment", "what is theta", "what is assignment"], limit=6
    )
    docs = [c.doc_id for c in chunks]
    assert docs[:2] == ["assignment", "theta"] and len(docs) == len(set(docs))
    assert all(c.n == 0 for c in chunks)  # lead chunk = the definition
    assert len(log) == 3 and all(not r.empty for r in log)


def test_evidence_collection_from_trends(report: Any, deps: Deps) -> None:
    rep, final = report
    chunks = evidence_chunks(rep.trends)
    assert chunks and final["evidence"] == chunks
    assert all(c.kind == "evidence" and c.id == f"{c.doc_id}#{c.n}" for c in chunks)
    assert {c.doc_id for c in chunks} == {
        f"evidence-{re.sub(r'[^a-z0-9]+', '-', t.entity.lower()).strip('-')}"
        for t in rep.trends
        if t.evidence
    }
    # the Education agent searches it for questions: an entity name must come back as evidence
    entity = next(t for t in rep.trends if t.evidence).entity
    edu = build_agents(deps)["education_agent"]
    state = {**question_state(f"why is {entity} trending"), "evidence": chunks}
    out = edu.invoke(state)
    assert any(c.kind == "evidence" for c in out["sources"])


# -------------------------------------------------------------------------- concept Q&A


def test_question_gets_a_cited_answer_through_compliance(deps: Deps) -> None:
    final = answer_question(deps, "what is a cash-secured put", "t-qa-csp")
    answer: Narrative = final["answer"]
    assert answer.paragraphs[0].mode == "education" and answer.paragraphs[0].citations == ["S1"]
    assert final["citations"][0].doc_id == "cash-secured-put"
    assert final["citations"][0].tag == "S1"
    assert final["verification"].passed and final["verification"].citations_checked >= 1
    assert answer.paragraphs[-1].mode == "notice"
    assert answer.paragraphs[-1].text == deps.cfg.settings.disclaimer
    assert final["agents_visited"] == ["education_agent", "compliance_agent"]
    assert final["nodes_visited"] == [
        "knowledge_retrieval_node",
        "concept_answer_node",
        "compliance_node",
    ]


def test_no_source_question_returns_the_fixed_sentence(deps: Deps) -> None:
    final = answer_question(deps, "xqzv blorptastic", "t-qa-none")
    answer: Narrative = final["answer"]
    assert answer.paragraphs[0].text == NO_SOURCE_SENTENCE
    assert final["sources"] == [] and final["citations"] == []
    assert final["verification"].passed
    assert any("no source above the floor" in e for e in final["errors"])
    assert not any(u.task == "answer_concept" for u in final["token_usage"])  # LLM not called


def test_qa_graph_retries_then_falls_back_when_the_answer_fails_compliance(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def bad_answer(question: str, sources: str, disclaimer: str) -> Narrative:
        calls["n"] += 1
        return Narrative(
            paragraphs=[
                Paragraph(mode="education", text="You should buy this, it is risk-free [S9].")
            ]
        )

    monkeypatch.setattr(deps.llm, "answer_concept", bad_answer)
    graph = build_qa_graph(deps)
    for _ in stream_run(graph, question_state("what is assignment"), "t-qa-bad"):
        pass
    final = graph.get_state(thread_config("t-qa-bad")).values
    assert calls["n"] == deps.cfg.settings.agent.max_explainer_retries + 1
    assert not final["verification"].passed
    assert "S9" in final["verification"].unknown_citations
    assert "risk-free" in final["verification"].banned_phrases_found
    assert final["agents_visited"].count("compliance_agent") == calls["n"]


# ------------------------------------------------------------------ rule-based stand-ins


def _sources() -> list[Any]:
    from options_scout.rag.chunking import chunk_documents
    from options_scout.rag.corpus import load_corpus

    docs = [d for d in load_corpus(REPO_ROOT / "knowledge") if d.id in ("assignment", "theta")]
    return [c for c in chunk_documents(docs) if c.n == 0]


def test_sources_block_round_trip_and_rule_answer() -> None:
    sources = _sources()
    block = render_sources_block(sources)
    parsed = parse_sources_block(block)
    assert [p["tag"] for p in parsed] == ["S1", "S2"]
    assert parsed[0]["text"] == sources[0].text and parsed[1]["title"] == sources[1].title
    answer = rule_answer_concept(
        f"copied exactly: DISCLAIMER\n<question>\nq\n</question>\n<sources>\n{block}\n</sources>"
    )
    assert [p.mode for p in answer.paragraphs] == ["education", "education", "notice"]
    assert answer.paragraphs[0].citations == ["S1"] and "[S2]" in answer.paragraphs[1].text
    assert answer.paragraphs[-1].text == "DISCLAIMER"
    empty = rule_answer_concept("copied exactly: D\n<sources>\n</sources>")
    assert empty.paragraphs[0].text == NO_SOURCE_SENTENCE


def test_rule_explain_is_grounded_including_quoted_sources(report: Any) -> None:
    _rep, final = report
    sources = _sources()
    payload = {
        **final["explain_payload"],
        "sources": [
            {"tag": f"S{i}", "title": c.title, "url": c.url, "kind": c.kind, "text": c.text}
            for i, c in enumerate(sources, start=1)
        ],
    }
    narrative = rule_explain(rule_prompt(payload, render_sources_block(sources)))
    v = verify_narrative(
        narrative.markdown, payload, disclaimer=payload["disclaimer"], source_count=len(sources)
    )
    assert v.passed, (v.ungrounded_numbers, v.unknown_citations)
    assert [p.mode for p in narrative.paragraphs][-1] == "notice"
    assert sum(p.mode == "education" for p in narrative.paragraphs) == 2


def test_citation_helpers() -> None:
    cites = [citation_of(c) for c in _sources()]
    n = Narrative(
        paragraphs=[
            Paragraph(mode="education", text="a [S2]", citations=["s2"]),
            Paragraph(mode="education", text="b [S1] and [S7]"),
        ]
    )
    resolved = resolve_citations(n, cites)
    assert [c.tag for c in resolved] == ["S1", "S2"]  # numbered in source order, S7 dropped
    assert all(isinstance(c, Citation) for c in resolved)
    assert unknown_source_tags("x [S1] y [S3] z [S3]", 2) == ["S3"]
    assert unknown_source_tags("no tags", 0) == []
    # a tag is never read as a number
    v = verify_narrative("Stated [S1].", {"sources": [{"text": "t"}]}, disclaimer="")
    assert v.numbers_checked == 0 and v.citations_checked == 1 and v.unknown_citations == []


# ------------------------------------------------------------------------ payoff goldens


def test_csp_payoff_golden() -> None:
    legs = payoff.csp_legs(90.0, 1.50)
    s = payoff.summarize_strategy(legs, spot=100.0)
    assert s.breakevens == [88.5]
    assert s.max_loss == pytest.approx(8850.0) and s.loss_at_zero == pytest.approx(-8850.0)
    assert s.max_gain == pytest.approx(150.0)
    assert payoff.payoff(legs, 95.0) == pytest.approx(150.0)
    assert payoff.payoff(legs, 80.0) == pytest.approx(-850.0)


def test_long_call_payoff_golden() -> None:
    legs = payoff.long_call_legs(70.0, 33.0)
    s = payoff.summarize_strategy(legs, spot=100.0)
    assert s.breakevens == [103.0] and s.max_loss == pytest.approx(3300.0)
    assert s.max_gain is None  # unbounded
    assert payoff.payoff(legs, 120.0) == pytest.approx(1700.0)


def test_pmcc_payoff_golden() -> None:
    legs = payoff.pmcc_legs(70.0, 33.0, 110.0, 2.0)
    s = payoff.summarize_strategy(legs, spot=100.0)
    assert s.breakevens == [101.0]  # LEAPS strike + net debit (33 − 2)
    assert s.max_loss == pytest.approx(3100.0)
    assert s.max_gain == pytest.approx(900.0)  # (110 − 70 − 31) × 100
    assert payoff.payoff(legs, 150.0) == pytest.approx(900.0)


def test_payoff_scales_with_contracts_and_grid_rejects_bad_input() -> None:
    one = payoff.summarize_strategy(payoff.csp_legs(50.0, 1.0, 1))
    three = payoff.summarize_strategy(payoff.csp_legs(50.0, 1.0, 3))
    assert three.max_loss == pytest.approx(3 * one.max_loss) and three.breakevens == one.breakevens
    with pytest.raises(ValueError):
        payoff.grid(10.0, 5.0)
