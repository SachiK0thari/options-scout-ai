"""Portfolio (section 5.0, #4): allocate buying power, then size positions under the constraints.

When the Risk agent sends the run back (sizing retry), only ``sizing_node`` re-runs: the
allocation is a pure function of profile and regime, so re-computing it would only add noise to
the trace.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import allocator, sizing
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "portfolio_agent"


def _entry(state: AgentState) -> str:
    retrying = int((state.get("retries") or {}).get("sizing", 0)) > 0
    return "sizing_node" if retrying else "allocator_node"


def build_portfolio_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("allocator_node", timed_node("allocator_node", allocator.make(deps)))
    g.add_node("sizing_node", timed_node("sizing_node", sizing.make(deps)))
    g.add_conditional_edges(START, _entry, ["allocator_node", "sizing_node"])
    g.add_edge("allocator_node", "sizing_node")
    g.add_edge("sizing_node", END)
    return g.compile()
