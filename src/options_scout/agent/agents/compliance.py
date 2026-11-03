"""Compliance (section 5.0, C): numeric grounding + language policy; the only path to the user.

A failed narrative goes back to Education with specific feedback (bounded); after the retry
budget the report node falls back to a deterministic narrative. Step 10.4 adds the remaining
checks of section 13.1 and ``audit_node``.
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import compliance
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "compliance_agent"

_NEXT = {"explainer_node": "education_agent", "report_node": "report_node"}


def build_compliance_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("compliance_node", timed_node("compliance_node", compliance.make(deps)))
    g.add_edge(START, "compliance_node")
    g.add_edge("compliance_node", END)
    return g.compile()


def make_router(deps: Deps) -> Callable[[AgentState], str]:
    """Parent-graph edge after Compliance: retry Education (bounded) or release the report."""
    node_router = compliance.make_router(deps)

    def route_after_compliance_agent(state: AgentState) -> str:
        return _NEXT[node_router(state)]

    return route_after_compliance_agent
