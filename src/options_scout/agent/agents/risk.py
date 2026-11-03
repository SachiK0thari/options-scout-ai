"""Risk (section 5.0, #5): constraint checks + stress tests; may send the run back to Portfolio.

Step 10.4 adds ``suitability_facts`` to this slice so Compliance never recomputes anything.
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import risk
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "risk_agent"

# the node-level router names Phase 9 nodes; the parent graph routes between agents
_NEXT_AGENT = {"sizing_node": "portfolio_agent", "explainer_node": "education_agent"}


def build_risk_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("risk_node", timed_node("risk_node", risk.make(deps)))
    g.add_edge(START, "risk_node")
    g.add_edge("risk_node", END)
    return g.compile()


def make_router(deps: Deps) -> Callable[[AgentState], str]:
    """Parent-graph edge after the Risk agent: retry sizing (bounded) or hand over to Education."""
    node_router = risk.make_router(deps)

    def route_after_risk_agent(state: AgentState) -> str:
        return _NEXT_AGENT[node_router(state)]

    return route_after_risk_agent
