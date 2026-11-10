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
    BOTTLENECK_BOARD_DOC_ID,
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
_CODE_SPAN = re.compile(r"`[^`\n]*`")  # run ids, thread ids, config keys: identifiers, not claims


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
    scrubbed = _CODE_SPAN.sub(" ", text)
    scrubbed = _PMCC_ID.sub(" ", scrubbed)
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


_VERBATIM_QUOTE = re.compile(r'“([^”]+)”|"([^"]+)"')


def _evidence_texts(payload: dict[str, Any]) -> list[str]:
    return [
        " ".join(str(src.get("text", "")).split())
        for src in payload.get("sources") or []
        if isinstance(src, dict) and src.get("kind") == "evidence"
    ]


def _without_evidence_text(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload minus the text of third-party sources (posts, headlines, filing excerpts):
    a number someone else wrote must not ground a claim (W13). Knowledge-base and run-facts
    sources keep their text."""
    sources = payload.get("sources")
    if not isinstance(sources, list):
        return payload
    kept = [
        {k: v for k, v in src.items() if k != "text"}
        if isinstance(src, dict) and src.get("kind") == "evidence"
        else src
        for src in sources
    ]
    return {**payload, "sources": kept}


def _without_verbatim_quotes(narrative: str, payload: dict[str, Any]) -> str:
    """``narrative`` with every quotation that is copied verbatim from an evidence source blanked
    out: quoting a post accurately states what the post says, not a computed figure, so its
    numbers are not claims. A paraphrase or an altered quote stays in and is checked."""
    texts = _evidence_texts(payload)
    if not texts:
        return narrative

    def blank(m: re.Match[str]) -> str:
        quoted = " ".join((m.group(1) or m.group(2) or "").split()).rstrip("….").strip()
        if len(quoted) >= 12 and any(quoted in t for t in texts):
            return " "
        return m.group(0)

    return _VERBATIM_QUOTE.sub(blank, narrative)


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
    allowed = collect_payload_numbers(_without_evidence_text(payload))
    found = extract_narrative_numbers(_without_verbatim_quotes(narrative, payload))
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
_NOT_RUN_DATA = frozenset({"sources", "disclaimer", "tax_disclaimer", "question"})


def _without_keys(value: Any, keys: frozenset[str]) -> Any:
    """``value`` with the named dict keys removed at every depth."""
    if isinstance(value, dict):
        return {k: _without_keys(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list | tuple):
        return [_without_keys(v, keys) for v in value]
    return value


def _run_numbers(payload: dict[str, Any]) -> set[float]:
    """Numbers that identify this run (positions, portfolio, allocation…), not quoted sources.

    The user's own question is not run data wherever it sits in the payload: a tax reply nests it
    under ``tax``, and "Section 1256" or "Form 1099-B" in a question must not make the education
    paragraph that explains them look like it leaks a run number.
    """
    core = _without_keys(payload, _NOT_RUN_DATA)
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
_EARNINGS_UNKNOWN_WORDS = re.compile(
    r"\bearnings\b.*\b(?:unknown|not known|could not be confirmed|unconfirmed)\b"
    r"|\b(?:unknown|unconfirmed)\b.*\bearnings\b|earnings_unknown",
    re.IGNORECASE,
)
_EASING_WORDS = re.compile(r"\b(?:easing|weakening|new supply)\b|bottleneck_easing", re.IGNORECASE)


# Suitability codes that describe the sized portfolio itself. A rewrite of the narrative cannot
# change them, so a run that fails on one is withheld at once (W12). The one text-only code,
# ``earnings_unflagged_conservative``, is fixed by saying "earnings" in the sentence, so it
# keeps the normal retry.
TEXT_SUITABILITY_CODES = frozenset({"earnings_unflagged_conservative"})
WITHHELD_NOTICE = "This screen was withheld: the sized portfolio does not suit the stated account."


def fact_suitability_codes(report: ComplianceReport | None) -> list[str]:
    """Reason codes of a failed ``check_suitability`` that no rewrite can fix, in order."""
    if report is None:
        return []
    out: list[str] = []
    for c in report.checks:
        if c.name == "check_suitability" and not c.passed:
            out += [code for code in c.locations if code not in TEXT_SUITABILITY_CODES]
    return list(dict.fromkeys(out))


def withheld_reason_codes(report: ComplianceReport) -> list[str]:
    """What a withheld notice names: the fact codes, else the names of the failed checks."""
    return fact_suitability_codes(report) or [c.name for c in report.failed_checks]


def withheld_narrative(report: ComplianceReport, disclaimer: str) -> Narrative:
    """The fixed text that replaces a narrative the gate would not release (W12, PRD 13.1)."""
    codes = withheld_reason_codes(report)
    failed = ", ".join(c.name for c in report.failed_checks) or "none"
    return Narrative(
        paragraphs=[
            Paragraph(
                mode="notice",
                text=f"{WITHHELD_NOTICE} Reason codes: {', '.join(codes)}. Failed checks: "
                f"{failed}. The candidate tables and the constraint checks are computed facts and "
                "are shown; the sized positions and the explanation are not.",
            ),
            Paragraph(mode="notice", text=disclaimer),
        ]
    )


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
    # W5: any profile; a sized position whose earnings date is unknown is named as such
    for cid in facts.earnings_unknown_ids:
        if not any(cid in s and _EARNINGS_UNKNOWN_WORDS.search(s) for s in _sentences(text)):
            out.append(
                (
                    "earnings_unknown_unflagged",
                    f"{cid} has no confirmed earnings date but the text does not say so "
                    "in the same sentence",
                )
            )
            break
    if facts.risk_profile == "conservative" and facts.bottleneck_easing_flagged:
        # Phase 11 (4A.8): a short put on a supplier whose bottleneck is easing is flagged, and a
        # conservative reader is told so in the sentence that names the candidate
        for cid in facts.bottleneck_easing_flagged:
            if not any(cid in s and _EASING_WORDS.search(s) for s in _sentences(text)):
                out.append(
                    (
                        "bottleneck_easing_unflagged_conservative",
                        f"{cid} carries the bottleneck_easing flag (new supply or decelerating "
                        "prices in its layer) but the text does not say so in the same sentence",
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
def _ages_like_a_filing(c: Citation) -> bool:
    """Rules, SEC filings and the bottleneck evidence pack (filing excerpts, price points and
    headlines indexed as ``bottleneck-<theme>-<layer>`` evidence) age; concepts do not."""
    if c.kind in ("rules", "filings"):
        return True
    return c.kind == "evidence" and c.doc_id.startswith("bottleneck-")


def check_sources_fresh(
    citations: Sequence[Citation], cfg: ComplianceConfig, today: date | None = None
) -> ComplianceCheck:
    """Check 7 (warn): a cited rule, filing or bottleneck evidence item older than
    ``max_age_days`` may be out of date; a cited bottleneck board whose snapshot ``as_of`` is older
    than ``max_snapshot_age_days`` reports a constraint the daily job has not re-measured (Phase 11,
    step 11.5). Both compare against the data clock passed as ``today``."""
    today = today or date.today()
    stale: list[str] = []
    old_board: list[str] = []
    for c in citations:
        if c.as_of is None:
            continue
        age = (today - c.as_of).days
        if c.doc_id == BOTTLENECK_BOARD_DOC_ID:
            if age > cfg.max_snapshot_age_days:
                old_board.append(c.tag or c.doc_id)
        elif _ages_like_a_filing(c) and age > cfg.max_age_days:
            stale.append(c.tag or c.doc_id)
    problems: list[str] = []
    if stale:
        problems.append(
            f"{', '.join(stale)} older than {cfg.max_age_days} days (source may be out of date)"
        )
    if old_board:
        problems.append(
            f"{', '.join(old_board)} snapshot older than {cfg.max_snapshot_age_days} days "
            "(bottleneck snapshot may be out of date)"
        )
    return ComplianceCheck(
        name="check_sources_fresh",
        passed=not problems,
        severity="warn",
        detail="; ".join(problems) or "cited rules and filings are current",
        locations=stale + old_board,
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
_STATUS_WORDS = ("fits", "stretch", "does not fit")
_FIRE_VARIANTS = ("lean", "regular", "fat", "coast", "barista")


def check_goal_narrative(
    narrative: Narrative,
    payload: dict[str, Any],
    cfg: ComplianceConfig,
    text_kind: TextKind = "answer",
) -> ComplianceCheck:
    """Check 9 (Phase 12): a Goal Planning reply states the verdict, keeps the stress path beside
    any projection, never promises a projected figure, and (FIRE) names the variant and sources
    the withdrawal rate. Applies to goal replies only: a screening report that carries a plan has
    it in the payload to ground numbers, and its narrative is the Education agent's."""
    plan = payload.get("goal_plan")
    if text_kind != "answer" or not isinstance(plan, dict) or plan.get("clarification"):
        return ComplianceCheck(name="goal_narrative", passed=True, detail="no goal reply to check")
    text = narrative.markdown
    low = text.lower()
    problems: list[str] = []
    rules = cfg.goal
    if rules.require_status and not any(w in low for w in _STATUS_WORDS):
        problems.append("the verdict (fits / stretch / does not fit) is not stated")
    projection = plan.get("projection") or {}
    if rules.require_stress_path and projection.get("base") is not None and "stress" not in low:
        problems.append("a projection is shown without naming the stress path")
    promise = re.compile(rules.promise_pattern, re.IGNORECASE)
    hits = sorted({m.group(0).lower() for m in promise.finditer(text)})
    if hits:
        problems.append(f"projected figures are promised ({', '.join(hits)}); use 'would'")
    fire = plan.get("fire")
    if isinstance(fire, dict) and rules.fire_requires_withdrawal_source:
        variant = str(fire.get("variant", "")).lower()
        if variant in _FIRE_VARIANTS and variant not in low:
            problems.append(f"the FIRE variant ({variant}) is not named")
        if "withdrawal" not in low:
            problems.append("the withdrawal rate is not mentioned")
        if "diversified" not in low:
            problems.append("the reply does not source the rate to diversified-portfolio research")
    return ComplianceCheck(
        name="goal_narrative",
        passed=not problems,
        detail="; ".join(problems) if problems else "verdict stated, stress path kept, no promises",
    )


_QUOTED_SPAN = re.compile(r"[\"“]([^\"”]{12,300})[\"”]")


def _norm_headline(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def check_news_grounding(narrative: Narrative, payload: dict[str, Any]) -> ComplianceCheck:
    """Check 10 (Phase 12): every quoted span in a News Desk reply is a headline the payload
    carries, verbatim. Passes trivially when the payload holds no headlines."""
    news = payload.get("news")
    if not isinstance(news, dict) or not news.get("headlines"):
        return ComplianceCheck(name="news_grounding", passed=True, detail="no headlines to check")
    titles = {_norm_headline(str(h.get("title", ""))) for h in news["headlines"]}
    bad: list[str] = []
    checked = 0
    for p in narrative.paragraphs:
        if p.mode == "education":
            continue  # cited education text quotes its sources, which check_citations verifies
        for span in _QUOTED_SPAN.findall(p.text):
            checked += 1
            if _norm_headline(span) not in titles:
                bad.append(span[:80])
    return ComplianceCheck(
        name="news_grounding",
        passed=not bad,
        detail=(
            f"quoted text is not a fetched headline: {'; '.join(bad)}"
            if bad
            else f"{checked} quoted headline(s) match the fetched items"
        ),
        locations=bad,
    )


def check_tax_reply(
    narrative: Narrative, payload: dict[str, Any], cfg: ComplianceConfig
) -> ComplianceCheck:
    """Check 11 (Phase 12): a Tax & Accounts reply carries the tax disclaimer exactly once, states
    no rate a reader will pay and gives no filing instruction. Passes trivially otherwise."""
    tax = payload.get("tax")
    if not isinstance(tax, dict):
        return ComplianceCheck(name="tax_reply", passed=True, detail="no tax reply to check")
    rules = cfg.tax
    text = narrative.markdown
    problems: list[str] = []
    n = text.count(rules.disclaimer)
    if n != 1:
        problems.append(f"tax disclaimer appears {n} time(s), expected once")
    if rules.forbid_rates:
        hits = [m.group(0) for m in re.finditer(rules.rate_pattern, text, re.IGNORECASE)]
        if hits:
            problems.append(f"a tax rate is stated ({'; '.join(hits[:3])})")
    imperatives = [
        m.group(0).strip() for m in re.finditer(rules.imperative_pattern, text, re.IGNORECASE)
    ]
    if imperatives:
        problems.append(f"filing instruction in the imperative ({'; '.join(imperatives[:3])})")
    return ComplianceCheck(
        name="tax_reply",
        passed=not problems,
        detail="; ".join(problems) if problems else "tax disclaimer once, no rate, no instruction",
    )


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
    """Run the eleven checks (eight of 13.1 plus the goal, news and tax checks of Phase 12);
    ``passed`` is False on any blocking failure. Warnings never block."""
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
        check_goal_narrative(narrative, payload, cfg, text_kind),
        check_news_grounding(narrative, payload),
        check_tax_reply(narrative, payload, cfg),
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
