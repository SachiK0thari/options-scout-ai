"""Retrieval layer (PRD section 5.6): a cited knowledge base for the Education agent.

Corpus ``knowledge/`` (Markdown + YAML front-matter) → :mod:`chunking` → :mod:`embeddings`
(``HashEmbedder`` offline, ``FastEmbedEmbedder`` optional) → :mod:`store` (SQLite + numpy cosine)
+ :mod:`bm25` → :mod:`retriever` (reciprocal-rank fusion, ``kind`` filter, similarity floor) →
``Citation`` objects. Retrieval supplies concepts, rules and evidence, never prices.
"""
