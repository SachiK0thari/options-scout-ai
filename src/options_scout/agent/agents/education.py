"""Education (section 5.0, #6): cited explanations and concept answers.

``knowledge_retrieval_node`` picks the ``[S1]…[Sn]`` sources, then either ``explainer_node``
(a screening report) or ``concept_answer_node`` (a question) writes tagged paragraphs. Nothing it
writes reaches the user directly: the parent graph routes it through Compliance, and on a
Compliance retry the agent re-enters at the writer with the sources it already has.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import concept_answer, explainer, knowledge_retrieval
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "education_agent"


def _writer(state: AgentState) -> str:
    return "concept_answer_node" if (state.get("question") or "").strip() else "explainer_node"


def _entry(state: AgentState) -> str:
    retrying = int((state.get("retries") or {}).get("explainer", 0)) > 0
    return _writer(state) if retrying and state.get("sources") else "knowledge_retrieval_node"


def build_education_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node(
        "knowledge_retrieval_node",
        timed_node("knowledge_retrieval_node", knowledge_retrieval.make(deps)),
    )
    g.add_node("explainer_node", timed_node("explainer_node", explainer.make(deps)))
    g.add_node("concept_answer_node", timed_node("concept_answer_node", concept_answer.make(deps)))
    g.add_conditional_edges(
        START, _entry, ["knowledge_retrieval_node", "explainer_node", "concept_answer_node"]
    )
    g.add_conditional_edges(
        "knowledge_retrieval_node", _writer, ["explainer_node", "concept_answer_node"]
    )
    g.add_edge("explainer_node", END)
    g.add_edge("concept_answer_node", END)
    return g.compile()
