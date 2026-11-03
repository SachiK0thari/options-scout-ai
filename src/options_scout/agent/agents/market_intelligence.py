"""Market Intelligence (section 5.0, #2): the consumer-trend board.

Runs before Market Data because the universe node promotes curated names with a trend score.
Step 10.3 adds ``evidence_retrieval_node`` here.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import trend_scout
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "market_intelligence_agent"


def build_market_intelligence_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("trend_scout_node", timed_node("trend_scout_node", trend_scout.make(deps)))
    g.add_edge(START, "trend_scout_node")
    g.add_edge("trend_scout_node", END)
    return g.compile()
