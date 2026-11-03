"""evidence_retrieval_node (Market Intelligence, step 10.3): the run's evidence as a collection.

Every evidence post behind a trend signal becomes one ``evidence`` chunk (``evidence-<entity>#n``)
so later questions ("why is COST ranked above WMT") can cite the actual posts. The chunks live in
state, which the checkpointer persists per thread; ``KnowledgeRetriever.in_memory`` rebuilds the
searchable collection from them on demand, so nothing is cached outside the thread.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.models import TrendSignal
from options_scout.rag.models import Chunk


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "entity"


def evidence_chunks(trends: list[TrendSignal]) -> list[Chunk]:
    out: list[Chunk] = []
    for t in trends:
        doc_id = f"evidence-{_slug(t.entity)}"
        label = f"{t.entity}" + (f" ({t.ticker})" if t.ticker else "")
        for n, item in enumerate(t.evidence):
            where = f"r/{item.subreddit}" if item.subreddit else item.source
            out.append(
                Chunk(
                    id=f"{doc_id}#{n}",
                    doc_id=doc_id,
                    n=n,
                    kind="evidence",
                    title=f"Trend evidence: {label}",
                    url=item.url or "",
                    source=f"{item.source} post {item.post_id} in {where}, score {item.score}",
                    as_of=item.date,
                    heading=f"score {round(t.score)}",
                    text=item.excerpt,
                )
            )
    return out


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def evidence_retrieval_node(state: AgentState) -> dict[str, Any]:
        chunks = evidence_chunks(list(state.get("trends") or []))
        return {"evidence": chunks}

    return evidence_retrieval_node
