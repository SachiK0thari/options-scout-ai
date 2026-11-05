"""Hybrid retriever: dense cosine + BM25 fused by weighted reciprocal rank, with a ``kind`` filter
and a dense similarity floor. With a lexical embedder (``hash``) a chunk must also share at least
one content word with the query (``rag.require_shared_term``): a bag-of-words vector that shares no
word can only clear the floor by hash collision, which is what made "what is the weather in Boston"
cite the VIX document before the rule existed.

    python -m options_scout.rag.retriever "what is assignment" [--kind concepts] [--k 6]
        [--max-level beginner]

prints the cited chunks (the index is built on first use if ``data/knowledge.sqlite`` is missing
or stale for the current corpus and embedder).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from options_scout.config import COLLECTION_NAMES, AppConfig, RagConfig, load_config, load_env
from options_scout.rag.bm25 import BM25Index
from options_scout.rag.chunking import ChunkParams, chunk_documents
from options_scout.rag.corpus import load_corpus
from options_scout.rag.embeddings import Embedder, make_embedder, tokenize
from options_scout.rag.models import (
    LEVELS,
    Chunk,
    Kind,
    Level,
    RetrievalResult,
    ScoredChunk,
    level_rank,
)
from options_scout.rag.store import KnowledgeStore


def chunk_params(cfg: RagConfig) -> ChunkParams:
    return ChunkParams(chunk_tokens=cfg.chunk_tokens, overlap=cfg.overlap)


class KnowledgeRetriever:
    """Searches one :class:`KnowledgeStore`. Build with :meth:`from_config` for the committed
    corpus or with :meth:`in_memory` for a run's evidence posts."""

    def __init__(self, store: KnowledgeStore, embedder: Embedder, cfg: RagConfig) -> None:
        self.store = store
        self.embedder = embedder
        self.cfg = cfg
        self._bm25: BM25Index | None = None
        self._bm25_count = -1

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_config(cls, cfg: AppConfig, *, rebuild: bool = False) -> KnowledgeRetriever:
        """Open ``rag.index_db``; (re)index when missing, stale or ``rebuild`` is set."""
        embedder = make_embedder(cfg.rag)
        store = KnowledgeStore(cfg.rag.index_db)
        chunks = chunk_documents(load_corpus(cfg.rag.knowledge_dir), chunk_params(cfg.rag))
        if rebuild or not store.is_current(chunks, embedder):
            store.rebuild(chunks, embedder)
        return cls(store, embedder, cfg.rag)

    @classmethod
    def in_memory(
        cls, chunks: Sequence[Chunk], embedder: Embedder, cfg: RagConfig
    ) -> KnowledgeRetriever:
        store = KnowledgeStore(":memory:")
        store.rebuild(list(chunks), embedder)
        return cls(store, embedder, cfg)

    # ------------------------------------------------------------------ search
    def retrieve(
        self,
        query: str,
        *,
        kind: Kind | None = None,
        top_k: int | None = None,
        max_level: Level | None = None,
    ) -> RetrievalResult:
        """``kind`` restricts the collection; ``max_level`` drops chunks written above a reading
        level (a beginner profile never cites a margin or skew document first)."""
        k = top_k or self.cfg.top_k
        floor = self.cfg.floor
        chunks = self.store.chunks()
        empty = RetrievalResult(
            query=query, kind=kind, max_level=max_level, embedder=self.embedder.name, floor=floor
        )
        if not chunks or not query.strip():
            return empty
        qvec = self.embedder.embed([query])[0]
        dense = self.store.dense_scores(qvec)
        bm25 = self._bm25_index(chunks)
        lexical = bm25.scores(query)
        # lexical embedder: a chunk that shares no content word only matched by hash collision
        shares = bm25.shares_term(query) if self.cfg.shared_term_required else None

        cap = None if max_level is None else level_rank(max_level)
        eligible = [
            i
            for i, c in enumerate(chunks)
            if (kind is None or c.kind == kind)
            and (cap is None or level_rank(c.level) <= cap)
            and float(dense[i]) >= floor
            and (shares is None or bool(shares[i]))
        ]
        if not eligible:
            return empty

        fused = self._rrf(eligible, dense, lexical, chunks, query)
        order = sorted(eligible, key=lambda i: (-fused[i], -float(dense[i]), chunks[i].id))[:k]
        hits = [
            ScoredChunk(
                chunk=chunks[i],
                dense=round(float(dense[i]), 4),
                bm25=round(float(lexical[i]), 4),
                fused=round(fused[i], 6),
                rank=rank,
            )
            for rank, i in enumerate(order, start=1)
        ]
        return RetrievalResult(
            query=query,
            hits=hits,
            kind=kind,
            max_level=max_level,
            embedder=self.embedder.name,
            floor=floor,
        )

    def _rrf(
        self,
        eligible: list[int],
        dense: NDArray[np.float32],
        lexical: NDArray[np.float64],
        chunks: list[Chunk],
        query: str = "",
    ) -> dict[int, float]:
        """Weighted reciprocal-rank fusion over the eligible set. BM25 contributes only for chunks
        that share at least one query term, so purely dense hits are not boosted by lexical ties.
        A title-head match adds ``rag.title_boost`` (see :func:`title_head_match`)."""
        k = self.cfg.rrf_k
        by_dense = sorted(eligible, key=lambda i: -float(dense[i]))
        by_lex = sorted((i for i in eligible if lexical[i] > 0), key=lambda i: -float(lexical[i]))
        fused: dict[int, float] = dict.fromkeys(eligible, 0.0)
        for rank, i in enumerate(by_dense, start=1):
            fused[i] += 1.0 / (k + rank)
        for rank, i in enumerate(by_lex, start=1):
            fused[i] += 1.0 / (k + rank)
        for i in eligible:
            fused[i] *= self.cfg.weight(chunks[i].kind)
        if self.cfg.title_boost > 0:
            q = frozenset(tokenize(query))
            for i in eligible:
                fused[i] += self.cfg.title_boost * title_head_match(chunks[i].title, q)
        return fused

    def _bm25_index(self, chunks: list[Chunk]) -> BM25Index:
        if self._bm25 is None or self._bm25_count != len(chunks):
            self._bm25 = BM25Index(chunks)
            self._bm25_count = len(chunks)
        return self._bm25


def title_head(title: str) -> str:
    """The subject of a title: the words before the first ":" or "(". *Cash-secured put (CSP):
    selling a put …* → "Cash-secured put"; *The wheel: cash-secured put, …* → "The wheel"."""
    return re.split(r"[:(]", title, maxsplit=1)[0].strip()


def title_head_match(title: str, query_tokens: frozenset[str]) -> float:
    """Share of the title head's content words that occur in the query (0.0–1.0). A document
    *about* the thing the query names scores 1.0; one that only mentions it in its body scores 0."""
    head = tokenize(title_head(title))
    if not head:
        return 0.0
    return sum(1 for t in head if t in query_tokens) / len(head)


def format_result(result: RetrievalResult) -> str:
    if result.empty:
        return (
            f"no chunks above the similarity floor ({result.floor} with {result.embedder}) "
            f"for: {result.query!r}"
        )
    lines = [
        f"{len(result.hits)} chunks for {result.query!r} "
        f"(embedder {result.embedder}, floor {result.floor}"
        + (f", kind {result.kind}" if result.kind else "")
        + (f", max level {result.max_level}" if result.max_level else "")
        + ")"
    ]
    for h in result.hits:
        c = h.chunk
        lines.append(
            f"\n[S{h.rank}] {c.title} — {c.id} ({c.kind}; dense {h.dense:.3f}, bm25 {h.bm25:.2f})"
            f"\n     {c.source}: {c.url}\n     “{c.quote}”"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query the knowledge base.")
    parser.add_argument("query", nargs="+")
    parser.add_argument("--kind", choices=list(COLLECTION_NAMES))
    parser.add_argument("--max-level", choices=list(LEVELS), default=None)
    parser.add_argument("--k", type=int, default=None)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    load_env()
    cfg = load_config(args.root)
    retriever = KnowledgeRetriever.from_config(cfg)
    result = retriever.retrieve(
        " ".join(args.query), kind=args.kind, top_k=args.k, max_level=args.max_level
    )
    print(format_result(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
