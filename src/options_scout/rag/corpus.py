"""Load ``knowledge/<kind>/*.md`` into :class:`Document` objects (YAML front-matter + body).

Collections: concepts (options), basics (investing for beginners), tax (tax and account
types), rules (generated from the PRD and config), filings (SEC excerpts); evidence is per run."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from options_scout.config import COLLECTION_NAMES
from options_scout.rag.models import DEFAULT_LEVEL, Document

_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
REQUIRED_FIELDS: tuple[str, ...] = ("id", "title", "source", "url", "kind", "as_of")


def parse_document(text: str, *, path: str = "") -> Document:
    m = _FRONT.match(text)
    if not m:
        raise ValueError(f"{path or '<text>'}: missing YAML front-matter")
    meta: Any = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: front-matter must be a mapping")
    missing = [f for f in REQUIRED_FIELDS if f not in meta]
    if missing:
        raise ValueError(f"{path}: front-matter missing {missing}")
    body = text[m.end() :].strip() + "\n"
    return Document(
        id=str(meta["id"]),
        title=str(meta["title"]),
        source=str(meta["source"]),
        url=str(meta["url"]),
        kind=meta["kind"],
        level=meta.get("level", DEFAULT_LEVEL),
        as_of=meta["as_of"],
        body=body,
        path=path,
    )


def load_corpus(knowledge_dir: Path, kinds: tuple[str, ...] = COLLECTION_NAMES) -> list[Document]:
    """Every ``*.md`` under ``knowledge/<kind>/`` for the given kinds, sorted by path.
    Duplicate ids are an error; a doc's ``kind`` must match its folder."""
    docs: list[Document] = []
    seen: dict[str, str] = {}
    for kind in kinds:
        folder = knowledge_dir / kind
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            rel = str(path.relative_to(knowledge_dir.parent)) if knowledge_dir.parent else str(path)
            doc = parse_document(path.read_text(encoding="utf-8"), path=rel)
            if doc.kind != kind:
                raise ValueError(f"{rel}: kind={doc.kind!r} but the file is under {kind}/")
            if doc.id in seen:
                raise ValueError(f"duplicate document id {doc.id!r}: {seen[doc.id]} and {rel}")
            seen[doc.id] = rel
            docs.append(doc)
    return docs


def render_document(doc: Document) -> str:
    """Inverse of :func:`parse_document` (used by the generators so output is canonical)."""
    front = {
        "id": doc.id,
        "title": doc.title,
        "source": doc.source,
        "url": doc.url,
        "kind": doc.kind,
        "level": doc.level,
        "as_of": doc.as_of.isoformat(),
    }
    header = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1000).strip()
    return f"---\n{header}\n---\n\n{doc.body.strip()}\n"
