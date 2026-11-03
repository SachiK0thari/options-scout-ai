"""Deprecated location (Phase 10, step 10.1): moved to ``options_scout.core.compliance``.

The Compliance agent owns these checks now. This module re-exports the old names for one release
so existing imports keep working; new code imports from ``options_scout.core.compliance``.
"""

from __future__ import annotations

from options_scout.core.compliance import (
    BANNED_PHRASES,
    CANDIDATE_ID,
    collect_payload_numbers,
    extract_narrative_numbers,
    verify_narrative,
)

__all__ = [
    "BANNED_PHRASES",
    "CANDIDATE_ID",
    "collect_payload_numbers",
    "extract_narrative_numbers",
    "verify_narrative",
]
