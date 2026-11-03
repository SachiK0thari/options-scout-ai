"""Education (section 5.0, #6): the LLM narrative written only from computed numbers.

Nothing it writes reaches the user directly: the parent graph routes it through Compliance.
Step 10.3 adds ``knowledge_retrieval_node`` and ``concept_answer_node`` here.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import explainer
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "education_agent"


def build_education_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("explainer_node", timed_node("explainer_node", explainer.make(deps)))
    g.add_edge(START, "explainer_node")
    g.add_edge("explainer_node", END)
    return g.compile()
