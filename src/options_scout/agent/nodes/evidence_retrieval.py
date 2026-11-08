"""evidence_retrieval_node (Market Intelligence, step 10.3): the run's evidence as a collection.

Every evidence post behind a trend signal becomes one ``evidence`` chunk (``evidence-<entity>#n``)
so later questions ("why is COST ranked above WMT") can cite the actual posts. Phase 11 (4A.10)
adds the bottleneck evidence pack the same way: one document per layer
(``bottleneck-<theme>-<layer>#n``, filings first) plus one *board facts* chunk that states every
layer and curated-supplier score, so "why is HON ranked above UNP" can quote the filing excerpt
and the computed scores. The chunks live in state, which the checkpointer persists per thread;
``KnowledgeRetriever.in_memory`` rebuilds the searchable collection from them on demand, so
nothing is cached outside the thread.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.models import BOTTLENECK_BOARD_DOC_ID, BottleneckSignal, TrendSignal
from options_scout.rag.models import Chunk

BOARD_FACTS_TITLE = "Bottleneck board (secondary signal)"
BOARD_DOC_ID = BOTTLENECK_BOARD_DOC_ID  # compliance check 7 reads the snapshot date off this id
_KIND_ORDER = {"filing": 0, "headline": 1, "post": 2, "price": 3}


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


def _suppliers_in(signals: Sequence[BottleneckSignal], theme_id: str, layer_id: str) -> list[str]:
    return sorted(
        {
            s.ticker
            for s in signals
            if s.ticker
            and s.role == "supplier"
            and (s.theme_id, s.layer_id) == (theme_id, layer_id)
        }
    )


def bottleneck_evidence_chunks(signals: Sequence[BottleneckSignal]) -> list[Chunk]:
    """The evidence pack of every layer (4A.10) as ``evidence`` chunks, filings first. The chunk
    text is the stored excerpt; the layer and its suppliers go in the heading so a question that
    names a ticker finds the layer's evidence without altering the quote."""
    out: list[Chunk] = []
    for row in signals:
        if row.ticker is not None or not row.evidence:
            continue
        doc_id = f"bottleneck-{_slug(row.theme_id)}-{_slug(row.layer_id)}"
        suppliers = _suppliers_in(signals, row.theme_id, row.layer_id)
        items = sorted(row.evidence, key=lambda e: (_KIND_ORDER.get(e.kind, 9), e.date))
        for n, item in enumerate(items):
            who = f" filed by {item.filer_ticker}" if item.filer_ticker else ""
            out.append(
                Chunk(
                    id=f"{doc_id}#{n}",
                    doc_id=doc_id,
                    n=n,
                    kind="evidence",
                    title=f"Bottleneck evidence: {row.layer_name}",
                    url=item.url or "",
                    source=f"{item.source} {item.kind}{who}, {item.date.isoformat()}"
                    + (f", label {item.label}" if item.label else ""),
                    as_of=item.date,
                    heading=f"{row.layer_name} · suppliers {', '.join(suppliers) or 'none'}",
                    text=item.excerpt,
                )
            )
    return out


def board_facts_chunk(signals: Sequence[BottleneckSignal]) -> Chunk | None:
    """One ``evidence`` chunk with the board's computed numbers (layer scores, thesis state,
    curated-supplier company scores and flags), so a ``why`` answer can report them."""
    layers = [s for s in signals if s.ticker is None]
    if not layers:
        return None
    lines = [
        "Bottleneck board: a secondary signal that re-orders quality-gated stocks, never adds one."
    ]
    for row in sorted(layers, key=lambda s: -s.score):
        state = "thesis weakening" if row.thesis_weakening else "thesis holding"
        lines.append(
            f"Layer {row.layer_name} ({row.theme_id}/{row.layer_id}): layer score "
            f"{row.score:.0f}, {state}."
        )
    companies = sorted(
        (s for s in signals if s.ticker and s.role == "supplier"), key=lambda s: -s.score
    )
    seen: set[str] = set()
    for s in companies:
        if s.ticker in seen:
            continue
        seen.add(s.ticker or "")
        tag = "on the good-to-own list" if s.curated else "not on the good-to-own list"
        flags = f"; flags {', '.join(s.flags)}" if s.flags else ""
        lines.append(
            f"{s.ticker}: bottleneck company score {s.score:.0f} in layer {s.layer_name} "
            f"(exposure {s.components.get('exposure', 0.0):.2f}), {tag}{flags}."
        )
    as_of = max(s.as_of for s in layers)
    return Chunk(
        id=f"{BOARD_DOC_ID}#0",
        doc_id=BOARD_DOC_ID,
        n=0,
        kind="evidence",
        title=BOARD_FACTS_TITLE,
        url="",
        source=f"bottleneck engine snapshot {as_of:%Y-%m-%d}",
        as_of=as_of.date(),
        heading="",
        text="\n".join(lines),
    )


def board_chunks(signals: Sequence[BottleneckSignal]) -> list[Chunk]:
    """Board facts first, then the evidence pack."""
    facts = board_facts_chunk(signals)
    return ([facts] if facts else []) + bottleneck_evidence_chunks(signals)


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def evidence_retrieval_node(state: AgentState) -> dict[str, Any]:
        chunks = evidence_chunks(list(state.get("trends") or []))
        chunks += board_chunks(list(state.get("bottlenecks") or []))
        return {"evidence": chunks}

    return evidence_retrieval_node
