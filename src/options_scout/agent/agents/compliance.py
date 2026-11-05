"""Compliance (section 5.0, C): the eight checks of 13.1 plus the audit log; the only path to the
user.

``compliance_node`` evaluates the text this run produced (report narrative or concept answer) and
``audit_node`` persists the outcome. A blocking failure goes back to Education with specific
feedback (bounded); after the retry budget the report node (reports) or the audit node (answers)
falls back to deterministic text that is checked again.
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import audit, compliance
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "compliance_agent"

_NEXT = {"explainer_node": "education_agent", "report_node": "report_node"}
GOAL_WRITER = "goal_planning_agent"  # Phase 12: a goal turn's text is rewritten by its own agent


def build_compliance_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("compliance_node", timed_node("compliance_node", compliance.make(deps)))
    g.add_node("audit_node", timed_node("audit_node", audit.make(deps)))
    g.add_edge(START, "compliance_node")
    g.add_edge("compliance_node", "audit_node")
    g.add_edge("audit_node", END)
    return g.compile()


def make_router(deps: Deps) -> Callable[[AgentState], str]:
    """Parent-graph edge after Compliance: retry Education (bounded) or release the report."""
    node_router = compliance.make_router(deps)

    def route_after_compliance_agent(state: AgentState) -> str:
        nxt = _NEXT[node_router(state)]
        if nxt == "education_agent" and state.get("intent") == "goal":
            return GOAL_WRITER
        if nxt == "education_agent" and state.get("intent") == "holdings":
            return "portfolio_agent"  # its reply is deterministic; the retry budget still bounds it
        if nxt == "education_agent" and state.get("intent") == "news":
            return "news_desk_agent"
        if nxt == "education_agent" and state.get("intent") == "tax":
            return "tax_agent"
        if nxt == "report_node" and compliance.text_kind(state) == "answer":
            return END  # chat replies and concept answers have no report to assemble
        return nxt

    return route_after_compliance_agent
