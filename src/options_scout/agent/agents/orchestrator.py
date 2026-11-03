"""Orchestrator (section 5.0, #0): route the turn, then intake ⇄ human_review for screens.

``route_node`` classifies the turn (new_screen, refine_profile, concept, why, what_if,
off_topic). Screens continue to ``intake_node`` and, when the profile is incomplete or a review
was requested, to the ``human_review`` interrupt; ``what_if_node`` and ``redirect_node`` write
their deterministic replies here; concept and why questions leave the subgraph for Education. The
parent graph routes on ``intent`` after this agent finishes.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import human_review, intake, redirect, route, what_if
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "orchestrator_agent"


def _route_after_intake(state: AgentState) -> str:
    # the node-level router names the Phase 9 successor; inside the subgraph that means "done"
    return END if intake.route_after_intake(state) == "regime_node" else "human_review"


def _after_route(state: AgentState) -> str:
    nxt = route.route_after_route(state)
    return END if nxt == "__end__" else nxt


def build_orchestrator_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("route_node", timed_node("route_node", route.make(deps)))
    g.add_node("intake_node", timed_node("intake_node", intake.make(deps)))
    g.add_node("human_review", timed_node("human_review", human_review.make(deps)))
    g.add_node("what_if_node", timed_node("what_if_node", what_if.make(deps)))
    g.add_node("redirect_node", timed_node("redirect_node", redirect.make(deps)))
    g.add_edge(START, "route_node")
    g.add_conditional_edges(
        "route_node", _after_route, ["intake_node", "what_if_node", "redirect_node", END]
    )
    g.add_conditional_edges("intake_node", _route_after_intake, ["human_review", END])
    g.add_edge("human_review", "intake_node")
    g.add_edge("what_if_node", END)
    g.add_edge("redirect_node", END)
    return g.compile()
