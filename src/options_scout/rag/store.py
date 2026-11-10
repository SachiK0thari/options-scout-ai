"""SQLite chunk store with numpy cosine search (the corpus is a few hundred chunks).

Table ``chunks(id, doc_id, kind, text, meta_json, vector BLOB)`` plus ``meta(key, value)`` with
the embedder name, its dimensions and a fingerprint of the indexed chunks, so a store can tell
whether it is stale for the current corpus and config. ``rebuild`` replaces the whole table inside
one transaction and is idempotent. ``:memory:`` gives the per-thread evidence collection.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from options_scout.rag.embeddings import Embedder, Vector
from options_scout.rag.models import Chunk

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id        TEXT PRIMARY KEY,
    doc_id    TEXT NOT NULL,
    kind      TEXT NOT NULL,
    text      TEXT NOT NULL,
    meta_json TEXT NOT NULL,
    vector    BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_kind ON chunks(kind);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def fingerprint(chunks: Iterable[Chunk], embedder_name: str) -> str:
    h = hashlib.sha256(embedder_name.encode("utf-8"))
    for c in chunks:
        h.update(c.id.encode("utf-8"))
        h.update(b"\0")
        h.update(c.text.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


class KnowledgeStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path) if path != ":memory:" else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # W39: one store serves every request thread, so the connection is not bound to the
        # thread that opened it and every use (including the lazy matrix load) holds the lock
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(path) if self.path is None else str(self.path), check_same_thread=False, timeout=30
        )
        with self._lock:
            self._conn.executescript(_SCHEMA)
        self._ids: list[str] = []
        self._chunks: list[Chunk] = []
        self._matrix: Vector | None = None

    # ------------------------------------------------------------------ writing
    def rebuild(self, chunks: Sequence[Chunk], embedder: Embedder, batch_size: int = 64) -> int:
        """Replace every row with ``chunks`` embedded by ``embedder``; returns the row count."""
        vectors: list[Vector] = []
        for start in range(0, len(chunks), batch_size):
            vectors.append(
                embedder.embed([c.index_text for c in chunks[start : start + batch_size]])
            )
        matrix = (
            np.concatenate(vectors)
            if vectors
            else np.zeros((0, embedder.dimensions), dtype=np.float32)
        )
        rows = [
            (
                c.id,
                c.doc_id,
                c.kind,
                c.text,
                c.model_dump_json(exclude={"text"}),
                matrix[i].astype(np.float32).tobytes(),
            )
            for i, c in enumerate(chunks)
        ]
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chunks")
            self._conn.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)", rows)
            self._conn.execute("DELETE FROM meta")
            self._conn.executemany(
                "INSERT INTO meta VALUES (?, ?)",
                [
                    ("embedder", embedder.name),
                    ("dimensions", str(embedder.dimensions)),
                    ("fingerprint", fingerprint(chunks, embedder.name)),
                    ("count", str(len(chunks))),
                ],
            )
            self._invalidate()
        return len(rows)

    # ------------------------------------------------------------------ reading
    def meta(self) -> dict[str, str]:
        with self._lock:
            return dict(self._conn.execute("SELECT key, value FROM meta").fetchall())

    def is_current(self, chunks: Sequence[Chunk], embedder: Embedder) -> bool:
        return self.meta().get("fingerprint") == fingerprint(chunks, embedder.name)

    def __len__(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0]) if row else 0

    def chunks(self) -> list[Chunk]:
        with self._lock:
            self._load()
            return list(self._chunks)

    def get(self, chunk_id: str) -> Chunk | None:
        with self._lock:
            self._load()
            try:
                return self._chunks[self._ids.index(chunk_id)]
            except ValueError:
                return None

    def dense_scores(self, query_vector: Vector) -> NDArray[np.float32]:
        """Cosine similarity of every stored chunk to a unit query vector (same order as chunks)."""
        with self._lock:
            self._load()
            matrix = self._matrix
        if matrix is None or matrix.shape[0] == 0:
            return np.zeros(0, dtype=np.float32)
        scores: NDArray[np.float32] = (matrix @ query_vector.astype(np.float32)).astype(np.float32)
        return scores

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ internals
    def _invalidate(self) -> None:
        self._ids, self._chunks, self._matrix = [], [], None

    def _load(self) -> None:
        """Read every row into memory once (caller holds ``_lock``)."""
        if self._matrix is not None:
            return
        rows = self._conn.execute(
            "SELECT id, text, meta_json, vector FROM chunks ORDER BY rowid"
        ).fetchall()
        dims = int(self.meta().get("dimensions", "0") or 0)
        ids: list[str] = []
        chunks: list[Chunk] = []
        vectors: list[Vector] = []
        for cid, text, meta_json, blob in rows:
            meta = json.loads(meta_json)
            chunks.append(Chunk(text=text, **meta))
            ids.append(cid)
            vectors.append(np.frombuffer(blob, dtype=np.float32))
        self._ids = ids
        self._chunks = chunks
        self._matrix = (
            np.vstack(vectors).astype(np.float32)
            if vectors
            else np.zeros((0, dims), dtype=np.float32)
        )
