"""Graph wiring (section 5.1): StateGraph + Send fan-out + interrupt + SQLite checkpointer."""

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

from options_scout.agent.deps import Deps
from options_scout.agent.nodes import (
    allocator,
    explainer,
    human_review,
    intake,
    market_data,
    ranker,
    regime,
    report,
    risk,
    screener,
    sizing,
    trend_scout,
    universe,
)
from options_scout.agent.nodes import verifier as verifier_node
from options_scout.agent.state import AgentState
from options_scout.core.models import utcnow
from options_scout.observability import timed_node

NODE_ORDER = [
    "intake_node",
    "human_review",
    "regime_node",
    "allocator_node",
    "trend_scout_node",
    "universe_node",
    "market_data_node",
    "screener_node",
    "ranker_node",
    "sizing_node",
    "risk_node",
    "explainer_node",
    "verifier_node",
    "report_node",
]


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


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("intake_node", timed_node("intake_node", intake.make(deps)))
    g.add_node("human_review", timed_node("human_review", human_review.make(deps)))
    g.add_node("regime_node", timed_node("regime_node", regime.make(deps)))
    g.add_node("allocator_node", timed_node("allocator_node", allocator.make(deps)))
    g.add_node("trend_scout_node", timed_node("trend_scout_node", trend_scout.make(deps)))
    g.add_node("universe_node", timed_node("universe_node", universe.make(deps)))
    g.add_node("market_data_node", timed_node("market_data_node", market_data.make(deps)))
    g.add_node("screener_node", timed_node("screener_node", screener.make(deps)))
    g.add_node("ranker_node", timed_node("ranker_node", ranker.make(deps)))
    g.add_node("sizing_node", timed_node("sizing_node", sizing.make(deps)))
    g.add_node("risk_node", timed_node("risk_node", risk.make(deps)))
    g.add_node("explainer_node", timed_node("explainer_node", explainer.make(deps)))
    g.add_node("verifier_node", timed_node("verifier_node", verifier_node.make(deps)))
    g.add_node("report_node", timed_node("report_node", report.make(deps)))

    g.add_edge(START, "intake_node")
    g.add_conditional_edges(
        "intake_node", intake.route_after_intake, ["human_review", "regime_node"]
    )
    g.add_edge("human_review", "intake_node")
    g.add_edge("regime_node", "allocator_node")
    g.add_edge("allocator_node", "trend_scout_node")
    g.add_edge("trend_scout_node", "universe_node")
    g.add_conditional_edges(
        "universe_node", universe.fan_out, ["market_data_node", "screener_node"]
    )
    g.add_edge("market_data_node", "screener_node")
    g.add_edge("screener_node", "ranker_node")
    g.add_edge("ranker_node", "sizing_node")
    g.add_edge("sizing_node", "risk_node")
    g.add_conditional_edges("risk_node", risk.make_router(deps), ["sizing_node", "explainer_node"])
    g.add_edge("explainer_node", "verifier_node")
    g.add_conditional_edges(
        "verifier_node", verifier_node.make_router(deps), ["explainer_node", "report_node"]
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
        token_usage=[],
        data_source_status={},
    )


def thread_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def stream_run(graph: Any, state: AgentState, thread_id: str) -> Iterator[dict[str, Any]]:
    """Yield node updates ``{node_name: partial_state}`` until the graph ends or interrupts."""
    yield from graph.stream(state, thread_config(thread_id), stream_mode="updates")


def stream_resume(graph: Any, thread_id: str, answer: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield from graph.stream(Command(resume=answer), thread_config(thread_id), stream_mode="updates")


def pending_interrupt(graph: Any, thread_id: str) -> dict[str, Any] | None:
    snap = graph.get_state(thread_config(thread_id))
    for task in getattr(snap, "tasks", ()):
        for intr in getattr(task, "interrupts", ()):
            value = getattr(intr, "value", None)
            if isinstance(value, dict):
                return value
    return None
