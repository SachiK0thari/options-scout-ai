"""tax_retrieval_node (Tax & Accounts, Phase 12 step 12.6): the ``[S1]…[Sn]`` tax sources.

Searches the ``tax`` collection first (IRS Publication 550, the statutes, FINRA account rules as
summarised in ``knowledge/tax/``), one chunk per document, and falls back to the options concepts
when a question is really about mechanics (Reg T, assignment) rather than tax.
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
}


def expand(question: str) -> str:
    """The question plus the document vocabulary its words point at."""
    words = re.findall(r"[a-z0-9-]+", question.lower())
    extra = " ".join(_EXPANSIONS[w] for w in words if w in _EXPANSIONS)
    return f"{question} {extra}".strip()


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def tax_retrieval_node(state: AgentState) -> dict[str, Any]:
        question = (state.get("tax_text") or state.get("message") or "").strip()
        retriever = deps.knowledge()
        log: list[RetrievalResult] = []
        chosen: list[Chunk] = []
        seen: set[str] = set()
        for kind, query in (
            ("tax", question),
            ("tax", expand(question)),
            ("concepts", expand(question)),
        ):
            result = retriever.retrieve(query, kind=kind, top_k=6)  # type: ignore[arg-type]
            log.append(result)
            for hit in result.hits:
                if hit.chunk.doc_id in seen:
                    continue
                seen.add(hit.chunk.doc_id)
                chosen.append(hit.chunk)
                if len(chosen) >= MAX_SOURCES:
                    break
            if chosen:
                break  # tax documents answer tax questions; concepts are only the fallback
        return {"question": question, "sources": chosen, "retrievals": log}

    return tax_retrieval_node
