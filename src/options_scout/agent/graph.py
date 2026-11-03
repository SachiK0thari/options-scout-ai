"""Parent graph (sections 5.0/5.1): specialist subgraphs + report, SQLite checkpointer, streaming.

Phase 9 wired the fourteen nodes directly; Phase 10 groups them into eight specialist subgraphs
(``agent/agents/``) and composes those here. Node bodies are unchanged, so the report content is
identical; only the agent order (Market Intelligence before Market Data, because the universe is
ordered by trend score) and the ``verifier_node`` → ``compliance_node`` rename show in the trace.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
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
    market_data,
    market_intelligence,
    orchestrator,
    portfolio,
    risk,
    strategy,
)
from options_scout.agent.agents.base import compose
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import report
from options_scout.agent.state import AgentState
from options_scout.core.models import utcnow
from options_scout.observability import timed_node

# Specialists in execution order (parent-graph node names).
AGENT_ORDER = [
    orchestrator.NAME,
    market_intelligence.NAME,
    market_data.NAME,
    strategy.NAME,
    portfolio.NAME,
    risk.NAME,
    education.NAME,
    compliance.NAME,
]

# Node-level order of a run (used by the UI progress bar); human_review only on interrupt.
NODE_ORDER = [
    "intake_node",
    "human_review",
    "trend_scout_node",
    "regime_node",
    "universe_node",
    "market_data_node",
    "screener_node",
    "ranker_node",
    "allocator_node",
    "sizing_node",
    "risk_node",
    "explainer_node",
    "compliance_node",
    "report_node",
]

AGENT_OF_NODE = {
    "intake_node": orchestrator.NAME,
    "human_review": orchestrator.NAME,
    "trend_scout_node": market_intelligence.NAME,
    "regime_node": market_data.NAME,
    "universe_node": market_data.NAME,
    "market_data_node": market_data.NAME,
    "screener_node": strategy.NAME,
    "ranker_node": strategy.NAME,
    "allocator_node": portfolio.NAME,
    "sizing_node": portfolio.NAME,
    "risk_node": risk.NAME,
    "explainer_node": education.NAME,
    "compliance_node": compliance.NAME,
}


def _model_types() -> list[type]:
    import inspect

    from pydantic import BaseModel

    from options_scout.core import models

    return [
        obj
        for _, obj in inspect.getmembers(models, inspect.isclass)
        if issubclass(obj, BaseModel) and obj.__module__ == models.__name__
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
        portfolio.NAME: portfolio.build_portfolio_agent(deps),
        risk.NAME: risk.build_risk_agent(deps),
        education.NAME: education.build_education_agent(deps),
        compliance.NAME: compliance.build_compliance_agent(deps),
    }


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    agents = build_agents(deps)
    g: StateGraph[AgentState] = StateGraph(AgentState)
    for name, compiled in agents.items():
        g.add_node(name, compose(name, compiled))
    g.add_node("report_node", timed_node("report_node", report.make(deps)))

    g.add_edge(START, orchestrator.NAME)
    g.add_edge(orchestrator.NAME, market_intelligence.NAME)
    g.add_edge(market_intelligence.NAME, market_data.NAME)
    g.add_edge(market_data.NAME, strategy.NAME)
    g.add_edge(strategy.NAME, portfolio.NAME)
    g.add_edge(portfolio.NAME, risk.NAME)
    g.add_conditional_edges(risk.NAME, risk.make_router(deps), [portfolio.NAME, education.NAME])
    g.add_edge(education.NAME, compliance.NAME)
    g.add_conditional_edges(
        compliance.NAME, compliance.make_router(deps), [education.NAME, "report_node"]
    )
    g.add_edge("report_node", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver(serde=serializer()))


def sqlite_checkpointer(path: Path) -> BaseCheckpointSaver[Any]:
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver: BaseCheckpointSaver[Any] = SqliteSaver(conn, serde=serializer())
    return saver


def initial_state(request_text: str = "", profile: dict[str, Any] | None = None) -> AgentState:
    run_id = uuid.uuid4().hex[:12]
    return AgentState(
        request_text=request_text,
        profile_override=profile,
        run_id=run_id,
        started_at=utcnow().isoformat(),
        trends=[],
        social_scores={},
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
