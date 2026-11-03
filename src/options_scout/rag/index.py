"""``make index``: regenerate ``knowledge/rules/`` and rebuild ``data/knowledge.sqlite``.

python -m options_scout.rag.index [--no-rules] [--root PATH]
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from options_scout.config import AppConfig, load_config, load_env
from options_scout.rag.chunking import chunk_documents
from options_scout.rag.corpus import load_corpus
from options_scout.rag.embeddings import make_embedder
from options_scout.rag.retriever import chunk_params
from options_scout.rag.store import KnowledgeStore


def build_index(cfg: AppConfig) -> dict[str, object]:
    """Chunk the corpus, embed it and replace the store. Returns a summary for logs and tests."""
    t0 = time.perf_counter()
    docs = load_corpus(cfg.rag.knowledge_dir)
    chunks = chunk_documents(docs, chunk_params(cfg.rag))
    embedder = make_embedder(cfg.rag)
    store = KnowledgeStore(cfg.rag.index_db)
    count = store.rebuild(chunks, embedder)
    store.close()
    by_kind: dict[str, int] = {}
    for d in docs:
        by_kind[d.kind] = by_kind.get(d.kind, 0) + 1
    return {
        "documents": len(docs),
        "by_kind": by_kind,
        "chunks": count,
        "embedder": embedder.name,
        "db": str(cfg.rag.index_db),
        "seconds": round(time.perf_counter() - t0, 2),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the knowledge index.")
    parser.add_argument("--no-rules", action="store_true", help="skip regenerating knowledge/rules")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    load_env()
    cfg = load_config(args.root)
    if not args.no_rules:
        from options_scout.rag.rules_docs import write_rules_docs

        written = write_rules_docs(cfg)
        print(f"rules docs: {len(written)} files in {cfg.rag.knowledge_dir / 'rules'}")
    summary = build_index(cfg)
    print(
        f"indexed {summary['documents']} documents {summary['by_kind']} → {summary['chunks']} "
        f"chunks with {summary['embedder']} in {summary['seconds']}s → {summary['db']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
