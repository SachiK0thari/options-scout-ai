"""Portfolio (section 5.0, #4): allocate buying power, then size positions under the constraints.

Phase 12 (12.4) adds what the user already owns: ``holdings_intake_node`` reads a ``holdings``
chat turn, ``holdings_analysis_node`` values the positions (allocation, sector weights, HHI,
expense ratios, beta, covered-call lots, concentration after assignment) and, inside a screen that
carries holdings, feeds the seventh sizing constraint; ``holdings_reply_node`` writes the reply
to the chat turn. When the Risk agent sends the run back (sizing retry), only ``sizing_node``
re-runs: the allocation is a pure function of profile and regime.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import (
    allocator,
    holdings_analysis,
    holdings_intake,
    holdings_reply,
    sizing,
)
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "portfolio_agent"


def _entry(state: AgentState) -> str:
    if state.get("intent") == "holdings":
        return "holdings_intake_node"
    retrying = int((state.get("retries") or {}).get("sizing", 0)) > 0
    return "sizing_node" if retrying else "allocator_node"


def _after_allocator(state: AgentState) -> str:
    return "holdings_analysis_node" if state.get("holdings") else "sizing_node"


def _after_analysis(state: AgentState) -> str:
    return "holdings_reply_node" if state.get("intent") == "holdings" else "sizing_node"


def build_portfolio_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("allocator_node", timed_node("allocator_node", allocator.make(deps)))
    g.add_node("sizing_node", timed_node("sizing_node", sizing.make(deps)))
    g.add_node(
        "holdings_intake_node", timed_node("holdings_intake_node", holdings_intake.make(deps))
    )
    g.add_node(
        "holdings_analysis_node",
        timed_node("holdings_analysis_node", holdings_analysis.make(deps)),
    )
    g.add_node("holdings_reply_node", timed_node("holdings_reply_node", holdings_reply.make(deps)))
    g.add_conditional_edges(
        START, _entry, ["allocator_node", "sizing_node", "holdings_intake_node"]
    )
    g.add_conditional_edges(
        "allocator_node", _after_allocator, ["holdings_analysis_node", "sizing_node"]
    )
    g.add_edge("holdings_intake_node", "holdings_analysis_node")
    g.add_conditional_edges(
        "holdings_analysis_node", _after_analysis, ["holdings_reply_node", "sizing_node"]
    )
    g.add_edge("holdings_reply_node", END)
    g.add_edge("sizing_node", END)
    return g.compile()
