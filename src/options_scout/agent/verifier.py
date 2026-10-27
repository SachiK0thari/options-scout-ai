"""Deterministic verifier: every number in the narrative must exist in the computed payload.

Also enforces the language policy (banned phrases) and the presence of the disclaimer.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

from options_scout.core.models import VerificationResult

BANNED_PHRASES: tuple[str, ...] = (
    "guaranteed",
    "guarantee",
    "you should buy",
    "you should sell",
    "risk-free",
    "risk free",
    "can't lose",
    "cannot lose",
    "sure thing",
    "will profit",
    "free money",
    "buy now",
    "strong buy",
    "must buy",
    "i recommend buying",
    "we recommend buying",
)

CANDIDATE_ID = re.compile(r"\b(?:CSP|LEAPS|PMCC|PMCCSC)-[A-Z.\-]+?-\d{4}-\d{2}-\d{2}-[\d.]+[CP]\b")
_PMCC_ID = re.compile(r"\bPMCC-[A-Z.]+-\d{4}-\d{2}-\d{2}-[\d.]+C-\d{4}-\d{2}-\d{2}-[\d.]+C\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_NUMBER = re.compile(r"(?<![\w.])[-+−]?\$?\s?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
_ORDINAL = re.compile(r"\b\d+(st|nd|rd|th)\b")


def _to_float(token: str) -> tuple[float, bool] | None:
    t = token.replace("−", "-").replace("$", "").replace(",", "").replace(" ", "")
    pct = t.endswith("%")
    t = t.rstrip("%")
    try:
        return float(t), pct
    except ValueError:
        return None


def collect_payload_numbers(payload: Any, out: set[float] | None = None) -> set[float]:
    """Recursively gather every numeric value (plus display variants) from the payload."""
    out = set() if out is None else out
    if isinstance(payload, bool):
        return out
    if isinstance(payload, int | float):
        v = float(payload)
        if math.isfinite(v):
            out.add(v)
            for k in range(0, 5):
                out.add(round(v, k))
            if abs(v) <= 1.5:  # fractions may be written as percents
                out.add(round(v * 100, 2))
                out.add(round(v * 100, 1))
                out.add(round(v * 100, 0))
            out.add(abs(v))
    elif isinstance(payload, dict):
        for v in payload.values():
            collect_payload_numbers(v, out)
    elif isinstance(payload, list | tuple | set):
        for v in payload:
            collect_payload_numbers(v, out)
    elif isinstance(payload, str):
        for tok in _NUMBER.findall(payload):
            parsed = _to_float(tok)
            if parsed:
                out.add(parsed[0])
                out.add(abs(parsed[0]))
    return out


def extract_narrative_numbers(text: str) -> list[tuple[str, float, bool]]:
    """Numbers in the narrative, excluding candidate ids, dates and ordinals."""
    scrubbed = _PMCC_ID.sub(" ", text)
    scrubbed = CANDIDATE_ID.sub(" ", scrubbed)
    scrubbed = _DATE.sub(" ", scrubbed)
    scrubbed = _ORDINAL.sub(" ", scrubbed)
    scrubbed = re.sub(r"\*\*|__", " ", scrubbed)
    out: list[tuple[str, float, bool]] = []
    for m in _NUMBER.finditer(scrubbed):
        tok = m.group(0).strip()
        parsed = _to_float(tok)
        if parsed is None:
            continue
        val, pct = parsed
        if _YEAR.fullmatch(tok.strip("$ ")) and 1990 <= val <= 2100:
            continue  # bare years are not claims
        out.append((tok, val, pct))
    return out


def _matches(value: float, allowed: Iterable[float], rel_tol: float) -> bool:
    for a in allowed:
        if a == value:
            return True
        if math.isclose(a, value, rel_tol=rel_tol, abs_tol=0.0051):
            return True
    return False


def verify_narrative(
    narrative: str,
    payload: dict[str, Any],
    *,
    disclaimer: str,
    rel_tol: float = 0.01,
    attempts: int = 1,
) -> VerificationResult:
    allowed = collect_payload_numbers(payload)
    found = extract_narrative_numbers(narrative)
    ungrounded: list[str] = []
    for tok, val, pct in found:
        candidates = [val, -val]
        if pct:
            candidates += [val / 100.0, -val / 100.0]
        if not any(_matches(c, allowed, rel_tol) for c in candidates):
            ungrounded.append(tok)
    low = narrative.lower()
    banned = sorted({p for p in BANNED_PHRASES if p in low})
    disclaimer_present = _normalise(disclaimer)[:60] in _normalise(narrative)
    cited = sorted(set(CANDIDATE_ID.findall(narrative)) | set(_PMCC_ID.findall(narrative)))
    passed = not ungrounded and not banned and disclaimer_present
    return VerificationResult(
        passed=passed,
        numbers_checked=len(found),
        ungrounded_numbers=ungrounded,
        banned_phrases_found=banned,
        disclaimer_present=disclaimer_present,
        cited_candidate_ids=cited,
        attempts=attempts,
    )


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()
