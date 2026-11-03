"""Typed objects that cross the retrieval boundary: documents, chunks, scored hits.

``Citation`` itself lives in ``core/models.py`` because it travels on the report."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from options_scout.core.models import Citation

Kind = Literal["concepts", "rules", "filings", "evidence"]
QUOTE_CHARS = 240  # a citation quote is the first sentence(s) of the chunk, up to this many chars


class Document(BaseModel):
    """One Markdown file of the corpus (front-matter ``id, title, source, url, kind, as_of``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    url: str = Field(min_length=1)
    kind: Kind
    as_of: date
    body: str
    path: str = ""  # repo-relative path, informational

    @property
    def word_count(self) -> int:
        return len(self.body.split())


class Chunk(BaseModel):
    """A retrievable span of one document. ``id`` is ``<doc_id>#<n>`` and depends only on the
    document text and the chunking parameters, so re-indexing never renumbers citations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    doc_id: str
    n: int = Field(ge=0)
    kind: Kind
    title: str
    url: str
    source: str
    as_of: date
    heading: str = ""  # heading path inside the document, e.g. "Risks › Assignment"
    text: str  # the span itself; what gets quoted and shown to the LLM

    @property
    def context(self) -> str:
        """Title and heading path, prepended to ``text`` for embedding and BM25 only."""
        return f"{self.title} › {self.heading}" if self.heading else self.title

    @property
    def index_text(self) -> str:
        return f"{self.context}\n{self.text}"

    @property
    def quote(self) -> str:
        return quote_of(self.text)


class ScoredChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk: Chunk
    dense: float  # cosine similarity to the query
    bm25: float  # raw BM25 score (0 when no query term occurs)
    fused: float  # weighted reciprocal-rank fusion of the two rankings
    rank: int = Field(ge=1)  # 1-based position in the final result, i.e. the ``[Sn]`` number


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    hits: list[ScoredChunk] = Field(default_factory=list)
    kind: Kind | None = None
    embedder: str = ""
    floor: float = 0.0

    @property
    def empty(self) -> bool:
        return not self.hits

    @property
    def chunks(self) -> list[Chunk]:
        return [h.chunk for h in self.hits]

    def citations(self) -> list[Citation]:
        return [citation_of(h.chunk, f"S{h.rank}") for h in self.hits]

    def sources_block(self) -> str:
        """Numbered ``[S1]…[Sn]`` block handed to the Education prompt (step 10.3)."""
        lines = []
        for h in self.hits:
            c = h.chunk
            lines.append(f"[S{h.rank}] {c.title} — {c.source} ({c.url})\n{c.text.strip()}")
        return "\n\n".join(lines)


def citation_of(chunk: Chunk, tag: str = "") -> Citation:
    return Citation(
        chunk_id=chunk.id,
        doc_id=chunk.doc_id,
        title=chunk.title,
        url=chunk.url,
        quote=chunk.quote,
        kind=chunk.kind,
        tag=tag,
    )


def quote_of(text: str, limit: int = QUOTE_CHARS) -> str:
    """First sentence(s) of ``text`` up to ``limit`` characters, without cutting a word."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    for stop in (". ", "; ", ": "):
        idx = cut.rfind(stop)
        if idx >= limit // 2:
            return cut[: idx + 1]
    return cut[: cut.rfind(" ")].rstrip(",;:") + "…"
