"""Phase 12 step 12.7: knowledge level on the profile, the retrieval cap, audience-aware prompts,
the market overview strip's numbers and the glossary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ui import compute, glossary

from options_scout.agent.deps import Deps
from options_scout.agent.graph import build_graph, initial_state, stream_run, thread_config
from options_scout.agent.nodes.human_review import PROFILE_FIELDS
from options_scout.agent.nodes.intake import profile_from_parse
from options_scout.agent.nodes.knowledge_retrieval import (
    AUDIENCE,
    audience_for,
    level_cap,
    retrieve_capped,
)
from options_scout.agent.nodes.route import apply_changes
from options_scout.api.schemas import RecommendRequest
from options_scout.config import AppConfig, load_config
from options_scout.core.models import UserProfile
from options_scout.data.cache import MemoryCache
from options_scout.data.market import FixtureSource, MarketData
from options_scout.llm.rules import parse_knowledge_level, rule_parse_profile, rule_route
from options_scout.rag.models import level_rank
from options_scout.rag.retriever import KnowledgeRetriever
from tests.conftest import REPO_ROOT


@pytest.fixture(scope="module")
def config_module() -> AppConfig:
    return load_config(REPO_ROOT)


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("I have never traded options, $40k cash account, conservative.", "beginner"),
        ("New to this. 60k, conservative, cash account.", "beginner"),
        ("I know the Greeks, skip the basics. 100k margin, aggressive.", "advanced"),
        ("I know the basics and have traded a few options. 50k cash, balanced.", "intermediate"),
        ("$50k cash account, conservative, CSPs only.", None),
    ],
)
def test_knowledge_level_is_parsed_from_the_request(text: str, level: str | None) -> None:
    assert parse_knowledge_level(text) == level
    parsed = rule_parse_profile(text)
    assert parsed.knowledge_level == level


def test_level_cap_and_audience() -> None:
    base = {
        "buying_power": 1e4,
        "account_value": 1e4,
        "account_type": "cash",
        "risk_profile": "balanced",
    }
    beginner = UserProfile(**base, knowledge_level="beginner")
    advanced = UserProfile(**base, knowledge_level="advanced")
    assert level_cap(beginner) == "intermediate" and level_cap(advanced) is None
    assert level_cap(None) is None
    assert audience_for(beginner) == AUDIENCE["beginner"]
    assert audience_for(None) == AUDIENCE["intermediate"]
    assert "define every options term" in AUDIENCE["beginner"]


def test_review_answer_can_set_or_change_the_level() -> None:
    parsed = rule_parse_profile("New to this. 60k, conservative, cash account.")
    assert "knowledge_level" in PROFILE_FIELDS
    kept = profile_from_parse(parsed)
    assert kept is not None and kept.knowledge_level == "beginner"
    edited = profile_from_parse(parsed, {"knowledge_level": "advanced"})
    assert edited is not None and edited.knowledge_level == "advanced"


@pytest.mark.parametrize(
    ("message", "has_report", "intent", "changes"),
    [
        # after a screen, stating a level re-runs the same profile at that level
        ("Treat me as a complete novice.", True, "refine_profile", {"knowledge_level": "beginner"}),
        (
            "Actually switch to a margin account, and I know the Greeks.",
            True,
            "refine_profile",
            {"account_type": "margin", "knowledge_level": "advanced"},
        ),
        # the level never turns a question into a profile change
        ("I'm new to this, what is a put?", True, "concept", {}),
        ("I'm new to options. What is assignment?", False, "concept", {}),
    ],
)
def test_router_carries_a_stated_level_into_a_refinement(
    message: str, has_report: bool, intent: str, changes: dict[str, Any]
) -> None:
    context = "a report exists" if has_report else "a report does not exist yet"
    decision = rule_route(f"<message>\n{message}\n</message>\nContext: {context}")
    assert decision.intent == intent
    assert decision.profile_changes == changes
    if intent == "refine_profile":
        base = UserProfile(
            buying_power=5e4, account_value=5e4, account_type="cash", risk_profile="balanced"
        )
        assert (
            apply_changes(base, decision.profile_changes)["knowledge_level"]
            == (changes["knowledge_level"])
        )


def test_api_request_carries_the_level_into_the_profile() -> None:
    request = RecommendRequest(buying_power=40_000, knowledge_level="beginner")
    assert request.to_profile().knowledge_level == "beginner"
    assert RecommendRequest(buying_power=40_000).to_profile().knowledge_level is None


# ------------------------------------------------------------------------------ retrieval cap
@pytest.fixture(scope="module")
def retriever(config_module: AppConfig) -> KnowledgeRetriever:
    return KnowledgeRetriever.from_config(config_module)


def test_cap_holds_when_the_best_match_is_within_it(retriever: KnowledgeRetriever) -> None:
    capped = retrieve_capped(retriever, "what is a cash-secured put", max_level="intermediate")
    assert capped.hits[0].chunk.doc_id == "cash-secured-put"
    assert all(h.chunk.level != "advanced" for h in capped.hits)
    assert capped.max_level == "intermediate"
    # no cap is plain retrieval
    query = "implied volatility skew and term structure"
    assert retrieve_capped(retriever, query).hits == retriever.retrieve(query).hits


@pytest.mark.parametrize(
    ("query", "doc_id", "cap"),
    [
        ("what is gamma", "gamma", "intermediate"),
        ("what is IV rank", "iv-rank", "intermediate"),
        ("implied volatility skew and term structure", "iv-skew-and-term-structure", "beginner"),
    ],
)
def test_an_advanced_topic_is_answered_but_never_leads(
    retriever: KnowledgeRetriever, query: str, doc_id: str, cap: Any
) -> None:
    """The cap is a preference: the on-topic advanced document follows the easier ones."""
    result = retrieve_capped(retriever, query, max_level=cap)
    above = [level_rank(h.chunk.level) > level_rank(cap) for h in result.hits]
    assert above[0] is False, "an above-cap document is never S1 when an easier one matched"
    assert above == sorted(above), "under-cap hits first, then above-cap"
    assert doc_id in {h.chunk.doc_id for h in result.hits}
    assert [h.rank for h in result.hits] == list(range(1, len(result.hits) + 1))
    assert len(result.hits) <= retriever.cfg.top_k


def test_a_topic_with_nothing_under_the_cap_is_not_refused(retriever: KnowledgeRetriever) -> None:
    query = "Kelly criterion position sizing"
    assert retriever.retrieve(query, max_level="beginner").empty
    result = retrieve_capped(retriever, query, max_level="beginner")
    assert result.hits and result.hits[0].chunk.doc_id == "position-sizing-debate"


# ----------------------------------------------------------------------------- in the graph
@pytest.fixture(scope="module")
def deps(config_module: AppConfig, tmp_path_factory: pytest.TempPathFactory) -> Deps:
    from options_scout.social.pipeline import TrendStore

    d = Deps.from_config(config_module)
    d.trend_store = TrendStore(tmp_path_factory.mktemp("trends") / "t.sqlite")
    return d


PROFILE = {
    "buying_power": 60_000.0,
    "account_value": 60_000.0,
    "account_type": "cash",
    "risk_profile": "conservative",
    "strategies": ["csp"],
}


def _screen(deps: Deps, level: str, thread: str) -> tuple[dict[str, Any], list[str]]:
    """Run a screen at ``level``; returns the final state and the explainer's user prompts."""
    prompts: list[str] = []
    complete = deps.llm.provider.complete

    def spy(**kwargs: Any) -> Any:
        if kwargs["task"] == "explain_report":
            prompts.append(kwargs["user"])
        return complete(**kwargs)

    deps.llm.provider.complete = spy  # type: ignore[method-assign]
    try:
        graph = build_graph(deps)
        for _ in stream_run(
            graph, initial_state("", {**PROFILE, "knowledge_level": level}), thread
        ):
            pass
        return graph.get_state(thread_config(thread)).values, prompts
    finally:
        deps.llm.provider.complete = complete  # type: ignore[method-assign]


def test_a_beginner_screen_caps_retrieval_and_tells_the_explainer(deps: Deps) -> None:
    final, prompts = _screen(deps, "beginner", "t-level-beginner")
    assert final["report"].profile.knowledge_level == "beginner"
    assert final["retrievals"] and all(r.max_level == "intermediate" for r in final["retrievals"])
    assert final["sources"][0].level != "advanced"
    assert prompts and all(f"Reader level: {AUDIENCE['beginner']}." in p for p in prompts)
    assert final["report"].compliance.passed

    advanced, adv_prompts = _screen(deps, "advanced", "t-level-advanced")
    assert all(r.max_level is None for r in advanced["retrievals"])
    assert adv_prompts and all(f"Reader level: {AUDIENCE['advanced']}." in p for p in adv_prompts)

    def n_advanced(state: dict[str, Any]) -> int:
        return sum(c.level == "advanced" for c in state["sources"])

    assert n_advanced(final) < n_advanced(advanced), "the cap changes which documents are cited"


# ------------------------------------------------------------------- market overview strip
def test_day_change_uses_the_previous_close() -> None:
    # the series already ends on today's bar (after the close, or a recorded fixture)
    assert compute.day_change(102.0, [99.0, 100.0, 102.0]) == pytest.approx(0.02)
    # the series ends on yesterday's close (intraday)
    assert compute.day_change(102.0, [99.0, 100.0]) == pytest.approx(0.02)
    assert compute.day_change(102.0, []) is None
    assert compute.day_change(102.0, [102.0]) is None


def test_data_age_in_both_modes() -> None:
    fetched = datetime(2026, 11, 5, 14, 2, tzinfo=UTC)
    now = fetched + timedelta(minutes=14, seconds=40)
    assert compute.data_age(False, fetched, now) == "fixture, recorded 2026-11-05"
    assert compute.data_age(True, fetched, now) == "delayed quotes, fetched 14:02 UTC (14 min ago)"
    assert compute.data_age(True, None, now) == "no quotes fetched"


class _LiveLike(FixtureSource):
    """The recorded data served under a live provider's name, 14 minutes after it was fetched."""

    name = "tradier"

    def now(self) -> datetime:
        return super().now() + timedelta(minutes=14)


def test_strip_shows_quotes_change_and_age_in_fixture_and_live_mode(
    config_module: AppConfig,
) -> None:
    md = MarketData.from_config(config_module, mode="fixture")
    recorded = md.get_spot("SPY").as_of
    spy = md.build_snapshot("SPY")
    strip = compute.market_strip(md, {"SPY": spy}, None)
    assert [q.ticker for q in strip.quotes] == ["SPY", "QQQ"]
    by = {q.ticker: q for q in strip.quotes}
    assert by["SPY"].in_run and not by["QQQ"].in_run  # QQQ was looked up for the strip
    closes = md.get_close_history("SPY", 90)
    assert by["SPY"].price == spy.spot.price
    assert by["SPY"].change == pytest.approx(spy.spot.price / closes[-2] - 1.0)
    assert by["QQQ"].price is not None and by["QQQ"].change is not None
    assert not strip.live and strip.provider == "fixture"
    assert strip.age == f"fixture, recorded {recorded:%Y-%m-%d}"

    store = md.source.store  # type: ignore[attr-defined]
    live = MarketData(_LiveLike(store), MemoryCache(), md.ttl)
    strip = compute.market_strip(live, {}, None)
    oldest = min(live.get_spot(t).as_of for t in compute.STRIP_TICKERS)
    minutes = int((live.now() - oldest).total_seconds() // 60)
    assert strip.live and strip.provider == "tradier" and strip.fetched_at == oldest
    assert strip.age == f"delayed quotes, fetched {oldest:%H:%M} UTC ({minutes} min ago)"
    assert 0 < minutes <= 14

    class _Down(_LiveLike):
        def get_spot(self, ticker: str) -> Any:
            raise RuntimeError("provider down")

    strip = compute.market_strip(MarketData(_Down(store), MemoryCache(), md.ttl), {}, None)
    assert all(q.price is None for q in strip.quotes) and strip.age == "no quotes fetched"


# ------------------------------------------------------------------------------- glossary
def test_every_glossary_term_resolves_to_a_definition_and_a_document() -> None:
    for label, term in glossary.TERMS.items():
        text = glossary.help_for(label)
        assert text and len(text) > 20, label
        if term.doc_id is not None:
            doc = glossary.document(term.doc_id)
            assert doc is not None, f"{label}: no knowledge document {term.doc_id}"
            assert doc.kind in glossary.COLLECTIONS
            assert glossary.short_title(doc.title) in text, "the tooltip names the Learn page"


def test_lead_sentence_is_one_whole_sentence() -> None:
    body = "# Bills\n\nA **Treasury bill** is a short-term loan to the U.S. Treasury. It pays…"
    assert (
        glossary.lead_sentence(body) == "A Treasury bill is a short-term loan to the U.S. Treasury."
    )
    assert glossary.definition("delta").startswith("Delta measures how much an option's price")
    assert glossary.definition("no-such-document") == ""
