"""Heading-aware chunking of Markdown documents (PRD 5.6: ≤ 400 tokens, 15% overlap).

Tokens are approximated as ``0.75 × words`` (the usual English BPE ratio), so ``chunk_tokens=400``
means windows of at most 300 words. A document is first split at its Markdown headings; each
section is then cut into overlapping word windows. Chunk ids are ``<doc_id>#<n>`` with ``n``
counting from 0 across the whole document, so they are a pure function of the document text and
the chunking parameters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from options_scout.rag.models import Chunk, Document

WORDS_PER_TOKEN = 0.75
SKIP_HEADINGS: frozenset[str] = frozenset({"sources", "references", "see also"})  # link lists
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


@dataclass(frozen=True)
class ChunkParams:
    chunk_tokens: int = 400
    overlap: float = 0.15

    @property
    def max_words(self) -> int:
        return max(20, int(self.chunk_tokens * WORDS_PER_TOKEN))

    @property
    def overlap_words(self) -> int:
        return int(self.max_words * self.overlap)


@dataclass(frozen=True)
class Section:
    heading: str  # heading path joined with " › " ("" for text before the first heading)
    text: str


def split_sections(body: str) -> list[Section]:
    """Split Markdown at headings; the heading path is kept as context for every chunk."""
    path: list[tuple[int, str]] = []
    sections: list[Section] = []
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            sections.append(Section(" › ".join(h for _, h in path), text))
        buf.clear()

    for line in body.splitlines():
        m = _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            path[:] = [(lv, h) for lv, h in path if lv < level]
            path.append((level, m.group(2)))
        else:
            buf.append(line)
    flush()
    return sections


def _windows(words: list[str], params: ChunkParams) -> list[list[str]]:
    if len(words) <= params.max_words:
        return [words] if words else []
    step = max(1, params.max_words - params.overlap_words)
    out: list[list[str]] = []
    start = 0
    while start < len(words):
        window = words[start : start + params.max_words]
        out.append(window)
        if start + params.max_words >= len(words):
            break
        start += step
    return out


def _paragraph_windows(text: str, params: ChunkParams) -> list[str]:
    """Pack whole paragraphs into windows; a paragraph longer than a window is cut by words."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    windows: list[str] = []
    current: list[str] = []
    current_words = 0
    for para in paragraphs:
        n = len(para.split())
        if n > params.max_words:
            if current:
                windows.append("\n\n".join(current))
                current, current_words = [], 0
            windows.extend(" ".join(w) for w in _windows(para.split(), params))
            continue
        if current and current_words + n > params.max_words:
            windows.append("\n\n".join(current))
            # overlap: carry the tail of the previous window into the next one
            tail = " ".join(" ".join(current).split()[-params.overlap_words :])
            current = [tail] if params.overlap_words and tail else []
            current_words = len(tail.split()) if current else 0
        current.append(para)
        current_words += n
    if current:
        windows.append("\n\n".join(current))
    return windows


def chunk_document(doc: Document, params: ChunkParams | None = None) -> list[Chunk]:
    params = params or ChunkParams()
    chunks: list[Chunk] = []
    for section in split_sections(doc.body):
        leaf = section.heading.rsplit(" › ", 1)[-1].strip().lower()
        if leaf in SKIP_HEADINGS:
            continue  # the citation already carries the URL; the link list adds no content
        for text in _paragraph_windows(section.text, params):
            n = len(chunks)
            chunks.append(
                Chunk(
                    id=f"{doc.id}#{n}",
                    doc_id=doc.id,
                    n=n,
                    kind=doc.kind,
                    level=doc.level,
                    title=doc.title,
                    url=doc.url,
                    source=doc.source,
                    as_of=doc.as_of,
                    review_by=doc.review_by,
                    heading=section.heading,
                    text=text,
                )
            )
    return chunks


def chunk_documents(docs: list[Document], params: ChunkParams | None = None) -> list[Chunk]:
    out: list[Chunk] = []
    for doc in docs:
        out.extend(chunk_document(doc, params))
    return out
