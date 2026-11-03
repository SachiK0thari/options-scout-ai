"""Embedders behind one protocol.

``HashEmbedder`` is deterministic feature hashing of word unigrams and bigrams (signed hashing
trick, sublinear term frequency, L2-normalised): no model download, identical vectors on every
machine, good enough for lexical-style retrieval in tests and CI. ``FastEmbedEmbedder`` wraps
``fastembed`` (``pip install -e ".[rag]"``) with ``BAAI/bge-small-en-v1.5`` for real semantic
search. Both return float32 unit vectors so cosine similarity is a dot product.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from options_scout.config import RagConfig

Vector = NDArray[np.float32]

_WORD = re.compile(r"[a-z0-9][a-z0-9'\-]*")  # "35%" and "35" both become "35"
STOPWORDS: frozenset[str] = frozenset(
    (
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have",
        "how", "if", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the", "this",
        "to", "was", "what", "when", "where", "which", "who", "why", "will", "with", "you",
        "your", "i", "we", "our", "they", "their", "do", "does", "did", "can", "could", "should",
        "would", "may", "might", "also", "than", "then", "there", "these", "those", "not", "no",
    )
)  # fmt: skip


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens without stopwords; shared by the hash embedder and BM25 so a query
    with no content words matches nothing."""
    return [t for t in _WORD.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


class Embedder(Protocol):
    name: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> Vector: ...


def _bucket(token: str, dims: int) -> tuple[int, float]:
    h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    idx = int.from_bytes(h[:4], "little") % dims
    sign = 1.0 if h[4] & 1 else -1.0
    return idx, sign


class HashEmbedder:
    """Signed feature hashing of unigrams + bigrams with sublinear tf, L2-normalised."""

    def __init__(self, dimensions: int = 2048) -> None:
        if dimensions < 64:
            raise ValueError("HashEmbedder needs at least 64 dimensions")
        self.dimensions = dimensions
        self.name = f"hash-{dimensions}"

    def embed(self, texts: Sequence[str]) -> Vector:
        out = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = tokenize(text)
            feats: Counter[str] = Counter(tokens)
            feats.update(f"{a} {b}" for a, b in itertools.pairwise(tokens))
            for feat, count in feats.items():
                idx, sign = _bucket(feat, self.dimensions)
                out[row, idx] += sign * (1.0 + math.log(count))
            norm = float(np.linalg.norm(out[row]))
            if norm > 0:
                out[row] /= norm
        return out


class FastEmbedEmbedder:
    """``fastembed`` text embeddings (ONNX); lazily imported so the core install stays light."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ImportError(
                'fastembed is not installed; run `pip install -e ".[rag]"` or set '
                "rag.embedder: hash in config/rag.yaml"
            ) from exc
        self._model: Any = TextEmbedding(model_name=model_name)
        self.name = f"fastembed-{model_name.split('/')[-1]}"
        probe = np.asarray(next(iter(self._model.embed(["dimension probe"]))), dtype=np.float32)
        self.dimensions = int(probe.shape[0])

    def embed(self, texts: Sequence[str]) -> Vector:
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        vecs = np.asarray(list(self._model.embed(list(texts))), dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        result: Vector = (vecs / norms).astype(np.float32)
        return result


def make_embedder(cfg: RagConfig) -> Embedder:
    if cfg.embedder == "fastembed":
        return FastEmbedEmbedder(cfg.fastembed_model)
    return HashEmbedder(cfg.hash_dimensions)
