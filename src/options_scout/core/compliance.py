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
import unicodedata
import uuid
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from options_scout.config import ComplianceConfig
from options_scout.core.grounding import (
    CANDIDATE_ID,
    GAIN_WORDS,
    LOSS_WORDS,
    SLOT,
    Entry,
    GroundingResult,
    SlotError,
    display_variants,
    extract_numbers,
    ground_narrative,
    matching_paths,
    payload_entries,
    render_narrative,
    render_slots,
    scrub_identifiers,
    short_option_losses,
    source_entries,
    unstated_losses,
)
from options_scout.core.grounding import PMCC_ID as _PMCC_ID
from options_scout.core.models import (
    BOTTLENECK_BOARD_DOC_ID,
    DELAYED_DATA_NOTICE,
    NO_SOURCE_SENTENCE,
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

# "the risk-free rate" names the T-bill yield the payload supplies (``risk_free_rate_pct``); it is
# terminology, not a claim that something carries no risk
RISK_FREE_RATE_TERM = re.compile(r"\brisk[- ]?free(?:\s+interest)?\s+rates?\b", re.IGNORECASE)


def banned_phrases_in(text: str) -> list[str]:
    """The ``BANNED_PHRASES`` that occur in ``text`` (normalised, W15), after removing the
    risk-free rate term."""
    low = RISK_FREE_RATE_TERM.sub(" ", normalise_for_language(text).lower())
    return sorted({p for p in BANNED_PHRASES if p in low})


# ------------------------------------------------------------- W15: text normalisation
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e\u034f"))
_ASCII_PUNCT = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'", "\u02bc": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"',
        "\u00ab": '"', "\u00bb": '"',
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
    }
)  # fmt: skip
# Cyrillic and Greek letters that look like Latin ones (a small table, not the full Unicode
# confusables list); folded so "Y\u043eu sh\u043euld" reads "You should"
_LOOKALIKES = str.maketrans(
    "\u0430\u0435\u043e\u0440\u0441\u0443\u0445\u0456\u0458\u0455\u0501\u04bb\u04cf\u051b\u051d\u0442\u043c\u043d\u043a\u0432"
    "\u0410\u0412\u0415\u041a\u041c\u041d\u041e\u0420\u0421\u0422\u0425\u0423\u0406\u0408\u0405"
    "\u03b1\u03bf\u03bd\u03c1\u03b9\u03ba\u03c5\u03b5\u03c4"
    "\u0391\u0392\u0395\u0396\u0397\u0399\u039a\u039c\u039d\u039f\u03a1\u03a4\u03a5\u03a7",
    "aeopcyxijsdhlqwtmhkbABEKMHOPCTXYIJSaovpikuetABEZHIKMNOPTYX",
)
_HTML_TAG = re.compile(r"</?[A-Za-z][^<>]{0,200}>")
_MD_EMPHASIS = re.compile(r"[*_~`]+")
_SPACES = re.compile(r"\s+")


def normalise_for_language(text: str) -> str:
    """The text the language patterns run on (W15 step 2): NFKC (full-width letters, non-breaking
    spaces), invisible characters deleted, curly quotes and dashes to ASCII, accents stripped,
    look-alike Cyrillic and Greek letters folded to Latin, HTML tags and Markdown emphasis
    removed, whitespace collapsed. Case is kept (the patterns run case-insensitive, and the
    ticker patterns need the capitals)."""
    t = unicodedata.normalize("NFKC", text).translate(_INVISIBLE).translate(_ASCII_PUNCT)
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    t = t.translate(_LOOKALIKES)
    t = _MD_EMPHASIS.sub("", _HTML_TAG.sub("", t))
    return _SPACES.sub(" ", t).strip()


# Function words: a paragraph where those of other languages outnumber the English ones is not
# English (W15 step 5). Words that are also English ("a", "in", "do", "per") are left out.
_ENGLISH_WORDS = frozenset(
    [
        "the",
        "and",
        "of",
        "to",
        "is",
        "that",
        "for",
        "on",
        "with",
        "as",
        "it",
        "this",
        "are",
        "be",
        "at",
        "by",
        "or",
        "an",
        "if",
        "its",
        "from",
        "which",
        "not",
        "than",
        "when",
        "their",
        "was",
        "has",
        "have",
        "will",
        "can",
        "may",
    ]
)
_FOREIGN_WORDS = frozenset(
    [
        "el",
        "la",
        "los",
        "las",
        "del",
        "que",
        "y",
        "en",
        "un",
        "una",
        "por",
        "para",
        "con",
        "es",
        "se",
        "al",
        "lo",
        "como",
        "mas",
        "pero",
        "sus",
        "su",
        "muy",
        "le",
        "les",
        "des",
        "et",
        "est",
        "du",
        "une",
        "pour",
        "dans",
        "qui",
        "sur",
        "pas",
        "avec",
        "sont",
        "der",
        "die",
        "das",
        "und",
        "ist",
        "nicht",
        "mit",
        "ein",
        "eine",
        "zu",
        "von",
        "auf",
        "sie",
        "wir",
        "il",
        "di",
        "che",
        "della",
        "sono",
        "gli",
        "da",
        "em",
        "os",
        "ao",
        "nao",
        "uma",
        "voce",
    ]
)
_WORD = re.compile(r"[^\W\d_]+")


def non_english(text: str) -> str | None:
    """Why ``text`` does not read as English, or ``None``. The product is English-only: a
    paragraph whose letters are mostly outside the Latin script, or whose function words are
    mostly another language's, fails (W15 step 5)."""
    letters = [c for c in unicodedata.normalize("NFKC", text) if c.isalpha()]
    if len(letters) >= 8:
        other = sum(1 for c in letters if not unicodedata.name(c, "").startswith("LATIN"))
        if other / len(letters) > 0.3:
            return f"{other} of {len(letters)} letters are outside the Latin script"
    words = _WORD.findall(normalise_for_language(text).lower())
    foreign = sum(w in _FOREIGN_WORDS for w in words)
    english = sum(w in _ENGLISH_WORDS for w in words)
    if len(words) >= 6 and foreign >= 3 and foreign > english:
        return f"{foreign} non-English function words against {english} English"
    return None


__all__ = [
    "CANDIDATE_ID",
    "GroundingResult",
    "SlotError",
    "ground_narrative",
    "render_narrative",
    "render_slots",
]

_SOURCE_TAG = re.compile(SOURCE_TAG)
_ABS_TOL = 1e-9  # W14: was 0.0051, which matched anything near zero


def collect_payload_numbers(payload: Any, out: set[float] | None = None) -> set[float]:
    """Every numeric value in the payload with its display roundings and, for fractions, the
    percent forms. Kept for callers that want the flat set; the checks match by kind and sign
    through ``core.grounding`` instead."""
    out = set() if out is None else out
    for e in payload_entries(payload, skip=frozenset()):
        out.update(display_variants(e.value))
        if abs(e.value) <= 1.5:  # fractions may be written as percents
            out.update(display_variants(e.value * 100)[1:])
    return out


def extract_narrative_numbers(text: str) -> list[tuple[str, float, bool]]:
    """Numbers in the narrative as ``(token, value, is_percent)``: digits with unit suffixes,
    number words and multipliers; candidate ids, dates, bare years and day ordinals excluded."""
    return [(n.text, n.value, n.kind == "pct") for n in extract_numbers(text)]


def _matches(value: float, allowed: Iterable[float], rel_tol: float) -> bool:
    return any(
        a == value or math.isclose(a, value, rel_tol=rel_tol, abs_tol=_ABS_TOL) for a in allowed
    )


def _loss_near(text: str, start: int, end: int) -> bool:
    return bool(LOSS_WORDS.search(text[max(0, start - 60) : start] + " " + text[end : end + 30]))


def _gain_before(text: str, start: int) -> bool:
    window = text[max(0, start - 40) : start]
    return bool(GAIN_WORDS.search(window)) and not LOSS_WORDS.search(window)


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
    allowed: list[Entry] = payload_entries(payload) + source_entries(payload)
    body = scrub_identifiers(_without_verbatim_quotes(narrative, payload))
    found = extract_numbers(body, scrubbed=True)
    if source_count is None:
        source_count = len(payload.get("sources") or [])
    unknown = unknown_source_tags(narrative, source_count)
    ungrounded: list[str] = []
    for tok in found:
        loss = (
            False
            if (not tok.sign and _gain_before(body, tok.start))
            else _loss_near(body, tok.start, tok.end)
        )
        if not matching_paths(tok, allowed, rel_tol, loss_context=loss):
            ungrounded.append(tok.text)
    banned = banned_phrases_in(narrative)
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
_HANDLE = re.compile(r"(?<![\w/.])@[A-Za-z0-9_]{2,}|\b[ur]/[A-Za-z0-9_\-]{2,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_NAKED = re.compile(r"\bnaked\b|\buncovered put", re.IGNORECASE)
_LEVERAGE_OPPORTUNITY = re.compile(
    r"\b(?:leverage|margin)\b[^.]{0,80}\b(?:opportunit|boost|enhance|amplif|juice|free(?:s|d)? up)",
    re.IGNORECASE,
)


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
            + (f"not grounded: {'; '.join(bad)}" if bad else "all grounded")
        ),
        locations=list(bad),
    )


# ------------------------------------------------- W16: a paragraph's mode follows its content
# Slots a model-written notice may hold: the fixed texts and the sizer's own warnings
_NOTICE_SLOT = re.compile(
    r"(?:disclaimer|tax_disclaimer|delayed_data_notice|risk\.warnings\[[^\]]*\])", re.IGNORECASE
)
_BOLD_LABEL = re.compile(r"^\s*\*\*[^*\n]{1,60}\*\*\s*")
_BOLD_LABEL_ONLY = re.compile(r"^\s*\*\*[^*\n]{1,60}\*\*\s*$")


def _fold(text: str) -> str:
    """``text`` reduced to lower-case words for comparing fixed texts and quotations: the
    language normalisation (NFKC, curly quotes, look-alikes, Markdown), then letters and digits
    only."""
    return " ".join(re.findall(r"[a-z0-9]+", normalise_for_language(text).lower()))


def fixed_notices(disclaimer: str, cfg: ComplianceConfig) -> list[str]:
    """The fixed texts a model may write as a ``notice``, folded, longest first."""
    texts = [disclaimer, cfg.reminder, cfg.tax.disclaimer, NO_SOURCE_SENTENCE, DELAYED_DATA_NOTICE]
    return sorted({f for t in texts if (f := _fold(t))}, key=len, reverse=True)


def is_fixed_notice(p: Paragraph, fixed: Sequence[str]) -> bool:
    """True when the paragraph holds only fixed texts (written out or slotted) and the sizer's
    warnings, after an optional bold label (W16 step 2)."""
    template = p.template if p.template is not None else p.text
    rest = SLOT.sub(lambda m: " " if _NOTICE_SLOT.fullmatch(m.group(1).strip()) else "\0", template)
    if "\0" in rest:
        return False  # a slot into run data: that is a screen result, not a notice
    folded = _fold(_BOLD_LABEL.sub(" ", rest, count=1))
    for f in fixed:
        folded = folded.replace(f, " ")
    return not folded.strip()


def demoted_notices(narrative: Narrative, fixed: Sequence[str]) -> list[int]:
    """Indices of model-written ``notice`` paragraphs that are not fixed texts: checked as
    ``education``, so they need a citation and may carry no run data (W16 step 2)."""
    return [
        i
        for i, p in enumerate(narrative.paragraphs)
        if p.written_by == "model" and p.mode == "notice" and not is_fixed_notice(p, fixed)
    ]


def checked_narrative(narrative: Narrative, demoted: Sequence[int]) -> Narrative:
    """The narrative as the checks see it: demoted notices carry the ``education`` mode."""
    if not demoted:
        return narrative
    return Narrative(
        paragraphs=[
            p.model_copy(update={"mode": "education"}) if i in demoted else p
            for i, p in enumerate(narrative.paragraphs)
        ]
    )


def _payload_tickers(payload: Any, out: set[str] | None = None) -> set[str]:
    """Values of ``ticker`` / ``underlying`` fields in the run's data (not its sources)."""
    out = set() if out is None else out
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k in _NOT_RUN_DATA:
                continue
            if k in ("ticker", "underlying") and isinstance(v, str) and v.strip():
                out.add(v.strip().upper())
            else:
                _payload_tickers(v, out)
    elif isinstance(payload, list | tuple):
        for v in payload:
            _payload_tickers(v, out)
    return out


def _reference_pattern(
    payload: dict[str, Any], run_tickers: Sequence[str], run_terms: Sequence[str] = ()
) -> re.Pattern[str]:
    """What ties a sentence to this run: a slot, a candidate id, a run ticker, a named part of
    the run's output (``citations.run_terms``: "the quality screen", "the bottleneck board"), or
    the goal verdict / FIRE variant the payload computed. A typed figure counts as well (checked
    separately by ``check_numbers``, which grounds it in the run's data)."""
    words = {t for t in [*run_tickers, *_payload_tickers(payload)] if len(t) >= 2}
    alts = [SLOT.pattern, CANDIDATE_ID.pattern, _PMCC_ID.pattern, *run_terms]
    if words:
        alts.append(r"\b(?:" + "|".join(map(re.escape, sorted(words))) + r")\b")
    plan = payload.get("goal_plan")
    if isinstance(plan, dict):
        alts.append(r"\b(?:fits|stretch|does not fit)\b")
        fire = plan.get("fire")
        if isinstance(fire, dict) and fire.get("variant"):
            alts.append(r"(?i:\b" + re.escape(str(fire["variant"])) + r"\b)")
    return re.compile("|".join(f"(?:{a})" for a in alts))


def general_claims(p: Paragraph, refs: re.Pattern[str], fixed: Sequence[str] = ()) -> list[str]:
    """Sentences of a model-written ``screen_result`` that name nothing from this run: no slot,
    candidate id, run ticker or figure. They are general claims and need a citation like an
    education sentence (W16 step 3). Read on the template, where the slots still show. A
    sentence that is part of one of the app's fixed texts ("these are screened candidates …,
    not recommendations") is the app's own caveat, not a claim."""
    if p.written_by != "model" or p.mode != "screen_result":
        return []
    out: list[str] = []
    for s in _sentences(p.template if p.template is not None else p.text):
        if _BOLD_LABEL_ONLY.match(s) or not re.search(r"[A-Za-z]", s):
            continue
        if refs.search(s) or extract_numbers(s):
            continue
        folded = _fold(s)
        if folded and any(folded in f for f in fixed):
            continue
        out.append(s.strip())
    return out


# Quotation marks after ``normalise_for_language`` (curly quotes and guillemets become ASCII). A
# single quote opens only after a non-word character, so apostrophes inside words never do.
_DOUBLE_QUOTED = re.compile(r'"([^"]+)"')
_SINGLE_QUOTED = re.compile(r"(?<![A-Za-z0-9])'([^']+)'(?![A-Za-z0-9])")
_ELLIPSIS = re.compile(r"\.\.\.|\[\s*\.\.\.\s*\]")


def quoted_spans(text: str, min_chars: int) -> list[str]:
    """Quoted spans of at least ``min_chars`` characters, in double or single quotes or
    guillemets."""
    t = normalise_for_language(text)
    spans = [m.group(1) for m in _DOUBLE_QUOTED.finditer(t)]
    spans += [m.group(1) for m in _SINGLE_QUOTED.finditer(t)]
    # a quoted slot is a value the app filled in ("{{...flags|list}}"), not words put in anyone's
    # mouth; the template is read, so the slot still shows
    return [s for s in spans if len(s.strip()) >= min_chars and not SLOT.search(s)]


def quote_found(span: str, corpus: Sequence[str]) -> bool:
    """True when every part of ``span`` (split at an elision "...") occurs in one corpus text,
    compared as folded words."""
    parts = [f for part in _ELLIPSIS.split(span) if (f := _fold(part))]
    if not parts:
        return True
    return any(all(f" {part} " in f" {text} " for part in parts) for text in corpus)


def _payload_strings(value: Any, skip: frozenset[str] = frozenset()) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            if k not in skip:
                out += _payload_strings(v, skip)
    elif isinstance(value, list | tuple):
        for v in value:
            out += _payload_strings(v, skip)
    return out


_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "nor",
        "so",
        "yet",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "from",
        "with",
        "without",
        "into",
        "onto",
        "over",
        "under",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "do",
        "does",
        "did",
        "doing",
        "done",
        "have",
        "has",
        "had",
        "having",
        "it",
        "its",
        "it's",
        "this",
        "that",
        "these",
        "those",
        "there",
        "here",
        "which",
        "who",
        "whom",
        "whose",
        "what",
        "when",
        "where",
        "why",
        "how",
        "than",
        "then",
        "also",
        "too",
        "very",
        "just",
        "only",
        "such",
        "same",
        "other",
        "another",
        "each",
        "every",
        "any",
        "all",
        "both",
        "either",
        "neither",
        "some",
        "more",
        "most",
        "less",
        "least",
        "much",
        "many",
        "few",
        "can",
        "could",
        "may",
        "might",
        "must",
        "shall",
        "should",
        "will",
        "would",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "our",
        "their",
        "one",
        "ones",
        "if",
        "because",
        "while",
        "about",
        "after",
        "before",
        "between",
        "during",
        "through",
        "up",
        "down",
        "out",
        "off",
        "again",
        "further",
        "once",
    ]
)
_CONTENT_WORD = re.compile(r"[a-z][a-z'\-]*[a-z]|[a-z]")


def _stem(word: str) -> str:
    w = word.replace("'", "")
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)]
    return w


def content_words(text: str) -> set[str]:
    """Stemmed words of ``text`` outside a small stop list (negations are kept: "cannot" carries
    meaning)."""
    low = _SOURCE_TAG.sub(" ", normalise_for_language(text).lower())
    out: set[str] = set()
    for w in _CONTENT_WORD.findall(low):
        for part in w.split("-"):
            if len(part) >= 3 and part not in _STOPWORDS:
                out.add(_stem(part))
    return out


def support_share(sentence: str, corpus: Sequence[str]) -> tuple[float, int]:
    """Share of the sentence's content words found in the corpus, and how many it has."""
    words = content_words(sentence)
    if not words:
        return 1.0, 0
    have: set[str] = set()
    for text in corpus:
        have |= content_words(text)
    return len(words & have) / len(words), len(words)


def _chunk_texts(sources: Sequence[Citation], payload: dict[str, Any] | None) -> dict[str, str]:
    """``Sn`` → the text the writer was shown for that source: its title, its quote and the
    chunk text the payload carries (the quote is the start of that text in the app)."""
    texts: dict[str, str] = {}
    by_tag: dict[str, str] = {}
    for src in (payload or {}).get("sources") or []:
        if isinstance(src, dict) and src.get("tag"):
            by_tag[str(src["tag"])] = str(src.get("text", ""))
    for i, c in enumerate(sources, start=1):
        tag = f"S{i}"
        texts[tag] = f"{c.title}. {c.quote} {by_tag.get(tag, '')}"
    return texts


def _tags_in(text: str) -> list[str]:
    return [f"S{n}" for n in _SOURCE_TAG.findall(text)]


# ----------------------------------------------------------------------- 2 check_citations
def check_citations(
    narrative: Narrative,
    sources: Sequence[Citation],
    *,
    payload: dict[str, Any] | None = None,
    cfg: ComplianceConfig | None = None,
    disclaimer: str = "",
    run_tickers: Sequence[str] = (),
    demoted: Sequence[int] = (),
) -> ComplianceCheck:
    """Every ``[Sn]`` exists; every education paragraph cites; a model's ``screen_result``
    sentence that names nothing from the run cites too; quotations occur in the cited chunks
    (or, uncited, in the run's data); each cited sentence shares enough of its words with the
    chunk it cites (W16). ``narrative`` is the checked narrative (demoted notices already carry
    the ``education`` mode); ``demoted`` names them for the message."""
    from options_scout.config import CitationRulesConfig

    rules = cfg.citations if cfg is not None else CitationRulesConfig()
    fixed = fixed_notices(disclaimer, cfg) if cfg is not None and disclaimer else []
    chunks = _chunk_texts(sources, payload)
    run_text = _payload_strings(payload or {}, frozenset({"previous_attempt_problems"}))
    run_text_folded = [_fold(t) for t in run_text]
    refs = _reference_pattern(payload or {}, run_tickers, rules.run_terms)
    glossary = {_fold(t) for t in (cfg.allow_terms if cfg is not None else [])}
    problems: list[str] = []
    locations: list[str] = []

    def flag(i: int, why: str) -> None:
        problems.append(f"{_loc(i)}: {why}")
        if _loc(i) not in locations:
            locations.append(_loc(i))

    unknown = unknown_source_tags(narrative.markdown, len(sources))
    for p in narrative.paragraphs:
        unknown += [t for t in p.citations if t not in unknown and int(t[1:]) > len(sources)]
    if unknown:
        problems.append(f"tags not in sources: {', '.join(sorted(set(unknown)))}")
        locations += sorted(set(unknown))  # pragma: no mutate (locations is empty here)
    for i, p in enumerate(narrative.paragraphs):
        para_tags = [t for t in dict.fromkeys([*p.citations, *_tags_in(p.text)]) if t in chunks]
        if p.mode == "education" and not _is_cited(p):
            why = "education paragraph without a citation"
            if i in demoted:
                why = (
                    "notice paragraph that is not one of the app's fixed notices is checked as "
                    "education and has no citation (data caveats go in the fixed notice slots)"
                )
            flag(i, why)
        claims = general_claims(p, refs, fixed)
        for s in claims:
            if not _tags_in(s):
                flag(
                    i,
                    "screen_result sentence names nothing from this run (no slot, candidate id, "
                    f"run ticker or figure), so it is a general claim and needs a citation: {s!r}",
                )
        # step 4: quotations come from what is cited, or, uncited, from the run's own data
        corpus = [_fold(chunks[t]) for t in para_tags]
        if p.mode != "education":  # a result may quote the run's own text (a reason as given)
            corpus += run_text_folded
        written = p.template if p.template is not None else p.text
        for span in quoted_spans(written, rules.quote_min_chars):
            if _fold(span) in glossary:
                continue  # a quoted glossary term ("sell to open") names an order, it quotes no one
            if not quote_found(span, corpus):
                where = "the cited source"
                if p.mode != "education":
                    where = "the sources or this run's data"
                flag(i, f"quotation not found in {where}: {span[:80]!r}")
        # step 5: each cited sentence shares enough of its words with what it cites
        if not (p.mode == "education" or claims) or not para_tags:
            continue
        checked = _sentences(p.text) if p.mode == "education" else claims
        for s in checked:
            if fixed and is_fixed_notice(Paragraph(mode="notice", text=s), fixed):
                continue  # a fixed text (the tax disclaimer) inside the paragraph
            tags = [t for t in _tags_in(s) if t in chunks] or para_tags
            share, n = support_share(s, [chunks[t] for t in tags])
            if n >= rules.support_min_words and share < rules.support_min_share:
                flag(
                    i,
                    f"{'/'.join(tags)} does not support {s.strip()[:80]!r} ({share:.0%} of its "
                    f"words occur in the source, need {rules.support_min_share:.0%})",
                )
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
    losses = short_option_losses(payload)
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
            for cid in unstated_losses(p, payload, rel_tol=rel_tol, losses=losses):
                why = "" if cid in losses else " (the payload has no realistic loss for it)"
                problems.append(
                    f"{_loc(i)}: short option {cid} described without its own realistic loss{why}"
                )
                locations.append(_loc(i))
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
# change them, so a run that fails on one is withheld at once (W12). Every other code is about
# wording (a flag the text must state, language it must not use) and keeps the normal retry; an
# explicit list of fact codes means a new code defaults to the retry, never to withholding.
FACT_SUITABILITY_CODES = frozenset(
    {
        "margin_on_cash",
        "loss_over_limit",
        "too_many_positions",
        "pmcc_without_leaps",
        "buying_power_below_minimum",
    }
)
_ONE_STOCK = re.compile(r"\b(?:one|single)[- ](?:stock|name|underlying|ticker)\b", re.IGNORECASE)
WITHHELD_NOTICE = "This screen was withheld: the sized portfolio does not suit the stated account."


def fact_suitability_codes(report: ComplianceReport | None) -> list[str]:
    """Reason codes of a failed ``check_suitability`` that no rewrite can fix, in order."""
    if report is None:
        return []
    out: list[str] = []
    for c in report.checks:
        if c.name == "check_suitability" and not c.passed:
            out += [code for code in c.locations if code in FACT_SUITABILITY_CODES]
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
    # W6: what the sizer left behind must be said, not hidden behind "all constraints pass"
    low = text.lower()
    if facts.account_too_small and "too small" not in low:
        out.append(
            (
                "account_too_small_unstated",
                "nothing was sized because the account is too small for the top-ranked "
                "underlyings, but the text does not say the account is too small",
            )
        )
    if facts.single_ticker and not any(
        facts.single_ticker in s and _ONE_STOCK.search(s) for s in _sentences(text)
    ):
        out.append(
            (
                "single_name_unstated",
                f"every sized position is on {facts.single_ticker} but no sentence names it as a "
                "one-stock (single-name) portfolio",
            )
        )
    if facts.ranking_not_followed and "did not fit" not in low:
        out.append(
            (
                "ranking_not_followed_unstated",
                "higher-ranked underlyings did not fit this account size and the text does not "
                "say they did not fit",
            )
        )
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
def _term_pattern(term: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in re.split(r"[\s-]+", normalise_for_language(term)) if w]
    return re.compile(r"(?<![\w-])\"?" + r"[\s-]".join(words) + r"\"?(?![\w-])", re.IGNORECASE)


def _scrub_allowed(text: str, cfg: ComplianceConfig) -> str:
    """Remove the exact glossary terms of ``cfg.allow_terms`` (quoted or not, spaces and hyphens
    interchangeable). Nothing else is removed: no quoted span, no definition clause (W15 step 3)."""
    for term in cfg.allow_terms:
        text = _term_pattern(term).sub(" ", text)
    return text


def language_violations(narrative: Narrative, cfg: ComplianceConfig) -> list[tuple[int, str, str]]:
    """``(paragraph index, label, matched text)`` for every banned pattern hit, matched on the
    normalised text (W15), plus a ``non_english`` hit for a paragraph that is not English. The
    glossary terms are exempt inside cited education paragraphs only."""
    hits: list[tuple[int, str, str]] = []
    for i, p in enumerate(narrative.paragraphs):
        text = normalise_for_language(p.text)
        if p.mode == "education" and _is_cited(p):
            text = _scrub_allowed(text, cfg)
        for bp in cfg.banned_patterns:
            m = re.search(bp.pattern, text, re.IGNORECASE)
            if m:
                hits.append((i, bp.label, m.group(0)))
        if p.mode != "notice" and (why := non_english(p.text)):
            hits.append((i, "non_english", why))
    return hits


def check_language(narrative: Narrative, cfg: ComplianceConfig) -> ComplianceCheck:
    hits = language_violations(narrative, cfg)
    return ComplianceCheck(
        name="check_language",
        passed=not hits,
        detail="; ".join(f"{_loc(i)}: {label} ({text!r})" for i, label, text in hits)
        or "no directive, certainty, superlative, urgency or rating language; English",
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
    step 11.5); a cited document past its ``review_by`` date states a rule that may have changed
    (W26). All compare against the data clock passed as ``today``."""
    today = today or date.today()
    stale: list[str] = []
    old_board: list[str] = []
    overdue: list[str] = []
    for c in citations:
        if c.review_by is not None and today > c.review_by:
            overdue.append(c.tag or c.doc_id)  # W26: a dated rule past its review date
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
    if overdue:
        problems.append(
            f"{', '.join(dict.fromkeys(overdue))} past its review date (the rule it states may "
            "have changed)"
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
        locations=stale + old_board + list(dict.fromkeys(overdue)),
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
    ``passed`` is False on any blocking failure. Warnings never block.

    W16: the mode of a model-written paragraph is not taken on trust. A model ``notice`` that is
    not one of the fixed texts is checked as ``education`` by every check, and a model
    ``screen_result`` sentence that names nothing from the run needs a citation (check 2)."""
    demoted = demoted_notices(narrative, fixed_notices(disclaimer, cfg))
    narrative = checked_narrative(narrative, demoted)
    text = narrative.markdown
    verification = verify_narrative(
        text,
        payload,
        disclaimer=disclaimer,
        rel_tol=rel_tol,
        attempts=attempts,
        source_count=len(sources),
    )
    # W14: figures are checked per paragraph (slot mode for templated paragraphs, the run's own
    # data only for screen_result and notice text, label-aware for the dangerous labels)
    grounding = ground_narrative(narrative, payload, cfg=cfg.grounding, rel_tol=rel_tol)
    verification = verification.model_copy(
        update={
            "numbers_checked": grounding.numbers_checked,
            "ungrounded_numbers": grounding.problems,
        }
    )
    citations = resolve_citations(narrative, list(sources))
    checks = [
        check_numbers(verification),
        check_citations(
            narrative,
            sources,
            payload=payload,
            cfg=cfg,
            disclaimer=disclaimer,
            run_tickers=run_tickers,
            demoted=demoted,
        ),
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
