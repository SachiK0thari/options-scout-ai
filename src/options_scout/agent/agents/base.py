"""Composition helper: a compiled specialist subgraph becomes one node of the parent graph."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeAlias

from langchain_core.runnables import RunnableConfig

from options_scout.agent.state import state_delta
from options_scout.observability import timed_agent

CompiledGraph: TypeAlias = Any  # langgraph's CompiledStateGraph; generics differ across versions
AgentNode: TypeAlias = Callable[..., dict[str, Any]]  # (state, config) -> partial state


def subgraph_node(name: str, compiled: CompiledGraph) -> AgentNode:
    """Run ``compiled`` on the shared state and hand back only what it changed.

    A compiled subgraph added directly as a node returns its *whole* final state, and the
    parent's reducers then re-append the lists it was given (probed on LangGraph 1.2.18: an
    inherited ``errors`` entry came back twice). Invoking it here and returning ``state_delta``
    applies every reducer exactly once. Interrupts raised inside propagate to the parent, ``Send``
    fan-outs stay inside the subgraph, and the subgraph inherits the parent's checkpointer and
    thread through ``config``, so a paused Orchestrator resumes in place.
    """

    def node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        final = compiled.invoke(state, config)
        return state_delta(state, final)

    node.__name__ = name
    return node


def compose(name: str, compiled: CompiledGraph) -> AgentNode:
    """Parent-graph node for a specialist: subgraph + per-agent timing and audit events."""
    return timed_agent(name, subgraph_node(name, compiled))
