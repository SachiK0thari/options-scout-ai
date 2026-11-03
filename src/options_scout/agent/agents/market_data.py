"""Market Data (section 5.0, #1): regime → universe → per-ticker snapshots + quality gate.

The ``Send`` fan-out over tickers lives inside this subgraph; tickers that fail the good-to-own
gate are recorded in ``quality`` with reasons and never reach ``market_data``.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import market_data, regime, universe
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "market_data_agent"


def _fan_out(state: AgentState) -> list[Send] | str:
    targets = universe.fan_out(state)
    return END if isinstance(targets, str) else targets  # empty universe: nothing to fetch


def build_market_data_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("regime_node", timed_node("regime_node", regime.make(deps)))
    g.add_node("universe_node", timed_node("universe_node", universe.make(deps)))
    g.add_node("market_data_node", timed_node("market_data_node", market_data.make(deps)))
    g.add_edge(START, "regime_node")
    g.add_edge("regime_node", "universe_node")
    g.add_conditional_edges("universe_node", _fan_out, ["market_data_node", END])
    g.add_edge("market_data_node", END)
    return g.compile()
