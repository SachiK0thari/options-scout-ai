"""Lexical ranking over chunks with ``rank_bm25`` (Okapi BM25), same tokenizer as the embedder."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from options_scout.rag.embeddings import tokenize
from options_scout.rag.models import Chunk


class BM25Index:
    def __init__(self, chunks: Sequence[Chunk]) -> None:
        from rank_bm25 import BM25Okapi

        self.ids = [c.id for c in chunks]
        corpus = [tokenize(c.index_text) or ["<empty>"] for c in chunks]
        self._tokens = [frozenset(toks) for toks in corpus]
        self._bm25: Any = BM25Okapi(corpus) if corpus else None

    def __len__(self) -> int:
        return len(self.ids)

    def shares_term(self, query: str) -> NDArray[np.bool_]:
        """Per chunk: does it contain at least one content word of ``query``? (A BM25 score of
        zero is not the same test: IDF is zero for a term found in one of two documents.)"""
        q = frozenset(tokenize(query))
        shares = (bool(q & toks) for toks in self._tokens)
        return np.fromiter(shares, dtype=bool, count=len(self.ids))

    def scores(self, query: str) -> NDArray[np.float64]:
        """Raw BM25 score per chunk (0.0 where no query term occurs)."""
        if self._bm25 is None:
            return np.zeros(0, dtype=np.float64)
        tokens = tokenize(query)
        if not tokens:
            return np.zeros(len(self.ids), dtype=np.float64)
        scores: NDArray[np.float64] = np.asarray(self._bm25.get_scores(tokens), dtype=np.float64)
        return np.maximum(scores, 0.0)
