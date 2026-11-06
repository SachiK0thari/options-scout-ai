"""tax_retrieval_node (Tax & Accounts, Phase 12 step 12.6): the ``[S1]…[Sn]`` tax sources.

Searches the ``tax`` collection (IRS Publication 550, the statutes, FINRA account rules as
summarised in ``knowledge/tax/``) with the question as asked and with the question expanded into
the documents' vocabulary, fuses the two rankings at document level, and keeps one chunk per
document. The options concepts are the fallback when a question is really about mechanics (Reg T,
assignment) rather than tax.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.rag.models import Chunk, RetrievalResult

MAX_SOURCES = 4
# question words → the vocabulary the tax documents use (the lexical embedder has no stemming)
_EXPANSIONS: dict[str, str] = {
    "taxes": "tax taxed taxable",
    "taxed": "tax taxable",
    "assigned": "assignment assigned shares basis",
    "assignment": "assigned shares cost basis",
    "basis": "cost basis",
    "expires": "expiration expired premium",
    "expire": "expiration expired premium",
    "ira": "ira margin cash-secured",
    "roth": "roth ira",
    "wash": "wash sale window",
    "1256": "section 1256 contracts",
    "1099": "form 1099-b 8949",
    "8949": "form 8949 1099-b",
    "long-term": "holding period long-term",
    "long": "holding period long-term",
    "leaps": "leaps holding period exercise",
    "covered": "qualified covered call holding period",
    "account": "account types cash margin ira",
    "naked": "naked margin account",
    "withdrawal": "early distribution additional tax",
    "day": "pattern day trading",
    "6781": "form 6781 section 1256 contracts",
}


def expand(question: str) -> str:
    """The question plus the document vocabulary its words point at."""
    words = re.findall(r"[a-z0-9-]+", question.lower())
    extra = " ".join(_EXPANSIONS[w] for w in words if w in _EXPANSIONS)
    return f"{question} {extra}".strip()


def fuse_documents(results: list[RetrievalResult], limit: int) -> list[Chunk]:
    """One chunk per document, documents ordered by reciprocal-rank fusion over ``results``.

    A document's rank in a result is the position of its best chunk among that result's
    documents; its score is the sum of 1 / rank over the results that found it. The chunk kept is
    the best one from the result that ranked the document highest (the earlier result on a tie).
    """
    score: dict[str, float] = {}
    best: dict[str, tuple[int, Chunk]] = {}
    for result in results:
        rank = 0
        seen: set[str] = set()
        for hit in result.hits:
            doc = hit.chunk.doc_id
            if doc in seen:
                continue
            seen.add(doc)
            rank += 1
            score[doc] = score.get(doc, 0.0) + 1.0 / rank
            if doc not in best or rank < best[doc][0]:
                best[doc] = (rank, hit.chunk)
    order = sorted(score, key=lambda d: (-score[d], best[d][0], d))
    return [best[d][1] for d in order[:limit]]


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def tax_retrieval_node(state: AgentState) -> dict[str, Any]:
        question = (state.get("tax_text") or state.get("message") or "").strip()
        retriever = deps.knowledge()
        expanded = expand(question)
        # the question as asked, then in the documents' vocabulary; both rankings count
        log: list[RetrievalResult] = [
            retriever.retrieve(query, kind="tax", top_k=6)
            for query in dict.fromkeys((question, expanded))
        ]
        chosen = fuse_documents(log, MAX_SOURCES)
        if not chosen:  # tax documents answer tax questions; concepts are only the fallback
            fallback = retriever.retrieve(expanded, kind="concepts", top_k=6)
            log.append(fallback)
            chosen = fuse_documents([fallback], MAX_SOURCES)
        return {"question": question, "sources": chosen, "retrievals": log}

    return tax_retrieval_node
