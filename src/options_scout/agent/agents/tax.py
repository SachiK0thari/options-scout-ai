"""Tax & Accounts (Phase 12, #9): how a CSP, LEAPS or PMCC is taxed and which accounts allow it.

``tax_retrieval_node`` → ``tax_math_node`` → ``tax_answer_node``. Education, never tax advice:
the reply cites IRS Publication 550, the statutes and FINRA pages from ``knowledge/tax/``,
illustrates with a screened candidate's own numbers computed by ``core/tax.py``, and carries the
tax disclaimer; Compliance check 11 rejects a stated rate or a filing instruction. A Compliance
retry re-enters at the writer.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import tax_answer, tax_math, tax_retrieval
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "tax_agent"


def _entry(state: AgentState) -> str:
    if state.get("intent") != "tax":
        return "tax_math_node"  # inside a screen: only the illustrative facts, no reply
    retrying = int((state.get("retries") or {}).get("explainer", 0)) > 0
    return "tax_answer_node" if retrying and state.get("sources") else "tax_retrieval_node"


def _after_math(state: AgentState) -> str:
    return "tax_answer_node" if state.get("intent") == "tax" else END


def build_tax_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("tax_retrieval_node", timed_node("tax_retrieval_node", tax_retrieval.make(deps)))
    g.add_node("tax_math_node", timed_node("tax_math_node", tax_math.make(deps)))
    g.add_node("tax_answer_node", timed_node("tax_answer_node", tax_answer.make(deps)))
    g.add_conditional_edges(
        START, _entry, ["tax_retrieval_node", "tax_math_node", "tax_answer_node"]
    )
    g.add_edge("tax_retrieval_node", "tax_math_node")
    g.add_conditional_edges("tax_math_node", _after_math, ["tax_answer_node", END])
    g.add_edge("tax_answer_node", END)
    return g.compile()
