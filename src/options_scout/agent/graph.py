"""Parent graph (sections 5.0/5.1): specialist subgraphs + report, SQLite checkpointer, streaming.

Phase 9 wired the fourteen nodes directly; Phase 10 groups them into eight specialist subgraphs
(``agent/agents/``) and composes those here. Step 10.5 added intent routing after the Orchestrator:

* ``new_screen`` / ``refine_profile`` → Market Intelligence → … → Compliance → report_node
  (or END with a ``handoff`` when the thread already holds a report: the session starts the new
  screen on a fresh thread so list reducers never append one run onto another);
* ``concept`` / ``why`` → Education → Compliance → END (``answer`` + ``citations``);
* ``goal`` → Goal Planning → Compliance → END (Phase 12; a screen seeded with a ``goal`` also
  passes through Goal Planning between Risk and Education);
* ``holdings`` → Portfolio (intake, analysis, reply) → Compliance → END (Phase 12; a screen
  whose thread holds ``holdings`` analyses them after allocation and sizes under the seventh
  constraint);
* ``news`` → News Desk → Compliance → END (Phase 12; every screen also runs News Desk between
  Strategy and Portfolio for the calendar flags and per-ticker briefs);
* ``tax`` → Tax & Accounts → Compliance → END (Phase 12; check 11 on the reply);
* ``what_if`` / ``off_topic`` → the Orchestrator's own reply → Compliance → END.

Compliance retries Education (bounded) and otherwise releases a report to ``report_node`` or an
answer to END. ``agent/chat.py`` drives multi-turn conversations over this graph;
``ask_specialist`` runs one turn pinned to a Phase 12 specialist (the MCP tools of step 12.8).
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from options_scout.agent.agents import (
    compliance,
    education,
    goal_planning,
    market_data,
    market_intelligence,
    news_desk,
    orchestrator,
    portfolio,
    risk,
    strategy,
    tax,
)
from options_scout.agent.agents.base import compose
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import report
from options_scout.agent.nodes.route import SPECIALIST_TEXT
from options_scout.agent.state import AgentState
from options_scout.core.models import Intent, UserProfile, utcnow
from options_scout.observability import timed_node

# Specialists in execution order (parent-graph node names).
AGENT_ORDER = [
    orchestrator.NAME,
    market_intelligence.NAME,
    market_data.NAME,
    strategy.NAME,
    news_desk.NAME,  # Phase 12: headlines → flags and briefs, after the candidates exist
    portfolio.NAME,
    risk.NAME,
    goal_planning.NAME,  # Phase 12: runs when the turn or the screen carries a goal
    tax.NAME,  # Phase 12: chat-only, the `tax` intent
    education.NAME,
    compliance.NAME,
]

# Node-level order of a run (used by the UI progress bar); human_review only on interrupt.
NODE_ORDER = [
    "route_node",
    "intake_node",
    "human_review",
    "trend_scout_node",
    "bottleneck_scout_node",
    "evidence_retrieval_node",
    "regime_node",
    "universe_node",
    "market_data_node",
    "screener_node",
    "ranker_node",
    "news_fetch_node",
    "news_classify_node",
    "news_brief_node",
    "allocator_node",
    "sizing_node",
    "risk_node",
    "knowledge_retrieval_node",
    "explainer_node",
    "compliance_node",
    "audit_node",
    "report_node",
]
# chat-only nodes (not part of a screen's progress bar)
CHAT_NODES = [
    "what_if_node",
    "redirect_node",
    "concept_answer_node",
    "goal_intake_node",
    "goal_math_node",
    "goal_explainer_node",
    "holdings_intake_node",
    "holdings_analysis_node",
    "holdings_reply_node",
    "tax_retrieval_node",
    "tax_math_node",
    "tax_answer_node",
]

AGENT_OF_NODE = {
    "route_node": orchestrator.NAME,
    "intake_node": orchestrator.NAME,
    "human_review": orchestrator.NAME,
    "what_if_node": orchestrator.NAME,
    "redirect_node": orchestrator.NAME,
    "trend_scout_node": market_intelligence.NAME,
    "bottleneck_scout_node": market_intelligence.NAME,
    "evidence_retrieval_node": market_intelligence.NAME,
    "regime_node": market_data.NAME,
    "universe_node": market_data.NAME,
    "market_data_node": market_data.NAME,
    "screener_node": strategy.NAME,
    "ranker_node": strategy.NAME,
    "news_fetch_node": news_desk.NAME,
    "news_classify_node": news_desk.NAME,
    "news_brief_node": news_desk.NAME,
    "allocator_node": portfolio.NAME,
    "sizing_node": portfolio.NAME,
    "holdings_intake_node": portfolio.NAME,
    "holdings_analysis_node": portfolio.NAME,
    "holdings_reply_node": portfolio.NAME,
    "tax_retrieval_node": tax.NAME,
    "tax_math_node": tax.NAME,
    "tax_answer_node": tax.NAME,
    "risk_node": risk.NAME,
    "goal_intake_node": goal_planning.NAME,
    "goal_math_node": goal_planning.NAME,
    "goal_explainer_node": goal_planning.NAME,
    "knowledge_retrieval_node": education.NAME,
    "explainer_node": education.NAME,
    "concept_answer_node": education.NAME,
    "compliance_node": compliance.NAME,
    "audit_node": compliance.NAME,
}


def _model_types() -> list[type]:
    import inspect

    from pydantic import BaseModel

    from options_scout.core import models
    from options_scout.rag import models as rag_models

    return [
        obj
        for mod in (models, rag_models)
        for _, obj in inspect.getmembers(mod, inspect.isclass)
        if issubclass(obj, BaseModel) and obj.__module__ == mod.__name__
    ]


def serializer() -> JsonPlusSerializer:
    """Checkpoint serializer that explicitly trusts our own Pydantic models (and nothing else)."""
    return JsonPlusSerializer(allowed_msgpack_modules=_model_types())


def build_agents(deps: Deps) -> dict[str, Any]:
    """Every specialist as a standalone compiled subgraph, keyed by parent-graph node name."""
    return {
        orchestrator.NAME: orchestrator.build_orchestrator_agent(deps),
        market_intelligence.NAME: market_intelligence.build_market_intelligence_agent(deps),
        market_data.NAME: market_data.build_market_data_agent(deps),
        strategy.NAME: strategy.build_strategy_agent(deps),
        news_desk.NAME: news_desk.build_news_desk_agent(deps),
        portfolio.NAME: portfolio.build_portfolio_agent(deps),
        risk.NAME: risk.build_risk_agent(deps),
        goal_planning.NAME: goal_planning.build_goal_planning_agent(deps),
        tax.NAME: tax.build_tax_agent(deps),
        education.NAME: education.build_education_agent(deps),
        compliance.NAME: compliance.build_compliance_agent(deps),
    }


def route_after_orchestrator(state: AgentState) -> str:
    """Parent-graph edge after the Orchestrator (step 10.5), keyed on the routed ``intent``."""
    intent = state.get("intent") or "new_screen"
    if intent in ("concept", "why"):
        return education.NAME
    if intent == "goal":
        return goal_planning.NAME
    if intent == "holdings":
        return portfolio.NAME  # Phase 12: holdings analysis lives in the Portfolio agent
    if intent == "news":
        return news_desk.NAME
    if intent == "tax":
        return tax.NAME
    if intent in ("what_if", "off_topic"):
        return compliance.NAME
    if state.get("handoff"):
        return END  # the session starts the new screen on a fresh thread
    return market_intelligence.NAME


def route_after_risk(deps: Deps) -> Any:
    """Risk's own router (retry Portfolio or continue), with a detour through Goal Planning when
    the screen carries a goal (Phase 12)."""
    inner = risk.make_router(deps)

    def route(state: AgentState) -> str:
        nxt = inner(state)
        if nxt == education.NAME and state.get("goal") is not None:
            return goal_planning.NAME
        return nxt

    return route


def route_after_news_desk(state: AgentState) -> str:
    """A news chat turn ends in Compliance; inside a screen the pipeline continues to Portfolio."""
    return compliance.NAME if state.get("intent") == "news" else portfolio.NAME


def route_after_portfolio(state: AgentState) -> str:
    """A holdings chat turn ends in Compliance; inside a screen the pipeline continues to Risk."""
    return compliance.NAME if state.get("intent") == "holdings" else risk.NAME


def route_after_goal_planning(state: AgentState) -> str:
    """A goal chat turn goes straight to Compliance; inside a screen the pipeline continues."""
    return compliance.NAME if state.get("intent") == "goal" else education.NAME


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    agents = build_agents(deps)
    g: StateGraph[AgentState] = StateGraph(AgentState)
    for name, compiled in agents.items():
        g.add_node(name, compose(name, compiled))
    g.add_node("report_node", timed_node("report_node", report.make(deps)))

    g.add_edge(START, orchestrator.NAME)
    g.add_conditional_edges(
        orchestrator.NAME,
        route_after_orchestrator,
        [
            market_intelligence.NAME,
            education.NAME,
            goal_planning.NAME,
            portfolio.NAME,
            news_desk.NAME,
            tax.NAME,
            compliance.NAME,
            END,
        ],
    )
    g.add_edge(market_intelligence.NAME, market_data.NAME)
    g.add_edge(market_data.NAME, strategy.NAME)
    g.add_edge(strategy.NAME, news_desk.NAME)
    g.add_conditional_edges(
        news_desk.NAME, route_after_news_desk, [portfolio.NAME, compliance.NAME]
    )
    g.add_conditional_edges(portfolio.NAME, route_after_portfolio, [risk.NAME, compliance.NAME])
    g.add_conditional_edges(
        risk.NAME, route_after_risk(deps), [portfolio.NAME, goal_planning.NAME, education.NAME]
    )
    g.add_conditional_edges(
        goal_planning.NAME, route_after_goal_planning, [education.NAME, compliance.NAME]
    )
    g.add_edge(education.NAME, compliance.NAME)
    g.add_edge(tax.NAME, compliance.NAME)
    g.add_conditional_edges(
        compliance.NAME,
        compliance.make_router(deps),
        [
            education.NAME,
            goal_planning.NAME,
            portfolio.NAME,
            news_desk.NAME,
            tax.NAME,
            "report_node",
            END,
        ],
    )
    g.add_edge("report_node", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver(serde=serializer()))


def build_qa_graph(deps: Deps, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    """Kept from step 10.3: questions now run through the one routed graph (``build_graph``)."""
    return build_graph(deps, checkpointer)


def question_state(question: str) -> AgentState:
    state = initial_state()
    state["question"] = question
    return state


def answer_question(deps: Deps, question: str, thread_id: str | None = None) -> dict[str, Any]:
    """Run the Q&A graph; the final state holds ``answer``, ``citations`` and ``verification``."""
    graph = build_qa_graph(deps)
    thread = thread_id or f"qa-{uuid.uuid4().hex[:8]}"
    for _ in stream_run(graph, question_state(question), thread):
        pass
    values: dict[str, Any] = dict(graph.get_state(thread_config(thread)).values)
    if values.get("compliance") is None or not values.get("audit_log"):
        # 13.1: a reply without a compliance audit entry must be impossible
        raise RuntimeError("answer produced without a ComplianceReport; refusing to return it")
    return values


def next_turn_state(existing: Mapping[str, Any]) -> dict[str, Any]:
    """The per-turn keys of a thread that already ran, cleared for its next turn.

    Everything a turn's router and writers set is reset, so a new turn never inherits the
    previous one's intent, texts or answer; the compliance retry counter is per text and starts
    at zero. The caller adds the turn's own input (``message``, or one specialist text).
    """
    return {
        "message": None,
        "question": None,
        "answer": None,
        "intent": None,
        "handoff": None,
        "what_if_profile": None,
        "what_if_diff": [],
        "goal_text": None,
        "goal_clarification": None,
        "holdings_text": None,
        "news_text": None,
        "tax_text": None,
        "verifier_feedback": None,
        "retries": {**(existing.get("retries") or {}), "explainer": 0},
    }


def ask_specialist(
    graph: Any,
    intent: Intent,
    text: str,
    thread_id: str | None = None,
    *,
    profile: UserProfile | None = None,
) -> dict[str, Any]:
    """One turn addressed to a Phase 12 specialist (``goal``, ``holdings``, ``news``, ``tax``).

    The intent is pinned, not classified (``route_node``). On a thread that already holds state
    (a finished screen, say) the turn runs there, so the specialist sees the thread's profile,
    candidates and sized portfolio exactly as a chat turn would; on a new thread it starts from
    an empty state plus the optional ``profile``. The final state holds ``answer``, ``citations``
    and ``compliance``; like ``answer_question`` this refuses to return text that Compliance did
    not evaluate in this turn.
    """
    key = SPECIALIST_TEXT.get(intent)
    if key is None:
        raise ValueError(f"{intent!r} is not a specialist intent ({', '.join(SPECIALIST_TEXT)})")
    thread = thread_id or f"{intent}-{uuid.uuid4().hex[:8]}"
    existing: dict[str, Any] = dict(graph.get_state(thread_config(thread)).values or {})
    if existing:
        payload: dict[str, Any] = next_turn_state(existing)
    else:
        payload = dict(initial_state())
        if profile is not None:
            payload["profile"] = profile
    payload[key] = text
    audited = len(existing.get("audit_log") or [])
    for _ in stream_run(graph, payload, thread):  # type: ignore[arg-type]
        pass
    values: dict[str, Any] = dict(graph.get_state(thread_config(thread)).values)
    if values.get("compliance") is None or len(values.get("audit_log") or []) <= audited:
        # 13.1: a reply without a compliance audit entry of its own must be impossible
        raise RuntimeError(f"{intent} reply produced without a ComplianceReport; refusing it")
    return values


def sqlite_checkpointer(path: Path, retention_days: int = 0) -> BaseCheckpointSaver[Any]:
    """Open (or create) the SQLite checkpoint database at ``path``.

    A new file is created with ``auto_vacuum=INCREMENTAL`` so deleted threads give their pages
    back. With ``retention_days`` above zero (``agent.checkpoint_retention_days`` in
    ``config/settings.yaml``), every thread whose newest checkpoint is older than that is
    deleted on open and the freed pages are released; ``0`` keeps every thread.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    if conn.execute("PRAGMA page_count").fetchone()[0] == 0:
        # auto_vacuum can only be chosen before the first table exists
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    saver: BaseCheckpointSaver[Any] = SqliteSaver(conn, serde=serializer())
    saver.setup()  # type: ignore[attr-defined]
    if retention_days > 0:
        prune_stale_threads(conn, saver, retention_days)
    return saver


def prune_stale_threads(
    conn: sqlite3.Connection,
    saver: BaseCheckpointSaver[Any],
    retention_days: int,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Delete every thread whose newest checkpoint is older than ``retention_days``.

    The newest checkpoint per thread is the row with the largest ``checkpoint_id`` (the saver's
    own ordering; ids are time-ordered UUIDs) and its age is the checkpoint's ``ts`` field. A
    row that cannot be decoded is kept. Returns the deleted thread ids.
    """
    cutoff = (now or utcnow()) - timedelta(days=retention_days)
    rows = conn.execute(
        "SELECT thread_id, type, checkpoint, MAX(checkpoint_id) FROM checkpoints GROUP BY thread_id"
    ).fetchall()
    stale: list[str] = []
    for thread_id, type_, blob, _newest_id in rows:
        try:
            newest = datetime.fromisoformat(saver.serde.loads_typed((type_, blob))["ts"])
        except Exception:  # an unreadable checkpoint is never a reason to delete a thread
            continue
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=UTC)
        if newest < cutoff:
            stale.append(str(thread_id))
    for thread_id in stale:
        saver.delete_thread(thread_id)
    if stale:
        conn.execute("PRAGMA incremental_vacuum")
        conn.commit()
    return stale


def initial_state(request_text: str = "", profile: dict[str, Any] | None = None) -> AgentState:
    run_id = uuid.uuid4().hex[:12]
    return AgentState(
        request_text=request_text,
        profile_override=profile,
        run_id=run_id,
        started_at=utcnow().isoformat(),
        trends=[],
        social_scores={},
        bottlenecks=[],
        bottleneck_scores={},
        evidence=[],
        sources=[],
        retrievals=[],
        citations=[],
        audit_log=[],
        chat_history=[],
        what_if_diff=[],
        universe=[],
        market_data={},
        quality={},
        candidates=[],
        pmcc_pairs=[],
        ranked=[],
        retries={},
        errors=[],
        nodes_visited=[],
        node_latency_ms={},
        agents_visited=[],
        agent_latency_ms={},
        token_usage=[],
        data_source_status={},
    )


def thread_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _flatten(stream: Iterator[tuple[tuple[str, ...], dict[str, Any]]]) -> Iterator[dict[str, Any]]:
    """Node-level updates from inside the specialists, then the specialist's own update.

    Consumers see ``{node_name: partial_state}`` exactly as in Phase 9, plus one
    ``{agent_name: delta}`` when a specialist finishes. An interrupt is reported once, at the root.
    """
    for namespace, update in stream:
        if namespace:
            inner = {k: v for k, v in update.items() if k != "__interrupt__"}
            if inner:
                yield inner
        else:
            yield update


def stream_run(graph: Any, state: AgentState, thread_id: str) -> Iterator[dict[str, Any]]:
    """Yield node updates ``{node_name: partial_state}`` until the graph ends or interrupts."""
    yield from _flatten(
        graph.stream(state, thread_config(thread_id), stream_mode="updates", subgraphs=True)
    )


def stream_resume(graph: Any, thread_id: str, answer: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield from _flatten(
        graph.stream(
            Command(resume=answer),
            thread_config(thread_id),
            stream_mode="updates",
            subgraphs=True,
        )
    )


def pending_interrupt(graph: Any, thread_id: str) -> dict[str, Any] | None:
    snap = graph.get_state(thread_config(thread_id))
    for task in getattr(snap, "tasks", ()):
        for intr in getattr(task, "interrupts", ()):
            value = getattr(intr, "value", None)
            if isinstance(value, dict):
                return value
    return None
