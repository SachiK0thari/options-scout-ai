"""Strategy (section 5.0, #3): screen CSP / LEAPS / PMCC candidates, then rank them."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import ranker, screener
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "strategy_agent"


def build_strategy_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("screener_node", timed_node("screener_node", screener.make(deps)))
    g.add_node("ranker_node", timed_node("ranker_node", ranker.make(deps)))
    g.add_edge(START, "screener_node")
    g.add_edge("screener_node", "ranker_node")
    g.add_edge("ranker_node", END)
    return g.compile()
