"""Number grounding for LLM-written text (W14).

Two paths, chosen per paragraph:

* **Slot mode** (the report explainer). The writer names payload fields as slots,
  ``{{positions[CSP-NKE-2026-11-20-35P].realistic_loss|money}}``, and ``render_slots`` fills them
  from the payload. The paragraph keeps its template, so the checker knows exactly where every
  rendered figure came from: any number the writer typed itself is a violation, an unknown slot
  is a violation, and a slot next to a dangerous label ("maximum loss", "premium", ...) must name
  that label's field. A number can only be wrong if the slot name is wrong.
* **Free-text mode** (concept, goal, tax and chat replies). Numbers are parsed with their unit
  suffixes, number words, multipliers, signs and percent signs, and each must match a payload
  value of the same kind and sign. ``screen_result`` and ``notice`` paragraphs are grounded by
  the run's own data only, never by the user's question or by retrieved text. The same label check
  ties a number next to a dangerous label to that label's field.

The label vocabulary and the literal allow-list live in ``config/compliance.yaml`` (``grounding``).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from options_scout.core.models import SOURCE_TAG

if TYPE_CHECKING:
    from options_scout.config import GroundingConfig, GroundingLabel
    from options_scout.core.models import Narrative, Paragraph

NumKind = Literal["plain", "pct", "multiple", "text"]

# ------------------------------------------------------------------ identifiers, not claims
CANDIDATE_ID = re.compile(r"\b(?:CSP|LEAPS|PMCC|PMCCSC)-[A-Z.\-]+?-\d{4}-\d{2}-\d{2}-[\d.]+[CP]\b")
PMCC_ID = re.compile(r"\bPMCC-[A-Z.]+-\d{4}-\d{2}-\d{2}-[\d.]+C-\d{4}-\d{2}-\d{2}-[\d.]+C\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_SOURCE_TAG = re.compile(SOURCE_TAG)
_DAY_ORDINAL = re.compile(
    r"\b(?:[1-9]|[12]\d|3[01])(?:st|nd|rd|th)\b"
)  # "the 21st"; larger ordinals are claims
_EMPHASIS = re.compile(r"\*\*|__")
_CURRENCY_PREFIX = re.compile(r"\b(?:USD|US\$|EUR|GBP)\s?(?=\d)")
SLOT = re.compile(r"\{\{\s*([^{}|]+?)\s*(?:\|\s*([^{}]*?))?\s*\}\}")

# ------------------------------------------------------------------------ number tokens
_SCALES = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "tn": 1e12, "trillion": 1e12,
}  # fmt: skip
_NUM = re.compile(
    r"(?<![\w.$])(?<![A-Za-z]-)(?P<sign>[-+−])?(?P<cur>\$)?\s?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?"
    r"(?:(?P<pct>\s?%|\s(?:percent|per cent)\b)"
    r"|(?P<mult>[x×](?![\w])|-fold\b|\s(?:times)\b)"
    r"|(?P<scale>(?:k|K|mm|mn|m|M|bn|b|B|tn)\b|\s(?:thousand|million|billion|trillion)\b))?"
    # a figure ends at a word boundary ("14bf735b" is an id), except before an ordinal suffix
    # ("57th") or a glued currency code ("3140USD")
    r"(?=(?:st|nd|rd|th|USD|EUR|GBP)\b|\W|$)"
)
_ONES = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_TEENS = (
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen",
)  # fmt: skip
_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_WORD_VALUE = (
    {w: i + 1 for i, w in enumerate(_ONES)}
    | {w: i + 10 for i, w in enumerate(_TEENS)}
    | {w: (i + 2) * 10 for i, w in enumerate(_TENS)}
)
_WORD_NUM = re.compile(
    rf"\b(?:(?P<tens>{'|'.join(_TENS)})(?:[- ](?P<tens_one>{'|'.join(_ONES)}))?"
    rf"|(?P<teen>{'|'.join(_TEENS)})|(?P<one>{'|'.join(_ONES)}))\b"
    r"(?P<pct>\s+(?:percent|per cent)\b|\s?%)?"
    r"(?P<scale>\s+(?:hundred|thousand|million|billion)\b)?"
    r"(?P<mult>-fold\b|\s+times\b)?",
    re.IGNORECASE,
)
_WORD_SCALE = {"hundred": 1e2, "thousand": 1e3, "million": 1e6, "billion": 1e9}
_MULT_WORD = re.compile(
    r"\b(?:(?P<two>double[ds]?|doubling|twice|twofold)(?!-check|-click)"
    r"|(?P<three>triple[ds]?|tripling|threefold)|(?P<four>quadruple[ds]?|fourfold)"
    r"|(?P<five>fivefold)|(?P<ten>tenfold))\b",
    re.IGNORECASE,
)
_MULT_VALUE = {"two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}

LOSS_WORDS = re.compile(
    r"\b(?:loss(?:es)?|lose[s]?|losing|lost|fall(?:s|ing)?|fell|drop(?:s|ped|ping)?|declin\w*"
    r"|down|crash\w*|deficit|debit|cost[s]?|paid|pay(?:s|ing)?|spent|negative|outflow|shortfall"
    r"|below|short of)\b",
    re.IGNORECASE,
)
GAIN_WORDS = re.compile(
    r"\b(?:gain(?:s|ed)?|profit\w*|rise[sn]?|rising|rose|up|earn\w*|collect\w*|credit|positive"
    r"|grow\w*|grew|increas\w*)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<!\d)[.!?](?=\s|$)|[.!?](?=\s+[A-Z*])|\n\n")
_CLAUSE_BREAK = re.compile(r"[;:()…]|,\s|\s[–—-]\s")

# Payload keys that never ground a claim (W13/W14): retrieved text and the user's own words.
NOT_RUN_DATA = frozenset({"sources", "question", "previous_attempt_problems"})
_PCT_KEY = re.compile(r"pct|percent|percentile|_rate$|^rate$")
_MULT_KEY = re.compile(r"_x$|multiple")
_IDENTITY_FIELDS = ("candidate_id", "ticker", "name", "shock", "layer", "entity", "tag")


@dataclass(frozen=True)
class Num:
    """A number claim in a text: its value with any explicit sign applied, and where it sits."""

    text: str
    value: float
    kind: NumKind
    sign: str  # "+", "-" or "" (no explicit sign)
    start: int
    end: int
    path: str | None = None  # slot mode: the payload field it was rendered from


@dataclass(frozen=True)
class Entry:
    """One payload value that can ground a claim."""

    path: str
    value: float
    kind: NumKind


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def scrub_identifiers(text: str) -> str:
    """``text`` with candidate ids, dates, ``[Sn]`` tags, day ordinals and emphasis markers
    replaced by spaces of the same length, so offsets still point into the original."""
    for pattern in (PMCC_ID, CANDIDATE_ID, ISO_DATE, _SOURCE_TAG, _DAY_ORDINAL, _EMPHASIS):
        text = _blank(text, pattern)
    return _CURRENCY_PREFIX.sub(lambda m: " " * (len(m.group(0)) - 1) + "$", text)


def extract_numbers(text: str, *, scrubbed: bool = False) -> list[Num]:
    """Every number claim in ``text``: digits with units (``3M``, ``5k``, ``10x``, ``40%``),
    number words up to ninety-nine, and multipliers (``double``, ``tenfold``). Ids, dates, bare
    years and day ordinals are not claims. Code spans are no longer exempt (W14)."""
    s = text if scrubbed else scrub_identifiers(text)
    out: list[Num] = []
    for m in _NUM.finditer(s):
        sign = {"−": "-"}.get(m.group("sign") or "", m.group("sign") or "")
        value = float(m.group("int").replace(",", "") + (m.group("dec") or ""))
        kind: NumKind = "plain"
        if m.group("pct"):
            kind = "pct"
        elif m.group("mult"):
            kind = "multiple"
        elif m.group("scale"):
            value *= _SCALES[m.group("scale").strip().lower()]
        bare = not (sign or m.group("cur") or m.group("dec") or m.group("pct") or m.group("mult"))
        if bare and not m.group("scale") and "," not in m.group("int") and 1990 <= value <= 2100:
            continue  # bare years are not claims
        out.append(Num(m.group(0).strip(), -value if sign == "-" else value, kind, sign,
                       m.start(), m.end()))  # fmt: skip
    for m in _WORD_NUM.finditer(s):
        bare_one = (m.group("one") or "").lower() == "one"
        if bare_one and not (m.group("pct") or m.group("scale") or m.group("mult")):
            continue  # a bare "one" ("one of", "one-stock") is not a figure
        word = (m.group("tens") or m.group("teen") or m.group("one")).lower()
        value = float(_WORD_VALUE[word] + (_WORD_VALUE[m.group("tens_one").lower()]
                                           if m.group("tens_one") else 0))  # fmt: skip
        if m.group("scale"):
            value *= _WORD_SCALE[m.group("scale").strip().lower()]
        kind = "pct" if m.group("pct") else "multiple" if m.group("mult") else "plain"
        out.append(Num(m.group(0).strip(), value, kind, "", m.start(), m.end()))
    for m in _MULT_WORD.finditer(s):
        which = next(k for k in _MULT_VALUE if m.group(k))
        out.append(Num(m.group(0), float(_MULT_VALUE[which]), "multiple", "", m.start(), m.end()))
    return sorted(out, key=lambda n: n.start)


# ------------------------------------------------------------------------ payload entries
def _identity_field(items: list[Any]) -> str | None:
    """The field that names each element of a list of dicts uniquely, if there is one."""
    if not items or not all(isinstance(x, dict) for x in items):
        return None
    for f in _IDENTITY_FIELDS:
        vals = [x.get(f) for x in items]
        if all(isinstance(v, str) and v for v in vals) and len(set(vals)) == len(vals):
            return f
    return None


def _child(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _kind_of_key(key: str) -> NumKind:
    if _MULT_KEY.search(key):
        return "multiple"
    return "pct" if _PCT_KEY.search(key) else "plain"


def payload_entries(
    payload: Any, *, skip: frozenset[str] = NOT_RUN_DATA, path: str = "", key: str = ""
) -> list[Entry]:
    """Every value in ``payload`` that can ground a claim, with its path. Lists of dicts are
    addressed by their identity field (``positions[CSP-...]``), others by index. Numbers inside
    strings (warning texts, ``"-30%"``) are parsed with the same rules as a narrative."""
    out: list[Entry] = []
    if isinstance(payload, bool) or payload is None:
        return out
    if isinstance(payload, int | float):
        v = float(payload)
        if math.isfinite(v):
            out.append(Entry(path, v, _kind_of_key(key)))
    elif isinstance(payload, str):
        for n in extract_numbers(payload):
            out.append(Entry(path, n.value, "pct" if n.kind == "pct" else n.kind))
    elif isinstance(payload, dict):
        for k, v in payload.items():
            if k in skip:
                continue  # at any depth: a tax reply nests the user's question under ``tax``
            # children of a percent-named mapping are percents ({"by_sector_pct": {"Tech": 75}})
            inherit = _kind_of_key(key) == "pct" and _kind_of_key(str(k)) == "plain"
            child_key = key if inherit else str(k)
            out += payload_entries(v, skip=skip, path=_child(path, str(k)), key=child_key)
    elif isinstance(payload, list | tuple):
        ident = _identity_field(list(payload))
        for i, v in enumerate(payload):
            label = str(v[ident]) if ident else str(i)
            out += payload_entries(v, skip=skip, path=f"{path}[{label}]", key=key)
    return out


def source_entries(payload: dict[str, Any], kinds: Iterable[str] | None = None) -> list[Entry]:
    """Numbers in the text of retrieved sources, never in third-party ``evidence`` (W13).
    ``kinds`` limits them to some source kinds (``run``: the facts this app computed)."""
    wanted = set(kinds) if kinds is not None else None
    out: list[Entry] = []
    for i, src in enumerate(payload.get("sources") or []):
        if not isinstance(src, dict) or src.get("kind") == "evidence":
            continue
        if wanted is not None and src.get("kind") not in wanted:
            continue
        for part in ("title", "text"):  # a cited excerpt is written under its document title
            for n in extract_numbers(str(src.get(part, ""))):
                out.append(Entry(f"sources[{src.get('tag', i)}].{part}", n.value, n.kind))
    return out


# --------------------------------------------------------------------------- matching
def _close(a: float, b: float, rel_tol: float) -> bool:
    return a == b or math.isclose(a, b, rel_tol=rel_tol, abs_tol=1e-9)


def display_variants(v: float) -> list[float]:
    """``v`` and its display roundings; a rounding to zero of a non-zero value is no variant."""
    out = [v]
    for k in range(0, 5):
        if k == 0 and abs(v) < 10:
            continue
        r = round(v, k)
        if r != 0 or v == 0:
            out.append(r)
    return out


def _value_matches(target: float, entry_value: float, rel_tol: float) -> bool:
    return any(_close(target, x, rel_tol) for x in display_variants(entry_value))


def matching_paths(
    tok: Num, entries: Sequence[Entry], rel_tol: float, *, loss_context: bool = False
) -> list[str]:
    """Paths of the entries ``tok`` can be read as. Signs count: ``+3140`` is not ``-3140``, and
    an unsigned figure stands for a negative value only next to a loss word ("a loss of 3,140").
    Percent is not a plain number: ``40%`` is 0.4 or a percent field of 40, never a count of 40;
    a bare ``40`` is never 0.4. A multiple (``10x``) matches only a multiple field."""
    if tok.kind == "text":
        return []
    mags = [tok.value] if tok.sign else ([tok.value, -tok.value] if loss_context else [tok.value])
    out: list[str] = []
    for e in entries:
        if tok.kind == "multiple":
            ok = e.kind == "multiple" and any(_value_matches(t, e.value, rel_tol) for t in mags)
        elif tok.kind == "pct":
            ok = (e.kind == "pct" and any(_value_matches(t, e.value, rel_tol) for t in mags)) or (
                # a fraction; under a ``_pct`` name only a small one is (csp_pct: 0.45)
                (e.kind in ("plain", "multiple") or (e.kind == "pct" and abs(e.value) <= 1.5))
                and any(
                    _close(t / 100.0, e.value, rel_tol)
                    or any(_close(t, x, rel_tol) for x in display_variants(e.value * 100)[1:])
                    for t in mags
                )
            )
        else:
            ok = e.kind != "multiple" and any(_value_matches(t, e.value, rel_tol) for t in mags)
        if ok:
            out.append(e.path)
    return out


# ------------------------------------------------------------------------ sentence helpers
def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        spans.append((start, m.end()))
        start = m.end()
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def _sentence_of(text: str, pos: int) -> tuple[int, int]:
    return next(((a, b) for a, b in _sentence_spans(text) if a <= pos < b), (0, len(text)))


def _clause_bounds(text: str, lo: int, hi: int, pos: int) -> tuple[int, int]:
    """The clause of ``text[lo:hi]`` that holds ``pos`` (commas, semicolons, brackets...)."""
    a, b = lo, hi
    for m in _CLAUSE_BREAK.finditer(text, lo, hi):
        if m.end() <= pos:
            a = m.end()
        elif m.start() >= pos:
            b = m.start()
            break
    return a, b


def loss_context(text: str, tok: Num, lo: int, hi: int) -> bool:
    """A loss word near the number, inside its sentence (60 characters before, 30 after)."""
    window = text[max(lo, tok.start - 60) : tok.start] + " " + text[tok.end : min(hi, tok.end + 30)]
    return bool(LOSS_WORDS.search(window))


def gain_context(text: str, tok: Num, lo: int, hi: int) -> bool:
    window = text[max(lo, tok.start - 40) : tok.start]
    return bool(GAIN_WORDS.search(window)) and not LOSS_WORDS.search(window)


# ---------------------------------------------------------------------------- slots
class SlotError(ValueError):
    """A slot names a path the payload does not have (or a field no claim may use)."""


@dataclass(frozen=True)
class SlotFill:
    path: str  # canonical path, lists addressed by identity
    value: Any
    rendered: str
    start: int  # span of the slot in the template
    end: int
    filters: tuple[str, ...] = ()


_SEGMENT = re.compile(r"\.?([A-Za-z_][\w]*)|\[([^\]]+)\]")
_FILTERS = frozenset({"money", "pct", "percent", "abs", "count", "list"})


def _parse_path(path: str) -> list[str | tuple[str]]:
    """``a.b[0][CSP-X].c`` -> ``["a", "b", ("0",), ("CSP-X",), "c"]`` (a tuple is a list key)."""
    out: list[str | tuple[str]] = []
    pos = 0
    path = path.strip()
    while pos < len(path):
        m = _SEGMENT.match(path, pos)
        if not m or m.end() == pos:
            raise SlotError(f"cannot parse slot path {path!r}")
        out.append(m.group(1) if m.group(1) is not None else (m.group(2).strip(),))
        pos = m.end()
    return out


def _shock_key(key: str) -> float | None:
    """``-30%``, ``-0.30`` and ``-30`` all name the -30% stress row."""
    t = key.replace("−", "-").strip()
    try:
        if t.endswith("%"):
            return float(t[:-1])
        v = float(t)
    except ValueError:
        return None
    return v * 100 if abs(v) <= 1.5 and "." in t else v


def _select(items: list[Any], key: str, path: str) -> tuple[Any, str]:
    ident = _identity_field(items)
    if re.fullmatch(r"-?\d+", key):
        i = int(key)
        if not -len(items) <= i < len(items):
            raise SlotError(f"{path}[{key}] is out of range ({len(items)} item(s))")
        v = items[i]
        return v, str(v[ident]) if ident else str(i % len(items))
    for i, v in enumerate(items):
        if isinstance(v, dict) and any(str(v.get(f)) == key for f in _IDENTITY_FIELDS):
            return v, str(v[ident]) if ident else str(i)
    want = _shock_key(key)
    if want is not None:
        for i, v in enumerate(items):
            got = _shock_key(str(v.get("shock"))) if isinstance(v, dict) else None
            if got is not None and _close(got, want, 1e-9):
                return v, str(v[ident]) if ident else str(i)
    raise SlotError(f"{path} has no item {key!r}")


def resolve_slot(payload: dict[str, Any], path: str) -> tuple[Any, str]:
    """The value at ``path`` and its canonical path; raises ``SlotError`` on an unknown path or
    on retrieved text and the user's question, which may not supply a figure."""
    segments = _parse_path(path)
    if not segments or not isinstance(segments[0], str):
        raise SlotError(f"slot {path!r} must start with a payload field")
    if segments[0] in NOT_RUN_DATA:
        raise SlotError(f"slot {path!r} reads {segments[0]!r}, which is not run data")
    cur: Any = payload
    canon = ""
    for seg in segments:
        if isinstance(seg, str):
            if not isinstance(cur, dict) or seg not in cur:
                raise SlotError(
                    f"unknown slot {{{{{path}}}}}: no field {seg!r} at {canon or 'top'}"
                )
            cur, canon = cur[seg], _child(canon, seg)
        else:
            if not isinstance(cur, list):
                raise SlotError(f"unknown slot {{{{{path}}}}}: {canon} is not a list")
            cur, label = _select(cur, seg[0], canon)
            canon = f"{canon}[{label}]"
    return cur, canon


def _fmt_number(v: float, *, money: bool) -> str:
    """``12337`` -> ``12,337`` (money ``$12,337``); ``735.0`` -> ``735``; ``4.1`` (``$4.10``)."""
    a = abs(v)
    if float(a).is_integer():
        body = f"{int(a):,}"
    else:
        body = f"{a:,.2f}" if money else f"{a:,}"
    return ("-" if v < 0 else "") + ("$" if money else "") + body


def format_value(value: Any, filters: Sequence[str]) -> str:
    """Display form of a slot value. Filters: ``money`` ($ and thousands separators), ``pct``
    (append %), ``percent`` (a fraction shown as a percent), ``abs`` (magnitude; a loss word
    must stand next to it), ``count`` (number of items in a list), ``list`` (a list of text
    items, such as flags, joined with commas; "none" when empty)."""
    unknown = [f for f in filters if f not in _FILTERS]
    if unknown:
        raise SlotError(
            f"unknown slot filter(s): {', '.join(unknown)} (allowed: {', '.join(sorted(_FILTERS))})"
        )
    if "list" in filters:
        if len(filters) > 1:
            raise SlotError("the list filter cannot be combined with another filter")
        if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
            raise SlotError(
                "the list filter joins a list of text items, not records or numbers (for names "
                "use a list of names such as quality_screen.passed_tickers; for a number name "
                "one item's field)"
            )
        return ", ".join(value) if value else "none"
    if "count" in filters:
        if not isinstance(value, list | tuple | dict):
            raise SlotError(
                "the count filter needs a list (a stored count such as passed_count is slotted "
                "without it)"
            )
        value = len(value)
    if isinstance(value, list | tuple | dict):
        raise SlotError(
            "a slot must name a single value, not a list or an object (use the count filter for "
            "how many items a list has, the list filter to name a list of text items such as "
            "flags, or name one item's field)"
        )
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        if set(filters) - {"abs"}:
            raise SlotError("number filters cannot format a text value")
        return value.lstrip("-−") if "abs" in filters else value
    v: float = value
    if "abs" in filters:
        v = abs(v)
    if "percent" in filters:
        v = round(v * 100, 2)
        v = int(v) if float(v).is_integer() else v
        return _fmt_number(v, money=False) + "%"
    out = _fmt_number(v, money="money" in filters)
    return out + "%" if "pct" in filters else out


_UNIT_FILTERS = frozenset({"pct", "percent", "money", "count", "list"})


def _implied_pct(canon: str, value: Any, filters: tuple[str, ...], after: str) -> tuple[str, ...]:
    """A field named ``*_pct`` already holds a percent: it is shown and checked as one even when
    the writer leaves out ``|pct`` (or types the ``%`` after the slot itself)."""
    numeric = isinstance(value, int | float) and not isinstance(value, bool)
    name = re.search(r"([A-Za-z_]\w*)$", canon)
    if (
        numeric
        and name is not None
        and name.group(1).endswith("_pct")
        and not _UNIT_FILTERS & set(filters)
        and not after.lstrip().startswith("%")
    ):
        return (*filters, "pct")
    return filters


def render_slots(text: str, payload: dict[str, Any]) -> str:
    """``text`` with every ``{{path|filters}}`` slot filled from ``payload``. Raises
    ``SlotError`` on an unknown path, a filter that does not apply, or a path into retrieved
    text or the user's question."""
    rendered, _, errors = render_template(text, payload)
    if errors:
        raise SlotError("; ".join(errors))
    return rendered


def render_template(text: str, payload: dict[str, Any]) -> tuple[str, list[SlotFill], list[str]]:
    """Lenient ``render_slots``: unknown slots stay as written and are reported as errors."""
    fills: list[SlotFill] = []
    errors: list[str] = []
    parts: list[str] = []
    last = 0
    for m in SLOT.finditer(text):
        filters = tuple(f.strip() for f in (m.group(2) or "").split("|") if f.strip())
        try:
            value, canon = resolve_slot(payload, m.group(1))
            filters = _implied_pct(canon, value, filters, text[m.end() : m.end() + 2])
            rendered = format_value(value, filters)
        except SlotError as exc:
            errors.append(f"{m.group(0)}: {exc}")
            continue
        parts.append(text[last : m.start()])
        parts.append(rendered)
        last = m.end()
        fills.append(SlotFill(canon, value, rendered, m.start(), m.end(), filters))
    parts.append(text[last:])
    return "".join(parts), fills, errors


def render_narrative(narrative: Narrative, payload: dict[str, Any]) -> Narrative:
    """Fill the slots of every paragraph and keep the written text as its ``template``, so the
    Compliance agent can tell slot-filled figures from typed ones. Idempotent: a paragraph that
    already carries a template is rendered from it again. Unknown slots stay visible in the text
    and fail ``check_numbers``."""
    from options_scout.core.models import Narrative as _Narrative

    paragraphs = []
    for p in narrative.paragraphs:
        template = p.template if p.template is not None else p.text
        text, _, _ = render_template(template, payload)
        paragraphs.append(p.model_copy(update={"text": text, "template": template}))
    return _Narrative(paragraphs=paragraphs)


def _fill_token(fill: SlotFill, template: str = "") -> Num:
    """A slot fill as a number claim: kind and sign from the value and its filters; a slot
    followed by a typed ``%`` (``{{risk.realistic_loss_drop_pct}}%``) is a percent."""
    value = fill.value
    if "count" in fill.filters and isinstance(value, list | tuple | dict):
        value = len(value)
    if isinstance(value, bool) or value is None or "list" in fill.filters:
        return Num(fill.rendered, 0.0, "text", "", fill.start, fill.end, fill.path)
    if isinstance(value, str):
        nums = extract_numbers(value)
        if len(nums) == 1 and value.strip() == nums[0].text:
            n = nums[0]
            return Num(fill.rendered, n.value, n.kind, n.sign, fill.start, fill.end, fill.path)
        return Num(fill.rendered, 0.0, "text", "", fill.start, fill.end, fill.path)
    v = float(value)
    pct_after = template[fill.end : fill.end + 2].lstrip().startswith("%")
    kind: NumKind = "pct" if ({"pct", "percent"} & set(fill.filters) or pct_after) else "plain"
    return Num(fill.rendered, v, kind, "-" if v < 0 else "", fill.start, fill.end, fill.path)


# ------------------------------------------------------------------------- label checks
def _glob(pattern: str) -> re.Pattern[str]:
    return re.compile("^" + ".*".join(re.escape(p) for p in pattern.split("*")) + "$")


@dataclass
class _Label:
    spec: GroundingLabel
    regex: re.Pattern[str]
    globs: list[re.Pattern[str]] = field(default_factory=list)

    def fields(self, entries: Sequence[Entry], cids: Sequence[str]) -> list[Entry]:
        mine = [e for e in entries if any(g.match(e.path) for g in self.globs)]
        if cids:
            scoped = [e for e in mine if any(f"[{c}]" in e.path for c in cids)]
            return scoped or mine
        return mine


def compile_labels(cfg: GroundingConfig | None) -> list[_Label]:
    if cfg is None:
        return []
    return [
        _Label(lb, re.compile(lb.pattern, re.IGNORECASE), [_glob(f) for f in lb.fields])
        for lb in cfg.labels
    ]


def _eligible(tok: Num, fields: Sequence[Entry]) -> bool:
    """Could ``tok`` be a value of one of these fields at all (a percent next to a dollar label
    is a different figure: "the realistic loss at a -30% move is $197,416")."""
    if tok.kind == "text":
        return False
    if not fields:
        return True  # nothing to compare with: any figure is the label's (require_field)
    if tok.kind == "pct":  # a percent field, or a true fraction (0 and 1 are dollar amounts too)
        return any(
            e.kind == "pct" or (0 < abs(e.value) <= 1.5 and not float(e.value).is_integer())
            for e in fields
        )
    if tok.kind == "multiple":
        return any(e.kind == "multiple" for e in fields)
    return bool(fields)


_SCENARIO_BEFORE = re.compile(
    r"\b(?:at|after|if|when|under|falls?|drops?|declines?|moves?|shocks?)\b", re.IGNORECASE
)
_SCENARIO_AFTER = re.compile(r"\s*(?:drop|fall|decline|move|shock|crash|downturn)", re.IGNORECASE)


def _percent_stated_as(
    text: str, start: int, end: int, tokens: Sequence[Num], fields: Sequence[Entry]
) -> Num | None:
    """A percent given AS a dollar label's value ("the realistic loss is 45%"), when no figure
    of the label's kind follows it in the clause. A percent that sets the scenario ("at a 30%
    drop", "if the stock falls 30%") is not one."""
    if not fields or any(e.kind == "pct" for e in fields):
        return None
    after = [t for t in tokens if start <= t.start < end and t.kind == "pct"]
    if not after:
        return None
    tok = after[0]
    if _SCENARIO_BEFORE.search(text, start, tok.start) or _SCENARIO_AFTER.match(text, tok.end):
        return None
    return tok


def label_problems(
    text: str,
    tokens: Sequence[Num],
    entries: Sequence[Entry],
    labels: Sequence[_Label],
    rel_tol: float,
    *,
    by_path: bool,
    ids_text: str | None = None,
) -> list[str]:
    """For each dangerous label in a sentence, the nearest figure in its clause (after it, else
    before it) must be that label's field, of the candidate the sentence names if it names one.
    ``by_path``: the figure's provenance is its slot path (slot mode), not a value match."""
    problems: list[str] = []
    for lo, hi in _sentence_spans(text):
        sentence = (ids_text if ids_text is not None else text)[lo:hi]  # ids survive scrubbing
        cids = CANDIDATE_ID.findall(sentence) + PMCC_ID.findall(sentence)
        in_sentence = [t for t in tokens if lo <= t.start < hi]
        taken: list[tuple[int, int]] = []
        for lab in labels:
            for m in lab.regex.finditer(text, lo, hi):
                if any(a < m.end() and m.start() < b for a, b in taken):
                    continue  # a more specific label already covers this phrase
                taken.append((m.start(), m.end()))
                fields = lab.fields(entries, cids)
                paths = {e.path for e in fields}
                a, b = _clause_bounds(text, lo, hi, m.start())
                # a slot of one of the label's own fields is always its figure (a margin usage of
                # 0 is a fraction that looks like a plain zero)
                near = [
                    t for t in in_sentence if (by_path and t.path in paths) or _eligible(t, fields)
                ]
                after = [t for t in near if m.end() <= t.start < b]
                before = [t for t in near if a <= t.start < m.start()]
                tok = after[0] if after else (before[-1] if before else None)
                if tok is None:
                    stand_in = _percent_stated_as(
                        text, m.end(), b, [t for t in in_sentence if t.path not in paths], fields
                    )
                    if stand_in is not None:
                        got = f" (slot {stand_in.path})" if by_path and stand_in.path else ""
                        problems.append(
                            f"{stand_in.text}{got} is a percent, not the {lab.spec.label} "
                            f"(fields: {', '.join(lab.spec.fields)})"
                        )
                    continue
                if not fields:
                    if lab.spec.require_field:
                        problems.append(
                            f"{tok.text} is called {lab.spec.label} but this run computes no "
                            f"{lab.spec.label}"
                        )
                    continue
                if by_path:
                    ok = tok.path in paths
                else:
                    ok = bool(
                        set(
                            matching_paths(
                                tok, fields, rel_tol, loss_context=loss_context(text, tok, lo, hi)
                            )
                        )
                        & paths
                    )
                if not ok:
                    whose = f" of {', '.join(dict.fromkeys(cids))}" if cids else ""
                    got = f" (slot {tok.path})" if by_path and tok.path else ""
                    problems.append(
                        f"{tok.text}{got} is not the {lab.spec.label}{whose} "
                        f"(fields: {', '.join(lab.spec.fields)})"
                    )
    return problems


# --------------------------------------------------------------------- paragraph checks
@dataclass
class GroundingResult:
    """What ``ground_narrative`` found: the figures it checked and what failed, in order."""

    numbers_checked: int = 0
    problems: list[str] = field(default_factory=list)


_QUOTE = re.compile(r"“([^”]+)”|\"([^\"]+)\"")


def _payload_texts(payload: Any, skip: frozenset[str] = NOT_RUN_DATA) -> list[str]:
    """Every text value of the run's own data (never sources or the question)."""
    if isinstance(payload, str):
        return [" ".join(payload.split())]
    if isinstance(payload, dict):
        return [t for k, v in payload.items() if k not in skip for t in _payload_texts(v, skip)]
    if isinstance(payload, list | tuple):
        return [t for v in payload for t in _payload_texts(v, skip)]
    return []


def _blank_payload_quotes(text: str, payload: dict[str, Any]) -> str:
    """``text`` with each quotation copied verbatim (12 characters or more) from a payload text
    blanked to spaces of the same length."""
    texts = _payload_texts(payload)

    def blank(m: re.Match[str]) -> str:
        quoted = " ".join((m.group(1) or m.group(2) or "").split()).rstrip("….").strip()
        if len(quoted) >= 12 and any(quoted in t for t in texts):
            return " " * len(m.group(0))
        return m.group(0)

    return _QUOTE.sub(blank, text)


def _without_quotes(text: str, payload: dict[str, Any]) -> str:
    from options_scout.core.compliance import _without_verbatim_quotes

    return _without_verbatim_quotes(text, payload)


def _slot_paragraph(
    i: int,
    p: Paragraph,
    payload: dict[str, Any],
    run: Sequence[Entry],
    labels: Sequence[_Label],
    literal_allow: Sequence[re.Pattern[str]],
    rel_tol: float,
    out: GroundingResult,
) -> None:
    where = f"paragraph {i + 1}"
    template = p.template or ""
    rendered, fills, errors = render_template(template, payload)
    out.problems += [f"{where}: {e}" for e in errors]
    if rendered != p.text:
        out.problems.append(f"{where}: the text differs from its rendered template")
    if p.mode == "education":
        if fills or errors:
            out.problems.append(f"{where}: slot in an education paragraph (run figures belong in "
                                "screen_result)")  # fmt: skip
        body = _without_quotes(template, payload)
        allowed = source_entries(payload) + list(run)
        for tok in extract_numbers(body):
            out.numbers_checked += 1
            loss = loss_context(body, tok, 0, len(body))
            if not matching_paths(tok, allowed, rel_tol, loss_context=loss):
                out.problems.append(f"{where}: {tok.text} is in no cited source")
        return
    # screen_result / notice: every figure must come from a slot, or sit inside a verbatim quote
    # of a payload text (a warning, a quality-screen description), which states what it says
    masked = _blank_payload_quotes(SLOT.sub(lambda m: " " * len(m.group(0)), template), payload)
    for pattern in literal_allow:
        masked = _blank(masked, pattern)
    for tok in extract_numbers(masked):
        out.numbers_checked += 1
        near = " ".join(template[max(0, tok.start - 40) : tok.end + 25].split())
        out.problems.append(
            f'{where}: {tok.text!r} is typed, not a slot, in "…{near}…" (name the payload field '
            "in double braces; counts too, e.g. passed_count or a list with the count filter)"
        )
    tokens = [_fill_token(f, template) for f in fills]
    out.numbers_checked += sum(1 for t in tokens if t.kind != "text")
    # sign: a negative figure is not a gain, and a magnitude of a negative needs a loss word
    for t, f in zip(tokens, fills, strict=True):
        if t.kind == "text" or not isinstance(f.value, int | float) or isinstance(f.value, bool):
            continue
        lo, hi = _sentence_of(masked, t.start)
        if f.value < 0 and gain_context(masked, t, lo, hi):
            out.problems.append(f"{where}: {{{{{f.path}}}}} is negative ({f.value}) but is "
                                "described as a gain")  # fmt: skip
        elif f.value < 0 and "abs" in f.filters and not loss_context(masked, t, lo, hi):
            out.problems.append(f"{where}: {{{{{f.path}|abs}}}} drops the sign of a negative "
                                "value; say loss next to it")  # fmt: skip
    entries = payload_entries(payload)
    out.problems += [
        f"{where}: {msg}"
        for msg in label_problems(masked, tokens, entries, labels, rel_tol, by_path=True)
    ]


def _free_paragraph(
    i: int,
    p: Paragraph,
    payload: dict[str, Any],
    run: Sequence[Entry],
    labels: Sequence[_Label],
    rel_tol: float,
    out: GroundingResult,
) -> None:
    where = f"paragraph {i + 1}"
    unscrubbed = _without_quotes(p.text, payload)
    body = scrub_identifiers(unscrubbed)
    if p.mode == "education":
        allowed = list(run) + source_entries(payload)
    else:  # W14 step 4: the run's own data, and the facts this app computed (kind "run") only
        allowed = list(run) + source_entries(payload, kinds=("run",))
    tokens = extract_numbers(body, scrubbed=True)
    for lo, hi in _sentence_spans(body):
        for tok in (t for t in tokens if lo <= t.start < hi):
            out.numbers_checked += 1
            if gain_context(body, tok, lo, hi) and not tok.sign:
                loss = False
            else:
                loss = loss_context(body, tok, lo, hi)
            if not matching_paths(tok, allowed, rel_tol, loss_context=loss):
                out.problems.append(tok.text)
    if p.mode != "education":
        out.problems += [
            f"{where}: {msg}"
            for msg in label_problems(
                body, tokens, allowed, labels, rel_tol, by_path=False, ids_text=unscrubbed
            )
        ]


def run_candidate_ids(payload: dict[str, Any]) -> set[str]:
    """Every candidate id the run's own data names: anywhere in the payload except retrieved
    text, the question and retry feedback, plus the facts this app computed (sources of kind
    ``run``, which chat replies quote)."""
    texts = _payload_texts(payload)
    texts += [
        str(src.get("text", ""))
        for src in payload.get("sources") or []
        if isinstance(src, dict) and src.get("kind") == "run"
    ]
    out: set[str] = set()
    for t in texts:
        out.update(CANDIDATE_ID.findall(t))
        out.update(PMCC_ID.findall(t))
    return out


def unknown_candidate_ids(p: Paragraph, known: set[str]) -> list[str]:
    """Candidate ids a paragraph names that the run never produced: an invented contract (the
    model once wrote CSP-CSCO-2026-11-20-35P, copying another put's date and strike, for a
    ticker that was never screened)."""
    named = CANDIDATE_ID.findall(p.text) + PMCC_ID.findall(p.text)
    return [cid for cid in dict.fromkeys(named) if cid not in known]


def ground_narrative(
    narrative: Narrative,
    payload: dict[str, Any],
    *,
    cfg: GroundingConfig | None = None,
    rel_tol: float = 0.01,
) -> GroundingResult:
    """Check every figure in ``narrative`` (W14). A paragraph with a ``template`` is checked in
    slot mode, any other in free-text mode."""
    labels = compile_labels(cfg)
    literal_allow = [re.compile(p, re.IGNORECASE) for p in (cfg.literal_allow if cfg else [])]
    run = payload_entries(payload)
    known = run_candidate_ids(payload)
    out = GroundingResult()
    for i, p in enumerate(narrative.paragraphs):
        if p.mode != "education":  # education paragraphs may not name an id at all (check 3)
            out.problems += [
                f"paragraph {i + 1}: {cid} is not a candidate in this run's data (name only ids "
                "the payload lists)"
                for cid in unknown_candidate_ids(p, known)
            ]
        if p.template is not None:
            _slot_paragraph(i, p, payload, run, labels, literal_allow, rel_tol, out)
        else:
            _free_paragraph(i, p, payload, run, labels, rel_tol, out)
    return out


# ------------------------------------------------------------------ realistic loss per option
SHORT_OPTION_ID = re.compile(r"\b(?:CSP|PMCCSC)-[A-Z.\-]+?-\d{4}-\d{2}-\d{2}-[\d.]+[CP]\b")


@dataclass(frozen=True)
class LossRef:
    """Where a short option's realistic loss lives: the slot that states it, its value, and
    whether it is one contract of a candidate that was not sized."""

    path: str
    value: float | None
    per_contract: bool = False


def short_option_losses(payload: dict[str, Any]) -> dict[str, LossRef]:
    """Every short option id the payload can name, mapped to its realistic loss: a sized CSP or
    PMCC to ``positions[ID].realistic_loss``; a PMCC short call (``PMCCSC-``) to its pair's
    position, whose loss covers the pair; a skipped candidate to the loss of one contract."""
    out: dict[str, LossRef] = {}
    for pos in payload.get("positions", []):
        if not isinstance(pos, dict):
            continue
        cid = str(pos.get("candidate_id"))
        ref = LossRef(f"positions[{cid}].realistic_loss", _num(pos.get("realistic_loss")))
        out[cid] = ref
        if pos.get("pmcc_short_call_id"):
            out.setdefault(str(pos["pmcc_short_call_id"]), ref)
    for sk in payload.get("skipped_candidates", []):
        if isinstance(sk, dict):
            cid = str(sk.get("candidate_id"))
            path = f"skipped_candidates[{cid}].realistic_loss_per_contract"
            out.setdefault(cid, LossRef(path, _num(sk.get("realistic_loss_per_contract")), True))
    # chat replies: the run facts this app computed (source kind "run") state each ranked put's
    # loss per contract and each position's loss, one line per candidate. These are not slots
    # (sources never are), so only a typed figure matching them states the loss.
    for src in payload.get("sources", []):
        if not isinstance(src, dict) or src.get("kind") != "run":
            continue
        for line in str(src.get("text", "")).splitlines():
            m = _RUN_FACT_LOSS.match(line)
            if m:
                value = float(m.group("loss").replace(",", ""))
                out.setdefault(m.group("id"), LossRef("", value, "per contract" in line))
    return out


_RUN_FACT_LOSS = re.compile(
    r"(?:Rank \d+|Position): ?(?P<id>(?:CSP|PMCCSC)-[A-Z.\-]+?-\d{4}-\d{2}-\d{2}-[\d.]+[CP])\b"
    r".*?realistic loss (?P<loss>[\d,]+(?:\.\d+)?)"
)


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def unstated_losses(
    p: Paragraph,
    payload: dict[str, Any],
    *,
    rel_tol: float = 0.01,
    losses: dict[str, LossRef] | None = None,
) -> list[str]:
    """The short options a ``screen_result`` paragraph names without their own realistic loss,
    in order. A templated paragraph must slot that option's loss field; free text must carry a
    figure matching it. The words "realistic loss" alone state nobody's figure."""
    if p.mode != "screen_result":
        return []
    refs = short_option_losses(payload) if losses is None else losses
    text = p.text
    slotted: set[str] | None = None
    figures: list[float] = []
    if p.template is not None:
        slotted = {f.path for f in render_template(p.template, payload)[1]}
    else:
        figures = [abs(t.value) for t in extract_numbers(text) if t.kind != "pct"]

    def stated(ref: LossRef) -> bool:
        if slotted is not None:
            return ref.path in slotted
        return ref.value is not None and any(_close(f, abs(ref.value), rel_tol) for f in figures)

    return [
        cid
        for cid in dict.fromkeys(SHORT_OPTION_ID.findall(text))
        if cid not in refs or not stated(refs[cid])
    ]


def add_missing_realistic_losses(
    narrative: Narrative, payload: dict[str, Any]
) -> tuple[Narrative, list[str]]:
    """Each short option a ``screen_result`` paragraph names without its own realistic loss gets
    the sentence added, as a slot of that loss (``unstated_losses`` decides, as the compliance
    check does). The figure still comes from the payload, so the repair adds no unchecked number.
    An option the payload has no loss for is left for the check to fail. Returns the narrative
    and one note per paragraph changed."""
    from options_scout.core.models import Narrative as _Narrative

    refs = short_option_losses(payload)
    notes: list[str] = []
    paragraphs = []
    for i, p in enumerate(narrative.paragraphs):
        template = p.template if p.template is not None else p.text
        # the writer's text is a template until rendered: check it as one
        probe = p.model_copy(
            update={"template": template, "text": render_template(template, payload)[0]}
        )
        added = []
        for cid in unstated_losses(probe, payload, losses=refs):
            ref = refs.get(cid)
            if ref is None or ref.value is None:
                continue
            if ref.per_contract:
                added.append(f"Realistic loss of one {cid} contract: {{{{{ref.path}|money}}}}.")
            elif cid.startswith("PMCCSC-"):
                added.append(
                    f"Realistic loss of the pair {cid} belongs to: {{{{{ref.path}|money}}}}."
                )
            else:
                added.append(f"Realistic loss of {cid}: {{{{{ref.path}|money}}}}.")
        if not added:
            paragraphs.append(p)
            continue
        new = template.rstrip() + " " + " ".join(added)
        update: dict[str, Any] = {"template": new} if p.template is not None else {"text": new}
        paragraphs.append(p.model_copy(update=update))
        notes.append(f"paragraph {i + 1}: realistic loss added ({len(added)} option(s))")
    return _Narrative(paragraphs=paragraphs), notes
