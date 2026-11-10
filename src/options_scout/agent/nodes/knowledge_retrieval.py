"""knowledge_retrieval_node (Education, step 10.3): pick the ``[S1]…[Sn]`` sources for this run.

For a **question** the query is the question itself and the run's evidence collection is searched
too. For a **report** there is no question, so the queries are derived from what the payload
contains: the strategies screened, the flags and exclusion reasons present, the account type and
the regime. Each query contributes its best chunk; the result is one chunk per document, capped
at ``rag.report_sources``, so the explainer can teach each concept the report relies on.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.bottleneck_scout import fresh_snapshot
from options_scout.agent.nodes.evidence_retrieval import BOARD_DOC_ID, board_chunks
from options_scout.agent.state import AgentState
from options_scout.core.models import BottleneckSignal, ScreeningReport, UserProfile
from options_scout.rag.models import Chunk, Kind, Level, RetrievalResult, level_rank
from options_scout.rag.retriever import KnowledgeRetriever

RUN_FACTS_TITLE = "This run's screen"

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


AUDIENCE = {
    "beginner": (
        "beginner: define every options term on first use, give each Greek's plain meaning before "
        "its name, and keep sentences short"
    ),
    "intermediate": "intermediate: define unusual terms on first use",
    "advanced": "advanced: be concise; standard options vocabulary needs no definition",
}


def level_cap(profile: UserProfile | None) -> Level | None:
    """Reading-level cap for retrieval (Phase 12): a beginner is never shown an advanced document
    first; others see everything. The cap is a preference (see ``retrieve_capped``)."""
    if profile is not None and profile.knowledge_level == "beginner":
        return "intermediate"
    return None


def audience_for(profile: UserProfile | None) -> str:
    level = (profile.knowledge_level if profile is not None else None) or "intermediate"
    return AUDIENCE[level]


def retrieve_capped(
    retriever: KnowledgeRetriever,
    query: str,
    *,
    kind: Kind | None = None,
    top_k: int | None = None,
    max_level: Level | None = None,
) -> RetrievalResult:
    """``retrieve`` under a reading-level cap that is a preference, not a wall.

    Documents at or under the cap lead. When the best match in the whole corpus is written above
    the cap (the question is about an advanced topic: "what is gamma" from a beginner), the
    above-cap hits follow them in up to half of the slots, so a beginner is never shown an advanced
    document first and is never answered from the wrong document, or refused, when the right one
    exists.
    """
    if max_level is None:
        return retriever.retrieve(query, kind=kind, top_k=top_k)
    capped = retriever.retrieve(query, kind=kind, top_k=top_k, max_level=max_level)
    full = retriever.retrieve(query, kind=kind, top_k=top_k)
    cap = level_rank(max_level)
    if full.empty or level_rank(full.hits[0].chunk.level) <= cap:
        return capped  # the best match is already within the reader's level
    k = top_k or retriever.cfg.top_k
    above = [h for h in full.hits if level_rank(h.chunk.level) > cap][: max((k + 1) // 2, 1)]
    merged = [*capped.hits[: k - len(above)], *above]
    hits = [h.model_copy(update={"rank": rank}) for rank, h in enumerate(merged, start=1)]
    return capped.model_copy(update={"hits": hits})


def select_sources(
    retriever: KnowledgeRetriever,
    queries: list[str],
    *,
    limit: int,
    kinds: tuple[Kind | None, ...] = (None,),
    lead_chunk: bool = True,
    max_level: Level | None = None,
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
            result = retrieve_capped(retriever, query, kind=kind, top_k=3, max_level=max_level)
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


def run_facts_chunk(rep: ScreeningReport) -> Chunk:
    """The current report's computed facts as one ``evidence`` chunk a ``why`` answer can cite:
    quality-gate outcomes with reasons, the ranking, skipped candidates and sized positions."""
    lines = [
        f"Run {rep.run_id}: screen for a {rep.profile.account_type} account, "
        f"{rep.profile.risk_profile} profile."
    ]
    for q in rep.quality:
        if q.passed:
            lines.append(
                f"{q.ticker} passed the quality gate with quality score {round(q.score * 100)}."
            )
        else:
            lines.append(f"{q.ticker} was excluded by the quality gate: {'; '.join(q.reasons)}.")
    for r in rep.ranked[:10]:
        c = r.candidate
        bflags = [f for f in c.flags if f.startswith(("bottleneck", "catalyst"))]
        lines.append(
            f"Rank {r.rank}: {c.id} ({c.ticker}) final score {r.final_score:.2f}, option quality "
            f"{r.option_quality:.2f}, stock quality {r.quality_score:.2f}, consumer-trend score "
            f"{r.social_score:.0f}, bottleneck score {r.bottleneck_score:.0f}"
            + (f", flags {', '.join(bflags)}" if bflags else "")
            + "."
        )
    lines.extend(bottleneck_fact_lines(rep.bottlenecks, {r.candidate.ticker for r in rep.ranked}))
    for skipped in rep.portfolio.skipped:
        lines.append(f"Skipped in sizing: {skipped}.")
    for p in rep.portfolio.positions:
        lines.append(
            f"Position {p.candidate_id}: {p.contracts} contract(s), capital used "
            f"{p.capital_used:,.0f}, realistic loss {p.realistic_loss:,.0f}."
        )
    if not rep.portfolio.positions:
        lines.append("No position fit inside the risk constraints.")
    return Chunk(
        id="run-report#0",
        doc_id="run-report",
        n=0,
        kind="run",  # reserved: the answerers find the run facts by kind, never by title
        title=RUN_FACTS_TITLE,
        url="",
        source=f"computed results of run {rep.run_id}",
        as_of=rep.as_of.date(),
        heading="",
        text="\n".join(lines),
    )


def bottleneck_fact_lines(signals: Sequence[BottleneckSignal], tickers: set[str]) -> list[str]:
    """Why X ranks above Y (Phase 11): the bottleneck term of every ranked ticker the board knows,
    with its layer, the layer's thesis state and its flags; tickers off the board take the neutral
    50, which the ranking line already states."""
    out: list[str] = []
    best: dict[str, BottleneckSignal] = {}
    for s in signals:
        t = s.ticker or ""
        on_board = t in tickers and s.role == "supplier" and s.curated
        if on_board and (t not in best or s.score > best[t].score):
            best[t] = s
    for t, s in sorted(best.items(), key=lambda kv: -kv[1].score):
        state = "weakening" if s.thesis_weakening else "holding"
        flags = f"; flags {', '.join(s.flags)}" if s.flags else ""
        out.append(
            f"{t} bottleneck exposure: company score {s.score:.0f} from layer {s.layer_name} "
            f"(layer score {s.layer_score:.0f}, thesis {state}, exposure "
            f"{s.components.get('exposure', 0.0):.2f}){flags}."
        )
    return out


_BOTTLENECK_WORDS = re.compile(
    r"\b(?:bottleneck|shortage|supply chain|lead time|capacity|thesis|falsifier|tighten\w*"
    r"|easing)\b",
    re.IGNORECASE,
)


def board_question_tickers(question: str, signals: Sequence[BottleneckSignal]) -> set[str]:
    """Tickers in the question that sit on the bottleneck board (as suppliers)."""
    on_board = {s.ticker for s in signals if s.ticker and s.role == "supplier"}
    return {t for t in re.findall(r"\b[A-Z]{2,5}\b", question) if t in on_board}


def asks_about_board(question: str, signals: Sequence[BottleneckSignal]) -> bool:
    named = board_question_tickers(question, signals)
    return bool(named) or _BOTTLENECK_WORDS.search(question) is not None


def latest_board(deps: Deps) -> list[BottleneckSignal]:
    """The board for a question asked outside a screen (CLI ``--ask``, a fresh chat thread): the
    fresh snapshot, else a run of the engine. Never fatal; an empty list means no board."""
    if "bottleneck" in deps.disabled_sources:
        return []
    try:
        rows = fresh_snapshot(
            deps.bottlenecks(), deps.cfg.bottleneck.snapshot_max_age_hours, deps.md.now()
        )
        if rows is None:
            rows = deps.bottleneck().run().signals
        return list(rows)
    except Exception:
        return []


def board_sources(
    question: str, evidence: Sequence[Chunk], signals: Sequence[BottleneckSignal]
) -> list[Chunk]:
    """Deterministic attachments for a question that names board tickers: the board facts chunk
    and the leading (filing) evidence chunk of each named ticker's best layer, so the answer can
    quote the filing behind the score (4A.10) whatever the embedder ranks first."""
    named = board_question_tickers(question, signals)
    if not named:
        return []
    by_id = {c.id: c for c in evidence}
    out: list[Chunk] = []
    if (facts := by_id.get(f"{BOARD_DOC_ID}#0")) is not None:
        out.append(facts)
    for t in sorted(named):
        rows = [s for s in signals if s.ticker == t and s.role == "supplier"]
        if not rows:
            continue
        best = max(rows, key=lambda s: s.score)
        doc_id = f"bottleneck-{_slug(best.theme_id)}-{_slug(best.layer_id)}"
        lead = by_id.get(f"{doc_id}#0")
        if lead is not None and lead not in out:
            out.append(lead)
    return out


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "entity"


def why_rule_queries(question: str, rep: ScreeningReport) -> list[str]:
    """The rule a ``why`` question is really about: the gate for exclusions, the ranking for
    order, the sizing constraints for skipped or missing positions."""
    low = question.lower()
    tickers = set(re.findall(r"\b[A-Z]{2,5}\b", question))
    excluded = {q.ticker for q in rep.quality if not q.passed}
    queries: list[str] = []
    if tickers & excluded or any(w in low for w in ("exclud", "gate", "screened out", "not in")):
        queries.append("how this app's quality gate works")
    if any(w in low for w in ("rank", "above", "below", "first", "last", "order", "score")):
        queries.append("ranking weights option quality stock quality consumer trend bottleneck")
    if _BOTTLENECK_WORDS.search(question):
        queries.append("bottleneck arbitrage supply constraint signal re-orders only")
    if any(w in low for w in ("position", "skip", "only", "reserve", "cash", "size", "fit")):
        queries.append("portfolio risk constraints and sizing")
    if not queries:
        queries.append("how this app's quality gate works")
    return queries


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def knowledge_retrieval_node(state: AgentState) -> dict[str, Any]:
        retriever = deps.knowledge()
        question = (state.get("question") or "").strip()
        errors: list[str] = []
        cap = level_cap(state.get("profile"))
        if question:
            result = retrieve_capped(retriever, question, max_level=cap)
            log = [result]
            chunks = [h.chunk for h in result.hits]
            rep = state.get("report")
            if state.get("intent") == "why" and rep is not None:
                chunks.insert(0, run_facts_chunk(rep))  # S1: the facts the question is about
                rules, rule_log = select_sources(
                    retriever, why_rule_queries(question, rep), limit=2, max_level=cap
                )
                log.extend(rule_log)
                chunks.extend(c for c in rules if c.doc_id not in {x.doc_id for x in chunks})
            evidence = list(state.get("evidence") or [])
            board = list(state.get("bottlenecks") or [])
            if not evidence and rep is None:
                # outside a screen (CLI --ask, a fresh thread) the bottleneck board is still
                # public, dated evidence: attach it when the question is about it (Phase 11)
                board = latest_board(deps)
                if board and asks_about_board(question, board):
                    evidence = board_chunks(board)
                else:
                    board = []
            if evidence:
                ev = KnowledgeRetriever.in_memory(evidence, retriever.embedder, deps.cfg.rag)
                ev_result = ev.retrieve(question, top_k=2)
                log.append(ev_result)
                have = {c.id for c in chunks}
                for c in board_sources(question, evidence, board):
                    if c.id not in have:
                        chunks.append(c)
                        have.add(c.id)
                chunks.extend(h.chunk for h in ev_result.hits if h.chunk.id not in have)
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
            retriever, report_queries(payload), limit=deps.cfg.rag.report_sources, max_level=cap
        )
        if not chunks:
            errors.append("knowledge_retrieval: no sources retrieved; narrative will be uncited")
        return {"sources": chunks, "retrievals": log, "errors": errors}

    return knowledge_retrieval_node
