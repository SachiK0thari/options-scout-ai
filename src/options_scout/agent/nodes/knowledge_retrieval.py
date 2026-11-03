"""knowledge_retrieval_node (Education, step 10.3): pick the ``[S1]…[Sn]`` sources for this run.

For a **question** the query is the question itself and the run's evidence collection is searched
too. For a **report** there is no question, so the queries are derived from what the payload
contains: the strategies screened, the flags and exclusion reasons present, the account type and
the regime. Each query contributes its best chunk; the result is one chunk per document, capped
at ``rag.report_sources``, so the explainer can teach each concept the report relies on.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.rag.models import Chunk, Kind, RetrievalResult
from options_scout.rag.retriever import KnowledgeRetriever

_STRATEGY_QUERIES: dict[str, list[str]] = {
    "csp": ["what is a cash-secured put", "what is assignment"],
    "leaps": ["what is a LEAPS call", "intrinsic and extrinsic value"],
    "pmcc": ["how does a poor man's covered call work"],
}
_FLAG_QUERIES: dict[str, str] = {
    "earnings": "earnings risk for short options before expiry",
    "hv_proxy": "IV rank and the HV proxy fallback",
    "dte_outside_preferred": "days to expiration window for cash-secured puts",
    "roll": "rolling or closing a LEAPS below the roll warning",
    "spread": "bid-ask spread and open interest liquidity rules",
}
_REASON_QUERIES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"volatil|hv30|iv", re.I), "quality gate realised and implied volatility limits"),
    (re.compile(r"high|drawdown|below", re.I), "quality gate distance below the 90-day high"),
    (re.compile(r"price|volume|liquid", re.I), "quality gate price and average volume limits"),
    (re.compile(r"history|closes|data", re.I), "quality gate price history requirement"),
]


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.append(it)
    return seen


def report_queries(payload: dict[str, Any]) -> list[str]:
    """Concept queries implied by a report payload, most important first."""
    queries: list[str] = []
    strategies = [str(s) for s in payload.get("profile", {}).get("strategies", [])]
    for s in strategies:
        queries.extend(_STRATEGY_QUERIES.get(s, []))
    if payload.get("profile", {}).get("account_type") in ("margin", "portfolio_margin"):
        queries.append("Reg T margin requirement for a naked put")
    queries.append("how this app's quality gate works")
    excluded = payload.get("quality_screen", {}).get("excluded", [])
    for item in excluded[:4]:
        for reason in item.get("reasons", [])[:2]:
            for pattern, query in _REASON_QUERIES:
                if pattern.search(str(reason)):
                    queries.append(query)
                    break
    flags: set[str] = set()
    for t in payload.get("trends", []):
        flags.update(str(f) for f in t.get("flags", []))
    for w in payload.get("risk", {}).get("warnings", []):
        low = str(w).lower()
        for key in _FLAG_QUERIES:
            if key.replace("_", " ") in low or key in low:
                flags.add(key)
    for key in sorted(flags):
        if key in _FLAG_QUERIES:
            queries.append(_FLAG_QUERIES[key])
    if payload.get("trends"):
        queries.append("why hype is a risk for short puts")
    queries.append("volatility regime VIX percentile allocation tilt")
    queries.append("probability of expiring out of the money and delta")
    return _dedupe(queries)


def select_sources(
    retriever: KnowledgeRetriever,
    queries: list[str],
    *,
    limit: int,
    kinds: tuple[Kind | None, ...] = (None,),
    lead_chunk: bool = True,
) -> tuple[list[Chunk], list[RetrievalResult]]:
    """One source per query, one per document, in query order, up to ``limit``.

    With ``lead_chunk`` the document's first chunk (its definition) is attached instead of the
    best-matching span, which is what an education paragraph in a report should quote.
    """
    chosen: list[Chunk] = []
    seen_docs: set[str] = set()
    log: list[RetrievalResult] = []
    for query in queries:
        for kind in kinds:
            result = retriever.retrieve(query, kind=kind, top_k=3)
            log.append(result)
            for hit in result.hits:
                if hit.chunk.doc_id in seen_docs:
                    continue
                seen_docs.add(hit.chunk.doc_id)
                lead = retriever.store.get(f"{hit.chunk.doc_id}#0") if lead_chunk else None
                chosen.append(lead or hit.chunk)
                break
        if len(chosen) >= limit:
            break
    return chosen[:limit], log


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def knowledge_retrieval_node(state: AgentState) -> dict[str, Any]:
        retriever = deps.knowledge()
        question = (state.get("question") or "").strip()
        errors: list[str] = []
        if question:
            result = retriever.retrieve(question)
            log = [result]
            chunks = [h.chunk for h in result.hits]
            evidence = state.get("evidence") or []
            if evidence:
                ev = KnowledgeRetriever.in_memory(evidence, retriever.embedder, deps.cfg.rag)
                ev_result = ev.retrieve(question, top_k=2)
                log.append(ev_result)
                chunks.extend(h.chunk for h in ev_result.hits)
            if not chunks:
                errors.append(f"knowledge_retrieval: no source above the floor for {question!r}")
            return {"sources": chunks, "retrievals": log, "errors": errors}
        payload = state.get("explain_payload") or {}
        if not payload:
            from options_scout.agent.nodes.explainer import build_explain_payload

            payload = build_explain_payload(
                state, deps.cfg.settings.disclaimer, loss_drop=deps.cfg.risk.realistic_loss_drop
            )
        chunks, log = select_sources(
            retriever, report_queries(payload), limit=deps.cfg.rag.report_sources
        )
        if not chunks:
            errors.append("knowledge_retrieval: no sources retrieved; narrative will be uncited")
        return {"sources": chunks, "retrievals": log, "errors": errors}

    return knowledge_retrieval_node
