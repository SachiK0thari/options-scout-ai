"""Orchestrator (section 5.0, #0): intake → human_review interrupt loop until the profile is set.

Step 10.5 adds ``route_node`` (chat intents) here; today every run is a new screen.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import human_review, intake
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "orchestrator_agent"


def _route_after_intake(state: AgentState) -> str:
    # the node-level router names the Phase 9 successor; inside the subgraph that means "done"
    return END if intake.route_after_intake(state) == "regime_node" else "human_review"


def build_orchestrator_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("intake_node", timed_node("intake_node", intake.make(deps)))
    g.add_node("human_review", timed_node("human_review", human_review.make(deps)))
    g.add_edge(START, "intake_node")
    g.add_conditional_edges("intake_node", _route_after_intake, ["human_review", END])
    g.add_edge("human_review", "intake_node")
    return g.compile()
