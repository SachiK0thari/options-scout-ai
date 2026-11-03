"""The Compliance agent's deterministic checks (PRD section 13.1).

``verify_narrative`` is the Phase 5 verifier (numbers, banned phrases, disclaimer, ``[Sn]`` tags)
and still backs ``VerificationResult``. ``run_compliance`` (step 10.4) runs the eight checks of
section 13.1 over a tagged ``Narrative`` and returns a ``ComplianceReport``:

``check_numbers`` · ``check_citations`` · ``check_education_only`` · ``check_suitability`` ·
``check_language`` · ``check_disclaimer`` · ``check_sources_fresh`` (warn) · ``check_no_pii``.

Rules and patterns live in ``config/compliance.yaml``. Moved here from ``agent/verifier.py`` in
step 10.1; ``agent/verifier.py`` re-exports the old names for one release.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from options_scout.config import ComplianceConfig
from options_scout.core.models import (
    SOURCE_TAG,
    Citation,
    ComplianceCheck,
    ComplianceReport,
    Narrative,
    Paragraph,
    SuitabilityFacts,
    TextKind,
    VerificationResult,
)

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
_SOURCE_TAG = re.compile(SOURCE_TAG)


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
    scrubbed = _SOURCE_TAG.sub(" ", scrubbed)  # [S3] is a citation, not a claim
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


def unknown_source_tags(text: str, source_count: int) -> list[str]:
    """``[Sn]`` tags in ``text`` that do not point at one of the ``source_count`` sources."""
    seen: list[str] = []
    for n in _SOURCE_TAG.findall(text):
        tag = f"S{n}"
        if not 1 <= int(n) <= source_count and tag not in seen:
            seen.append(tag)
    return seen


def resolve_citations(narrative: Narrative, sources: list[Citation]) -> list[Citation]:
    """The sources a narrative actually cites, numbered ``S1…`` in source order (10.3)."""
    by_tag = {f"S{i}": c for i, c in enumerate(sources, start=1)}
    used = narrative.tags
    return [by_tag[tag].model_copy(update={"tag": tag}) for tag in by_tag if tag in used]


def verify_narrative(
    narrative: str,
    payload: dict[str, Any],
    *,
    disclaimer: str,
    rel_tol: float = 0.01,
    attempts: int = 1,
    source_count: int | None = None,
) -> VerificationResult:
    """Deterministic checks on one narrative text.

    ``source_count`` is the number of ``[Sn]`` sources the text was allowed to cite (defaults to
    ``len(payload["sources"])``); a tag outside that range fails the check.
    """
    allowed = collect_payload_numbers(payload)
    found = extract_narrative_numbers(narrative)
    if source_count is None:
        source_count = len(payload.get("sources") or [])
    unknown = unknown_source_tags(narrative, source_count)
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
    passed = not ungrounded and not banned and disclaimer_present and not unknown
    return VerificationResult(
        passed=passed,
        numbers_checked=len(found),
        ungrounded_numbers=ungrounded,
        banned_phrases_found=banned,
        disclaimer_present=disclaimer_present,
        cited_candidate_ids=cited,
        attempts=attempts,
        citations_checked=len(_SOURCE_TAG.findall(narrative)),
        unknown_citations=unknown,
    )


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


# ====================================================================== 13.1: the eight checks
_SHORT_OPTION_ID = re.compile(r"\b(?:CSP|PMCCSC)-[A-Z.\-]+?-\d{4}-\d{2}-\d{2}-[\d.]+[CP]\b")
_HANDLE = re.compile(r"(?<![\w/.])@[A-Za-z0-9_]{2,}|\b[ur]/[A-Za-z0-9_\-]{2,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_NAKED = re.compile(r"\bnaked\b|\buncovered put", re.IGNORECASE)
_LEVERAGE_OPPORTUNITY = re.compile(
    r"\b(?:leverage|margin)\b[^.]{0,80}\b(?:opportunit|boost|enhance|amplif|juice|free(?:s|d)? up)",
    re.IGNORECASE,
)
_QUOTED = re.compile(r"[\"“][^\"”]{1,80}[\"”]")


def _loc(i: int) -> str:
    return f"paragraph {i + 1}"


def _sentences(text: str) -> list[str]:
    return [t for t in _SENTENCE.split(text) if t.strip()]


def _is_cited(p: Paragraph) -> bool:
    return bool(p.citations) or bool(re.search(SOURCE_TAG, p.text))


# ------------------------------------------------------------------------- 1 check_numbers
def check_numbers(verification: VerificationResult) -> ComplianceCheck:
    bad = verification.ungrounded_numbers
    return ComplianceCheck(
        name="check_numbers",
        passed=not bad,
        detail=(
            f"{verification.numbers_checked} numbers checked, "
            + (f"not in payload: {', '.join(bad)}" if bad else "all grounded")
        ),
        locations=list(bad),
    )


# ----------------------------------------------------------------------- 2 check_citations
def check_citations(narrative: Narrative, sources: Sequence[Citation]) -> ComplianceCheck:
    """Every ``[Sn]`` exists; every education paragraph cites; quotes come from the sources."""
    problems: list[str] = []
    locations: list[str] = []
    unknown = unknown_source_tags(narrative.markdown, len(sources))
    for p in narrative.paragraphs:
        unknown += [t for t in p.citations if t not in unknown and int(t[1:]) > len(sources)]
    if unknown:
        problems.append(f"tags not in sources: {', '.join(sorted(set(unknown)))}")
        locations += sorted(set(unknown))
    for i, p in enumerate(narrative.paragraphs):
        if p.mode == "education" and not _is_cited(p):
            problems.append(f"{_loc(i)}: education paragraph without a citation")
            locations.append(_loc(i))
    for c in resolve_citations(narrative, list(sources)):
        if not c.quote.strip():
            problems.append(f"{c.tag}: empty quote")
            locations.append(c.tag)
    return ComplianceCheck(
        name="check_citations",
        passed=not problems,
        detail="; ".join(problems) or f"{len(narrative.tags)} tag(s) resolve to retrieved sources",
        locations=locations,
    )


# ------------------------------------------------------------------ 3 check_education_only
def _run_numbers(payload: dict[str, Any]) -> set[float]:
    """Numbers that identify this run (positions, portfolio, allocation…), not quoted sources."""
    core = {k: v for k, v in payload.items() if k not in ("sources", "disclaimer", "question")}
    return {v for v in collect_payload_numbers(core) if abs(v) >= 1000}


def check_education_only(
    narrative: Narrative,
    payload: dict[str, Any],
    run_tickers: Sequence[str],
    *,
    rel_tol: float = 0.01,
) -> ComplianceCheck:
    """Mode-tag rules: no run data in ``education``; short options in ``screen_result`` carry
    their realistic loss; every paragraph has a known mode."""
    problems: list[str] = []
    locations: list[str] = []
    run_numbers = _run_numbers(payload)
    tickers = [t for t in run_tickers if len(t) >= 2]
    ticker_re = (
        re.compile(r"\b(?:" + "|".join(map(re.escape, tickers)) + r")\b") if tickers else None
    )
    losses = {
        str(p.get("candidate_id")): p.get("realistic_loss")
        for p in payload.get("positions", [])
        if isinstance(p, dict)
    }
    for i, p in enumerate(narrative.paragraphs):
        if p.mode == "education":
            ids = CANDIDATE_ID.findall(p.text)
            if ids:
                problems.append(f"{_loc(i)}: candidate id in education paragraph ({ids[0]})")
                locations.append(_loc(i))
            if ticker_re and (m := ticker_re.search(p.text)):
                problems.append(f"{_loc(i)}: run ticker {m.group(0)} in education paragraph")
                locations.append(_loc(i))
            for tok, val, pct in extract_narrative_numbers(p.text):
                if pct:
                    continue
                if any(_matches(val, [n], rel_tol) for n in run_numbers):
                    problems.append(f"{_loc(i)}: run number {tok} in education paragraph")
                    locations.append(_loc(i))
                    break
        elif p.mode == "screen_result":
            low = p.text.lower()
            for cid in _SHORT_OPTION_ID.findall(p.text):
                loss = losses.get(cid)
                has_phrase = "realistic loss" in low or "loss at" in low or "modelled loss" in low
                has_number = loss is not None and any(
                    _matches(val, [float(loss)], rel_tol)
                    for _, val, _ in extract_narrative_numbers(p.text)
                )
                if not (has_phrase or has_number):
                    problems.append(
                        f"{_loc(i)}: short option {cid} described without its realistic loss"
                    )
                    locations.append(_loc(i))
                    break
    return ComplianceCheck(
        name="check_education_only",
        passed=not problems,
        detail="; ".join(problems)
        or "education paragraphs carry no run data; short options show their loss",
        locations=locations,
    )


# -------------------------------------------------------------------- 4 check_suitability
def suitability_problems(
    facts: SuitabilityFacts, text: str, cfg: ComplianceConfig
) -> list[tuple[str, str]]:
    """``(reason_code, detail)`` pairs; empty when the described screen suits the profile."""
    out: list[tuple[str, str]] = []
    if facts.account_type == "cash" and facts.margin_used > 0:
        out.append(("margin_on_cash", f"margin ${facts.margin_used:,.0f} used in a cash account"))
    if facts.max_position_loss_pct > facts.loss_limit_pct + 1e-9:
        out.append(
            (
                "loss_over_limit",
                f"a position's realistic loss is {facts.max_position_loss_pct:.1%} of the account, "
                f"limit {facts.loss_limit_pct:.0%} for a {facts.risk_profile} profile",
            )
        )
    if facts.position_count > facts.max_positions:
        out.append(
            ("too_many_positions", f"{facts.position_count} positions > max {facts.max_positions}")
        )
    if facts.pmcc_present and not facts.leaps_requested:
        out.append(("pmcc_without_leaps", "a PMCC is described but LEAPS were not requested"))
    for strategy in facts.strategies_present:
        minimum = cfg.suitability.min_buying_power.get(strategy)  # type: ignore[call-overload]
        if minimum is not None and facts.buying_power < minimum:
            out.append(
                (
                    "buying_power_below_minimum",
                    f"{strategy} needs at least ${minimum:,.0f} of buying power, "
                    f"profile has ${facts.buying_power:,.0f}",
                )
            )
    if facts.risk_profile == "conservative" and facts.earnings_flagged:
        for cid in facts.earnings_flagged:
            if not any(cid in s and "earnings" in s.lower() for s in _sentences(text)):
                out.append(
                    (
                        "earnings_unflagged_conservative",
                        f"{cid} has earnings before expiry but the text does not say so "
                        "in the same sentence",
                    )
                )
                break
    if (
        cfg.suitability.reject_naked_language_on_cash
        and facts.account_type == "cash"
        and _NAKED.search(text)
    ):
        out.append(("naked_language_on_cash", "naked-put language for a cash account"))
    if cfg.suitability.reject_leverage_opportunity_when_conservative and (
        facts.risk_profile == "conservative" and _LEVERAGE_OPPORTUNITY.search(text)
    ):
        out.append(
            (
                "leverage_as_opportunity",
                "margin leverage described as an opportunity for a conservative profile",
            )
        )
    return out


def check_suitability(
    facts: SuitabilityFacts | None, text: str, cfg: ComplianceConfig
) -> ComplianceCheck:
    if facts is None:
        return ComplianceCheck(
            name="check_suitability", passed=True, detail="no screen in this text (concept answer)"
        )
    problems = suitability_problems(facts, text, cfg)
    return ComplianceCheck(
        name="check_suitability",
        passed=not problems,
        detail="; ".join(f"{code}: {d}" for code, d in problems) or "suits the profile",
        locations=[code for code, _ in problems],
    )


# ----------------------------------------------------------------------- 5 check_language
def _scrub_allowed(text: str, cfg: ComplianceConfig) -> str:
    out = _QUOTED.sub(" ", text)
    for pattern in cfg.allow_list:
        out = re.sub(pattern, " ", out, flags=re.IGNORECASE)
    return out


def language_violations(narrative: Narrative, cfg: ComplianceConfig) -> list[tuple[int, str, str]]:
    """``(paragraph index, label, matched text)`` for every banned pattern hit. Quoted terminology
    and allow-listed phrasings are exempt inside cited education paragraphs only."""
    hits: list[tuple[int, str, str]] = []
    for i, p in enumerate(narrative.paragraphs):
        text = _scrub_allowed(p.text, cfg) if (p.mode == "education" and _is_cited(p)) else p.text
        for bp in cfg.banned_patterns:
            m = re.search(bp.pattern, text, re.IGNORECASE)
            if m:
                hits.append((i, bp.label, m.group(0)))
    return hits


def check_language(narrative: Narrative, cfg: ComplianceConfig) -> ComplianceCheck:
    hits = language_violations(narrative, cfg)
    return ComplianceCheck(
        name="check_language",
        passed=not hits,
        detail="; ".join(f"{_loc(i)}: {label} ({text!r})" for i, label, text in hits)
        or "no directive, certainty, superlative or urgency language",
        locations=[_loc(i) for i, _, _ in hits],
    )


# ---------------------------------------------------------------------- 6 check_disclaimer
def check_disclaimer(
    narrative: Narrative,
    *,
    disclaimer: str,
    cfg: ComplianceConfig,
    text_kind: TextKind,
    delayed_data: bool,
) -> ComplianceCheck:
    text = narrative.markdown
    problems: list[str] = []
    count = _normalise(text).count(_normalise(disclaimer)[:60])
    if count != 1:
        problems.append(f"disclaimer appears {count} time(s), expected exactly once")
    if text_kind == "answer" and CANDIDATE_ID.search(text):
        last = narrative.paragraphs[-1].text if narrative.paragraphs else ""
        if _normalise(cfg.reminder) not in _normalise(last) and _normalise(disclaimer)[
            :60
        ] not in _normalise(last):
            problems.append("reply names an option but does not close with the reminder")
    body = _normalise(text).replace(_normalise(disclaimer), "")  # the disclaimer does not count
    if (
        text_kind == "report"
        and delayed_data
        and cfg.require_delayed_data_statement
        and "delayed" not in body
    ):
        problems.append("no statement that market data is delayed")
    return ComplianceCheck(
        name="check_disclaimer",
        passed=not problems,
        detail="; ".join(problems) or "disclaimer present once",
    )


# ------------------------------------------------------------------- 7 check_sources_fresh
def check_sources_fresh(
    citations: Sequence[Citation], cfg: ComplianceConfig, today: date | None = None
) -> ComplianceCheck:
    today = today or date.today()
    stale = [
        c.tag or c.doc_id
        for c in citations
        if c.kind in ("rules", "filings") and c.as_of and (today - c.as_of).days > cfg.max_age_days
    ]
    return ComplianceCheck(
        name="check_sources_fresh",
        passed=not stale,
        severity="warn",
        detail=(
            f"{', '.join(stale)} older than {cfg.max_age_days} days (source may be out of date)"
            if stale
            else "cited rules and filings are current"
        ),
        locations=stale,
    )


# -------------------------------------------------------------------------- 8 check_no_pii
def check_no_pii(narrative: Narrative) -> ComplianceCheck:
    found: list[str] = []
    for p in narrative.paragraphs:
        found += _HANDLE.findall(p.text) + _EMAIL.findall(p.text)
    return ComplianceCheck(
        name="check_no_pii",
        passed=not found,
        detail=f"handles or emails present: {', '.join(found)}"
        if found
        else "no handles or emails",
        locations=found,
    )


# ------------------------------------------------------------------------------- outcome
def run_compliance(
    narrative: Narrative,
    *,
    payload: dict[str, Any],
    sources: Sequence[Citation],
    facts: SuitabilityFacts | None,
    cfg: ComplianceConfig,
    disclaimer: str,
    text_kind: TextKind = "report",
    run_tickers: Sequence[str] = (),
    rel_tol: float = 0.01,
    attempts: int = 1,
    delayed_data: bool = True,
    today: date | None = None,
) -> ComplianceReport:
    """Run the eight checks; ``passed`` is False on any blocking failure. Warnings never block."""
    text = narrative.markdown
    verification = verify_narrative(
        text,
        payload,
        disclaimer=disclaimer,
        rel_tol=rel_tol,
        attempts=attempts,
        source_count=len(sources),
    )
    citations = resolve_citations(narrative, list(sources))
    checks = [
        check_numbers(verification),
        check_citations(narrative, sources),
        check_education_only(narrative, payload, run_tickers, rel_tol=rel_tol),
        check_suitability(facts, text, cfg),
        check_language(narrative, cfg),
        check_disclaimer(
            narrative,
            disclaimer=disclaimer,
            cfg=cfg,
            text_kind=text_kind,
            delayed_data=delayed_data,
        ),
        check_sources_fresh(citations, cfg, today),
        check_no_pii(narrative),
    ]
    blocking = [c for c in checks if not c.passed and c.severity == "block"]
    feedback = "; ".join(f"{c.name}: {c.detail}" for c in blocking)
    # keep the Phase 5 result consistent with the full set of checks
    verification = verification.model_copy(update={"passed": not blocking, "attempts": attempts})
    return ComplianceReport(
        passed=not blocking,
        checks=checks,
        retry_feedback=feedback,
        audit_id=uuid.uuid4().hex[:10],
        text_kind=text_kind,
        attempts=attempts,
        verification=verification,
    )
