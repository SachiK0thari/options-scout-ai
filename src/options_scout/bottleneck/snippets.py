"""Window filings, headlines and posts into ≤ 400-character snippets and dedupe them (4A.3).

The LLM never sees a filing: it sees these windows, cut around the layer keyword that found the
document and wrapped in delimiters by the classifier. Each snippet keeps its source, date, filer
ticker and URL so the evidence pack can link back to the document. Near-duplicates (the same
boilerplate risk factor in a 10-K and the next 10-Q, a headline syndicated to five outlets) are
collapsed with the social engine's shingle / Jaccard dedupe, keeping the earliest.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date

from options_scout.core.models import FilingSnippet, NewsItem, SocialPost
from options_scout.social.filters import inert_text, shingles

SNIPPET_MAX_CHARS = 400
DEFAULT_DEDUPE_THRESHOLD = 0.8
_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK_END = re.compile(r"</(p|div|tr|li|h[1-6]|table|br)\s*>|<br\s*/?>", re.IGNORECASE)


def normalise_text(text: str) -> str:
    """Collapse whitespace; filings are full of line breaks and non-breaking spaces."""
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def strip_html(markup: str) -> str:
    """Plain text from an EDGAR HTML document: drop scripts and styles, turn block ends into
    spaces, remove tags, unescape entities, collapse whitespace."""
    text = _SCRIPT.sub(" ", markup)
    text = _BLOCK_END.sub(" ", text)
    text = _TAG.sub(" ", text)
    return normalise_text(html.unescape(text))


def snippet_id(source: str, text: str, filer_ticker: str | None, day: date) -> str:
    """Content hash (shared with ``scripts/gen_bottleneck_fixtures.py``): the classification
    cache key."""
    key = f"{source}|{text}|{filer_ticker or ''}|{day.isoformat()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def window_text(
    text: str,
    keywords: Sequence[str],
    *,
    max_chars: int = SNIPPET_MAX_CHARS,
    max_windows: int = 4,
) -> list[str]:
    """Cut ≤ ``max_chars`` windows centred on each keyword occurrence, snapped to word boundaries.

    Windows that overlap an earlier window are skipped so one dense paragraph yields one snippet,
    not one per keyword. Returns at most ``max_windows`` windows in document order. A text with no
    keyword yields nothing: a snippet must contain the term that made it relevant.
    """
    clean = normalise_text(text)
    if not clean or max_chars < 1:
        return []
    low = clean.lower()
    hits: list[tuple[int, int]] = []
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        start = 0
        while True:
            i = low.find(k, start)
            if i < 0:
                break
            hits.append((i, i + len(k)))
            start = i + 1
    hits.sort()
    out: list[str] = []
    taken_until = -1
    for s, e in hits:
        if s < taken_until:
            continue
        window = _window_around(clean, s, e, max_chars)
        if window is None:
            continue
        w_start, w_end = window
        out.append(clean[w_start:w_end].strip())
        taken_until = w_end
        if len(out) >= max_windows:
            break
    return [w[:max_chars] for w in out if w]


def _window_around(text: str, s: int, e: int, max_chars: int) -> tuple[int, int] | None:
    n = len(text)
    if e - s >= max_chars:
        return (s, s + max_chars)
    room = max_chars - (e - s)
    before = room // 2
    w_start = max(0, s - before)
    w_end = min(n, w_start + max_chars)
    w_start = max(0, w_end - max_chars)
    # snap to word boundaries, never past the keyword itself
    if w_start > 0:
        nxt = text.find(" ", w_start, s)
        if nxt >= 0:
            w_start = nxt + 1
    if w_end < n:
        prev = text.rfind(" ", e, w_end)
        if prev >= 0:
            w_end = prev
    if w_end <= w_start:
        return None
    return (w_start, w_end)


def make_snippet(
    *,
    source: str,
    text: str,
    day: date,
    url: str | None,
    filer_ticker: str | None = None,
    form: str | None = None,
    theme_id: str | None = None,
    layer_id: str | None = None,
) -> FilingSnippet:
    body = inert_text(normalise_text(text))[:SNIPPET_MAX_CHARS]  # no markup into prompts (W13)
    filer = filer_ticker.strip().upper() or None if filer_ticker else None
    return FilingSnippet(
        id=snippet_id(source, body, filer, day),
        source=source,  # callers pass a BottleneckSourceName
        text=body,
        date=day,
        url=url,
        filer_ticker=filer,
        form=form,
        theme_id=theme_id,
        layer_hint=layer_id,
    )


def headline_to_snippet(
    item: NewsItem, *, theme_id: str | None, layer_id: str | None
) -> FilingSnippet | None:
    title = normalise_text(item.title)
    if not title:
        return None
    text = f"{title} ({item.source})" if item.source else title
    return make_snippet(
        source="news",
        text=text,
        day=item.published_at.date(),
        url=item.url,
        theme_id=theme_id,
        layer_id=layer_id,
    )


def post_to_snippets(
    post: SocialPost,
    keywords: Sequence[str],
    *,
    theme_id: str | None,
    layer_id: str | None,
    max_windows: int = 2,
) -> list[FilingSnippet]:
    """A Reddit post becomes at most ``max_windows`` snippets around the layer keywords. Only the
    post id and an excerpt are kept; author ids never enter a snippet."""
    title = post.title.strip()
    sep = " " if not title or title[-1] in ".!?" else ". "
    text = f"{title}{sep}{post.body}" if post.body else title
    return [
        make_snippet(
            source="reddit",
            text=w,
            day=post.created_at.date(),
            url=post.url,
            theme_id=theme_id,
            layer_id=layer_id,
        )
        for w in window_text(text, keywords, max_windows=max_windows)
    ]


def containment(a: set[str], b: set[str]) -> float:
    """Share of the smaller shingle set that appears in the larger one.

    Filings repeat a risk-factor sentence verbatim and add a clause; a syndicated headline gains an
    outlet suffix. Containment catches "the same text plus a bit", which Jaccard (the social
    engine's measure for whole posts) under-counts once the addition is a quarter of the text.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def dedupe_snippets(
    snippets: Iterable[FilingSnippet], threshold: float = DEFAULT_DEDUPE_THRESHOLD
) -> tuple[list[FilingSnippet], int]:
    """Drop exact and near-duplicate snippets (3-word shingles, containment ≥ ``threshold``),
    keeping the earliest of each cluster. Returns ``(kept, dropped)``; ``kept`` is in date order."""
    ordered = sorted(snippets, key=lambda s: (s.date, s.source, s.id))
    kept: list[tuple[FilingSnippet, set[str]]] = []
    buckets: dict[str, list[int]] = defaultdict(list)
    seen_ids: set[str] = set()
    out: list[FilingSnippet] = []
    dropped = 0
    for snip in ordered:
        if snip.id in seen_ids:
            dropped += 1
            continue
        sh = shingles(snip.text)
        candidates: set[int] = set()
        for s in sh:
            candidates.update(buckets.get(s, ()))
        if any(containment(sh, kept[i][1]) >= threshold for i in candidates):
            dropped += 1
            continue
        seen_ids.add(snip.id)
        kept.append((snip, sh))
        for s in sh:
            buckets[s].append(len(kept) - 1)
        out.append(snip)
    return out, dropped
