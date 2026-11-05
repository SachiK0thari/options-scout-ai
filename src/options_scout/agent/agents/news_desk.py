"""News Desk (Phase 12, #8): headlines become flags on candidates and per-ticker briefs.

``news_fetch_node`` → ``news_classify_node`` → ``news_brief_node``. Inside a screen the agent runs
after Strategy (it needs the candidates for the calendar flags) and before Portfolio; on a
``news`` chat turn it answers alone and Compliance checks the reply (check 10 verifies every quoted
headline). Headlines never enter the ranking: the 15% cap on non-economic signals stays intact.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from options_scout.agent.agents.base import CompiledGraph
from options_scout.agent.deps import Deps
from options_scout.agent.nodes import news_brief, news_classify, news_fetch
from options_scout.agent.state import AgentState
from options_scout.observability import timed_node

NAME = "news_desk_agent"


def _entry(state: AgentState) -> str:
    retrying = int((state.get("retries") or {}).get("explainer", 0)) > 0
    return "news_brief_node" if retrying and state.get("news_classified") else "news_fetch_node"


def build_news_desk_agent(deps: Deps) -> CompiledGraph:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    g.add_node("news_fetch_node", timed_node("news_fetch_node", news_fetch.make(deps)))
    g.add_node("news_classify_node", timed_node("news_classify_node", news_classify.make(deps)))
    g.add_node("news_brief_node", timed_node("news_brief_node", news_brief.make(deps)))
    g.add_conditional_edges(START, _entry, ["news_fetch_node", "news_brief_node"])
    g.add_edge("news_fetch_node", "news_classify_node")
    g.add_edge("news_classify_node", "news_brief_node")
    g.add_edge("news_brief_node", END)
    return g.compile()
