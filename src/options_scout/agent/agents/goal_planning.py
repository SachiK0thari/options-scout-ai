"""Goal Planning (Phase 12, #7): does the goal fit this account under this risk profile?

``goal_intake_node`` parses the goal, ``goal_math_node`` runs ``core.goals.plan_goal`` on the
thread's sized portfolio (or on cash alone), and ``goal_explainer_node`` writes the cited
narrative. On a ``goal`` chat turn the narrative goes to Compliance (check 9); inside a screen
whose state already carries a ``goal`` the agent only computes the plan, which the report and the
explainer payload pick up, so the explainer is skipped. A Compliance retry re-enters at the writer.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import goal_explainer, goal_intake, goal_math
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "goal_planning_agent"


def _entry(state: AgentState) -> str:
    retrying = int((state.get("retries") or {}).get("explainer", 0)) > 0
    if retrying and (state.get("goal_plan") is not None or state.get("goal_clarification")):
        return "goal_explainer_node"
    if state.get("intent") != "goal" and state.get("goal") is not None:
        return "goal_math_node"  # a screen seeded with a goal: no chat text to parse
    return "goal_intake_node"


def _after_math(state: AgentState) -> str:
    return "goal_explainer_node" if state.get("intent") == "goal" else END


def build_goal_planning_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("goal_intake_node", timed_node("goal_intake_node", goal_intake.make(deps)))
    g.add_node("goal_math_node", timed_node("goal_math_node", goal_math.make(deps)))
    g.add_node("goal_explainer_node", timed_node("goal_explainer_node", goal_explainer.make(deps)))
    g.add_conditional_edges(
        START, _entry, ["goal_intake_node", "goal_math_node", "goal_explainer_node"]
    )
    g.add_edge("goal_intake_node", "goal_math_node")
    g.add_conditional_edges("goal_math_node", _after_math, ["goal_explainer_node", END])
    g.add_edge("goal_explainer_node", END)
    return g.compile()
