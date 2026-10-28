"""Entity extraction over cleaned posts: batched LLM calls (or fixture labels / rule-based)."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from options_scout.core.models import ExtractedEntity, SocialPost
from options_scout.llm.client import LLMClient

log = logging.getLogger(__name__)


def extract_all(
    posts: Sequence[SocialPost],
    llm: LLMClient,
    *,
    batch_size: int,
    ground_truth: Mapping[str, Sequence[ExtractedEntity]] | None = None,
) -> dict[str, list[ExtractedEntity]]:
    """Return post_id → entities.

    Fixture corpora carry gold labels; when ``ground_truth`` is given AND the client is not a live
    provider, we use the labels (that is what "replaying cached LLM output" means offline).
    Otherwise we batch posts through the configured provider.
    """
    out: dict[str, list[ExtractedEntity]] = {}
    pending: list[SocialPost] = []
    for p in posts:
        if ground_truth is not None and not llm.is_live and p.id in ground_truth:
            out[p.id] = list(ground_truth[p.id])
        else:
            pending.append(p)
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        try:
            result = llm.extract_entities(batch)
        except Exception as exc:
            log.warning("extraction batch failed (%s); posts skipped", exc)
            for p in batch:
                out[p.id] = []
            continue
        by_id = {r.post_id: r.entities for r in result.results}
        for p in batch:
            out[p.id] = list(by_id.get(p.id, []))
    return out
