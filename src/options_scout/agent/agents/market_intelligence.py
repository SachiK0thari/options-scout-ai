"""Market Intelligence (section 5.0, #2): the consumer-trend board and its evidence.

Runs before Market Data because the universe node promotes curated names with a trend score.
``evidence_retrieval_node`` (step 10.3) turns the run's evidence posts into a retrievable
collection so later answers can cite the actual posts.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import evidence_retrieval, trend_scout
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "market_intelligence_agent"


def build_market_intelligence_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("trend_scout_node", timed_node("trend_scout_node", trend_scout.make(deps)))
    g.add_node(
        "evidence_retrieval_node",
        timed_node("evidence_retrieval_node", evidence_retrieval.make(deps)),
    )
    g.add_edge(START, "trend_scout_node")
    g.add_edge("trend_scout_node", "evidence_retrieval_node")
    g.add_edge("evidence_retrieval_node", END)
    return g.compile()
