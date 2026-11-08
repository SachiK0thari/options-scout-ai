"""Snippet classification (PRD 4A.6): the only LLM step of the bottleneck engine.

Each ≤ 400-character snippet gets one :class:`ConstraintLabel` (layer, side, direction, kind).
Three paths produce labels, in this order of preference per snippet:

1. **Fixture ground truth.** The fixture corpus carries designed labels; offline (any non-live LLM
   mode) they are replayed, exactly as the social engine replays its extraction labels.
2. **Cache.** Labels are cached in the app's SQLite cache keyed by snippet content hash and prompt
   version, so a re-run never re-classifies a filing it has seen.
3. **The provider.** Batches of ``llm.extraction_batch_size`` snippets go through
   ``prompts/classify_bottleneck.md`` with structured output. In ``none`` mode (``--no-llm``) the
   rule-based stand-in below answers instead; it is also what the offline eval measures.

Whatever the path, every label is checked: the layer must exist in the theme map (else ``None``),
every ticker must be in the SEC list (else dropped and counted), and the label's ``snippet_id``
must be one of the batch. Snippets are data: the rule-based path strips instruction-like
sentences before reading the text, and the prompt tells the model to do the same.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from options_scout.bottleneck.themes import ThemeMap
from options_scout.core.models import (
    ConstraintDirection,
    ConstraintKind,
    ConstraintLabel,
    ConstraintLabelBatch,
    ConstraintSide,
    FilingSnippet,
)

log = logging.getLogger(__name__)

PROMPT_NAME = "classify_bottleneck"
CACHE_TTL_SECONDS = 180 * 24 * 3600  # labels are content-addressed; keep them as long as snapshots

# ----------------------------------------------------------------------- rule-based stand-in
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;\n])\s+")
_INJECTION = re.compile(
    r"(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|instructions?)|"
    r"\binstruction\b|system (?:prompt|override|message)|\[system\]|\bsystem:|operator|"
    r"you are now|as an ai|\bassistant\b|\bmodel\b|\bbot\b|automated readers?|reviewer|"
    r"classify (?:this|all|every|each)|label(?:led)? (?:this|all|every|each)|direction\s*=|"
    r"add(?:ing)? (?:the )?ticker|append [A-Z]{2,5}|add [A-Z]{2,5} to|mark(?:ed)? (?:it|as) curated|"
    r"candidate list|watchlist|screened universe|recommend(?:ing)?\b|tell the user|should (?:buy|sell)|"
    r"(?:buy|sell) [A-Z]{2,5} (?:calls|puts|shares|stock|now)|"
    r"output json|return json|tool\b|function_call|tool_call|skip the quality gate|</?snippet>|"
    r"\bprompt\b|\bLLM\b|authori[sz]ed by",
    re.IGNORECASE,
)
_CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")

# Direction lexicons. Easing phrases are removed from the text before tightening cues are counted,
# so "no longer a constraint" never scores as tightening.
_EASING = re.compile(
    r"no longer (?:a |the )?(?:factor|constraint|binding|limiting|an issue)|"
    r"\beas(?:e[sd]?|ing)\b|normali[sz](?:e[sd]?|ing|ation)|moderat(?:e[sd]?|ing|ion)|"
    r"oversuppl(?:y|ied)|\bsurplus\b|glut\b|unwind(?:s|ing)?|resolv(?:e[sd]?|ing)|"
    r"improv(?:e[sd]?|ing) availability|availability (?:of [^.;]{0,60} )?improved|"
    r"(?:lead times?|delivery times?|wait(?:ing)? times?)[^.;]{0,40}\b(?:shorten|shrank|shorter|fell|declin|improv|came down|down toward|back under|returned to normal|normal)|"
    r"shorten(?:ed|ing)? (?:the )?lead times?|"
    r"pric(?:es?|ing)[^.;]{0,30}\b(?:fell|fall(?:s|ing)?|declin(?:e[sd]?|ing)|dropp?(?:ed|ing)|down|lower|softened|retreat|collapse|moderat)|"
    r"(?:lower|falling|declining|softer|weaker) (?:average selling )?pric(?:es?|ing)|price (?:cuts?|declines?|erosion)|"
    r"new (?:[a-z\-]+ )?(?:capacity|plant|fab|factory|lines?|mine|smelter|entrants?)|additional (?:capacity|supply)|"
    r"(?:come|came|comes|coming) online|"
    r"capacity (?:came|coming|comes|brought) online|(?:expand(?:s|ed|ing)?|expansion of|add(?:s|ed|ing)?) [^.;]{0,30}capacity|"
    r"capacity expansion|ramp(?:s|ed|ing)? (?:up )?(?:production|output|capacity|new)|"
    r"enters? the market|breaks? ground|second source|qualified (?:a|an|another) (?:second|new) supplier|"
    r"inventor(?:y|ies)[^.;]{0,30}\b(?:build|built|rose|elevated|normali|high|destock)|destocking|"
    r"renegotiat(?:e[sd]?|ing)[^.;]{0,20}\blower|orders? (?:declined|fell|slowed|softened|weakened)|"
    r"\bdeferred\b|sufficient (?:capacity|supply)|backlog[^.;]{0,20}\b(?:cleared|shrank|declined|fell|normali)|"
    r"did not materiali[sz]e|lowered (?:our )?[^.;]{0,15}costs|\bloosened\b|\brelief\b|\bample\b|caught up|"
    r"(?:demand|orders?) (?:has |have )?(?:slowed|softened|weakened|cooled|moderated)|"
    r"(?:available|in stock|back in stock|readily available)|"
    r"catch(?:ing|es)? up (?:with|to) demand|supply (?:caught|catching|catches) up|"
    r"(?:flat|unchanged) pricing|pricing to (?:moderate|soften|flatten)",
    re.IGNORECASE,
)
_TIGHTENING = re.compile(
    r"(?:lead|delivery|wait(?:ing)?) times?[^.;]{0,50}\b(?:extend|lengthen|stretch|rose|increas|grew|longer|doubled|now \d+|to \d+ weeks|\d+ weeks)|"
    r"(?:extended|longer|lengthening|stretched) (?:lead|delivery) times?|"
    r"sold out|\ballocat(?:ion|ed|ing)\b|\bshortages?\b|\bscarcit|\bconstrain(?:ed|t|ts|ing)\b|"
    r"\bbottleneck|unable to (?:fulfil|fulfill|meet|supply|deliver)|exceed(?:s|ed|ing)? (?:our|its|their)? ?(?:ability|capacity)|"
    r"demand (?:exceed|outstrip|outrun|outpac)|outrunning|outstripp?(?:ed|ing)|"
    r"backlog (?:grew|growth|rose|increased|expanded|extends?|record)|record backlog|"
    r"pricing power|price increases?|(?:higher|rising|increased) (?:average selling )?pric(?:es?|ing)|"
    r"pric(?:es?|ing)[^.;]{0,45}\b(?:rose|rise|rising|increas|climb|up\b|higher|surg|jump|double-digit|rebound|well above)|"
    r"raised (?:our )?pric(?:es|ing)|backlog[^.;]{0,30}\b(?:stretch|extends?|pushed|into 20\d\d|record|full)|"
    r"pushed [^.;]{0,40}\bout by|\boutran\b|\boutpac(?:ed|ing)\b|turning away [^.;]{0,20}orders|fully (?:booked|committed)|"
    r"reserved (?:manufacturing )?slots|\bprepaid\b|full utili[sz]ation|every tonne|scarce|gating item|"
    r"deepens|widened|\bcrunch\b|squeeze|scramble|flood(?:ed|ing)? [^.;]{0,20}suppliers|absorbed available supply|"
    r"mid-teens price|double-digit price|\btight(?:er|ness|ened|ening)?\b|"
    r"full capacity|capacity (?:is )?(?:full|constrained|sold)|at capacity|"
    r"take-or-pay|secure (?:supply|capacity|volume)|lock(?:ed|ing)? in (?:supply|capacity)|"
    r"multi-?year (?:supply )?agreements? to secure|"
    r"slipped|delays? (?:in|to) (?:delivery|deliveries|shipments?)|limiting factor|binding constraint|"
    r"few alternatives|rationing|waitlists?|on allocation|supply (?:remains? |is |was )?(?:tight|short|scarce|limited|constrained)|"
    r"persist(?:s|ed|ing)? through|extends? into 20\d\d",
    re.IGNORECASE,
)
_KIND_PATTERNS: tuple[tuple[ConstraintKind, re.Pattern[str]], ...] = (
    (
        "lead_time",
        re.compile(
            r"lead times?|delivery (?:times?|schedules?)|wait(?:ing)? times?|\d+ weeks|slipped|delays?",
            re.I,
        ),
    ),
    (
        "deal",
        re.compile(
            r"supply (?:deal|agreement|contract)|signs?|signed|agreements? (?:to|with)|take-or-pay|contract(?:s|ed)? (?:with|for)|acqui(?:re|sition)|merger|offtake",
            re.I,
        ),
    ),
    (
        "price",
        re.compile(r"\bpric(?:e|es|ing)\b|\bcosts?\b|selling prices?|premium|quotes?|paid", re.I),
    ),
    (
        "capacity",
        re.compile(
            r"capacit(?:y|ies)|plants?|fabs?|factor(?:y|ies)|production|output|allocat|sold out|ability to supply|fulfil|shipments?|volume|available|in stock|supply agreements?|expansion|entrant|breaks? ground|mine|smelter",
            re.I,
        ),
    ),
    (
        "coverage",
        re.compile(
            r"analysts?|explainer|what [^.;]{0,40} means|weigh|roundup|story of the year|survey|report claims|here'?s why|why [^.;]{0,30} became",
            re.I,
        ),
    ),
)
_GENERIC_TOKENS = frozenset(
    [
        "price",
        "prices",
        "contract",
        "supply",
        "lead",
        "time",
        "times",
        "capacity",
        "shortage",
        "shortages",
        "backlog",
        "constraint",
        "constraints",
        "demand",
        "sold",
        "out",
        "of",
        "the",
        "and",
        "for",
        "to",
        "in",
        "on",
        "tight",
        "electrical",
        "industrial",
    ]
)
_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "and",
        "or",
        "to",
        "in",
        "on",
        "for",
        "with",
        "by",
        "at",
        "from",
        "as",
        "is",
        "are",
    ]
)


def scrub_instructions(text: str) -> str:
    """Drop every sentence that reads like an instruction to a model; the rest is the data."""
    kept = [s for s in _SENTENCE_SPLIT.split(text) if s.strip() and not _INJECTION.search(s)]
    return " ".join(kept).strip()


@dataclass
class LayerVocabulary:
    """Keyword phrases and salient tokens per layer, for the rule-based layer match."""

    phrases: dict[str, list[str]]
    tokens: dict[str, set[str]]

    @classmethod
    def from_theme_map(cls, theme_map: ThemeMap) -> LayerVocabulary:
        phrases: dict[str, list[str]] = {}
        tokens: dict[str, set[str]] = {}
        for _, layer in theme_map.layers():
            phrases.setdefault(layer.id, []).extend(k.lower() for k in layer.keywords)
            toks = tokens.setdefault(layer.id, set())
            for kw in layer.keywords:
                for t in re.findall(r"[a-z0-9][a-z0-9\-]+", kw.lower()):
                    if t not in _STOP and t not in _GENERIC_TOKENS and len(t) > 2:
                        toks.add(t)
            for t in re.findall(r"[a-z0-9][a-z0-9\-]+", layer.name.lower()):
                if t not in _STOP and t not in _GENERIC_TOKENS and len(t) > 3:
                    toks.add(t)
        return cls(phrases=phrases, tokens=tokens)

    def match(self, text: str, hint: str | None) -> str | None:
        """Best layer by keyword hits: a full phrase counts 3, a salient token 1; ties go to the
        hint; no hit at all falls back to the hint (the query that found the snippet)."""
        low = text.lower()
        words = set(re.findall(r"[a-z0-9][a-z0-9\-]+", low))
        scores: dict[str, int] = {}
        for layer_id, phrases in self.phrases.items():
            score = sum(3 for p in phrases if p in low)
            score += sum(1 for t in self.tokens.get(layer_id, ()) if t in words)
            if score:
                scores[layer_id] = score
        if not scores:
            return hint if hint in self.phrases else None
        best = max(scores.values())
        tied = [layer_id for layer_id, s in scores.items() if s == best]
        if hint in tied:
            return hint
        return tied[0] if len(tied) == 1 else (hint if hint in self.phrases else tied[0])


_LEAD_TIME_UP = re.compile(
    r"(?:lead|delivery|wait(?:ing)?) times?[^.;]{0,50}\b(?:extend|lengthen|stretch|rose|increas|grew|longer|doubled|now \d+|to \d+ weeks)|"
    r"(?:extended|longer|lengthening|stretched) (?:lead|delivery) times?",
    re.IGNORECASE,
)


def _direction(text: str) -> tuple[ConstraintDirection, float]:
    easing_hits = len(_EASING.findall(text))
    stripped = _EASING.sub(" ", text)
    tight_hits = len(_TIGHTENING.findall(stripped)) + len(_LEAD_TIME_UP.findall(stripped))
    if tight_hits == 0 and easing_hits == 0:
        return "neutral", 0.5
    if tight_hits > easing_hits:
        return "tightening", min(0.95, 0.6 + 0.1 * (tight_hits - easing_hits))
    if easing_hits > tight_hits:
        return "easing", min(0.95, 0.6 + 0.1 * (easing_hits - tight_hits))
    return "neutral", 0.4


def _kind(text: str, direction: ConstraintDirection) -> ConstraintKind:
    counts: list[tuple[int, int, ConstraintKind]] = []
    for order, (kind, pattern) in enumerate(_KIND_PATTERNS):
        n = len(pattern.findall(text))
        if n:
            counts.append((n, -order, kind))
    if not counts:
        return "other"
    if direction == "neutral" and any(k == "coverage" for _, _, k in counts):
        return "coverage"
    counts.sort(reverse=True)
    return counts[0][2]


class RuleBasedClassifier:
    """Direction lexicons per kind, layer by keyword hit, side from the theme map (PRD 4A.6)."""

    def __init__(self, theme_map: ThemeMap, is_valid_ticker: Callable[[str], bool]) -> None:
        self.theme_map = theme_map
        self.vocab = LayerVocabulary.from_theme_map(theme_map)
        self._is_valid = is_valid_ticker
        self._roles = _roles_by_layer(theme_map)

    def classify(self, snippet: FilingSnippet) -> ConstraintLabel:
        return self.classify_text(
            snippet.id, snippet.text, filer=snippet.filer_ticker, hint=snippet.layer_hint
        )

    def classify_text(
        self, snippet_id: str, text: str, *, filer: str | None, hint: str | None
    ) -> ConstraintLabel:
        clean = scrub_instructions(text)
        if not clean:
            return ConstraintLabel(
                snippet_id=snippet_id,
                layer_id=None,
                side="neutral",
                direction="neutral",
                kind="other",
                confidence=0.3,
            )
        layer_id = self.vocab.match(clean, hint)
        direction, confidence = _direction(clean)
        kind = _kind(clean, direction)
        side = self._side(clean, filer, layer_id)
        tickers = sorted(
            {t for t in _CASHTAG.findall(clean) if self._is_valid(t)}
            | {t for t in self._mentioned_map_tickers(clean) if self._is_valid(t)}
        )
        return ConstraintLabel(
            snippet_id=snippet_id,
            layer_id=layer_id,
            side=side,
            direction=direction,
            kind=kind,
            confidence=confidence,
            tickers=tickers,
        )

    def _side(self, text: str, filer: str | None, layer_id: str | None) -> ConstraintSide:
        if filer:
            role = self._role_of(filer, layer_id)
            if role is not None:
                return role
        roles: set[ConstraintSide] = set()
        for t in self._mentioned_map_tickers(text):
            role = self._role_of(t, layer_id)
            if role is not None:
                roles.add(role)
        if len(roles) == 1:
            return roles.pop()
        return "neutral"

    def _role_of(self, ticker: str, layer_id: str | None) -> ConstraintSide | None:
        by_layer = self._roles.get(ticker.upper())
        if not by_layer:
            return None
        if layer_id and layer_id in by_layer:
            return by_layer[layer_id]
        roles = set(by_layer.values())
        return next(iter(roles)) if len(roles) == 1 else None

    def _mentioned_map_tickers(self, text: str) -> list[str]:
        words = set(re.findall(r"\b[A-Z][A-Z0-9.\-]{0,5}\b", text))
        return [t for t in self.theme_map.tickers if t in words]


def _roles_by_layer(theme_map: ThemeMap) -> dict[str, dict[str, ConstraintSide]]:
    out: dict[str, dict[str, ConstraintSide]] = {}
    for _, layer in theme_map.layers():
        for c in layer.companies:
            out.setdefault(c.ticker, {})[layer.id] = "supplier" if c.is_supplier else "customer"
    return out


_SNIPPET_BLOCK = re.compile(
    r'<snippet id="([^"]+)"(?P<attrs>[^>]*)>\n?(?P<text>.*?)\n?</snippet>', re.DOTALL
)
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def rule_handler(
    theme_map: ThemeMap, is_valid_ticker: Callable[[str], bool]
) -> Callable[[str], Any]:
    """The ``RuleBasedProvider`` handler: parse the rendered prompt back into snippets."""
    classifier = RuleBasedClassifier(theme_map, is_valid_ticker)

    def handle(user_prompt: str) -> ConstraintLabelBatch:
        labels: list[ConstraintLabel] = []
        for m in _SNIPPET_BLOCK.finditer(user_prompt):
            attrs = dict(_ATTR.findall(m.group("attrs")))
            labels.append(
                classifier.classify_text(
                    m.group(1),
                    m.group("text"),
                    filer=attrs.get("filer") or None,
                    hint=attrs.get("layer_hint") or None,
                )
            )
        return ConstraintLabelBatch(labels=labels)

    return handle


def render_snippets(snippets: Sequence[FilingSnippet]) -> str:
    return "\n".join(
        f'<snippet id="{s.id}" source="{s.source}" date="{s.date.isoformat()}" '
        f'filer="{s.filer_ticker or ""}" form="{s.form or ""}" layer_hint="{s.layer_hint or ""}">\n'
        f"{s.text}\n</snippet>"
        for s in snippets
    )


def render_layers(theme_map: ThemeMap) -> str:
    return "\n".join(
        f"- {layer.id}: {layer.name} ({', '.join(layer.keywords[:5])})"
        for _, layer in theme_map.layers()
    )


# ------------------------------------------------------------------------- the classifier
@dataclass
class ClassificationReport:
    total: int = 0
    from_ground_truth: int = 0
    from_cache: int = 0
    from_provider: int = 0
    from_rules_fallback: int = 0
    unvalidated_tickers_rejected: int = 0
    unknown_layers_cleared: int = 0
    batches_failed: int = 0
    by_direction: Counter[str] = field(default_factory=Counter)


class ConstraintClassifier:
    """Label snippets through ground truth, the cache, or the provider (see the module doc)."""

    def __init__(
        self,
        theme_map: ThemeMap,
        llm: Any,
        *,
        is_valid_ticker: Callable[[str], bool],
        cache: Any | None = None,
        batch_size: int = 20,
        prompt_version: str = "1.0.0",
    ) -> None:
        self.theme_map = theme_map
        self.llm = llm  # LLMClient; typed loosely to keep the engine importable without it
        self.cache = cache
        self.batch_size = max(1, batch_size)
        self.prompt_version = prompt_version
        self._is_valid = is_valid_ticker
        self._layer_ids = {layer.id for _, layer in theme_map.layers()}
        self._rules = RuleBasedClassifier(theme_map, is_valid_ticker)
        self.report = ClassificationReport()

    def classify(
        self,
        snippets: Sequence[FilingSnippet],
        ground_truth: Mapping[str, ConstraintLabel] | None = None,
    ) -> dict[str, ConstraintLabel]:
        out: dict[str, ConstraintLabel] = {}
        pending: list[FilingSnippet] = []
        replay = ground_truth is not None and not getattr(self.llm, "is_live", False)
        for s in snippets:
            if s.id in out:
                continue
            if replay and ground_truth is not None and s.id in ground_truth:
                out[s.id] = self._validate(ground_truth[s.id], s)
                self.report.from_ground_truth += 1
                continue
            cached = self._cache_get(s.id)
            if cached is not None:
                out[s.id] = cached
                self.report.from_cache += 1
                continue
            pending.append(s)
        for i in range(0, len(pending), self.batch_size):
            batch = pending[i : i + self.batch_size]
            out.update(self._classify_batch(batch))
        self.report.total = len(out)
        self.report.by_direction = Counter(lbl.direction for lbl in out.values())
        return out

    def _classify_batch(self, batch: Sequence[FilingSnippet]) -> dict[str, ConstraintLabel]:
        by_id = {s.id: s for s in batch}
        labels: dict[str, ConstraintLabel] = {}
        try:
            result: ConstraintLabelBatch = self.llm.classify_bottleneck(batch, self.theme_map)
            for lbl in result.labels:
                snip = by_id.get(lbl.snippet_id)
                if snip is None:
                    continue  # a label for a snippet that was not in the batch is discarded
                labels[snip.id] = self._validate(lbl, snip)
            self.report.from_provider += len(labels)
        except Exception as exc:
            self.report.batches_failed += 1
            log.warning("classification batch failed (%s); rule-based stand-in used", exc)
        for s in batch:
            if s.id not in labels:
                labels[s.id] = self._validate(self._rules.classify(s), s)
                self.report.from_rules_fallback += 1
        for sid, lbl in labels.items():
            self._cache_set(sid, lbl)
        return labels

    def _validate(self, label: ConstraintLabel, snippet: FilingSnippet) -> ConstraintLabel:
        update: dict[str, Any] = {"snippet_id": snippet.id}
        if label.layer_id is not None and label.layer_id not in self._layer_ids:
            update["layer_id"] = None
            self.report.unknown_layers_cleared += 1
        valid = [t.upper() for t in label.tickers if self._is_valid(t)]
        rejected = len(label.tickers) - len(valid)
        if rejected:
            self.report.unvalidated_tickers_rejected += rejected
        if valid != list(label.tickers):
            update["tickers"] = sorted(set(valid))
        return label.model_copy(update=update) if update else label

    def _cache_key(self, snippet_id: str) -> str:
        return f"bottleneck:label:{self.prompt_version}:{snippet_id}"

    def _cache_get(self, snippet_id: str) -> ConstraintLabel | None:
        if self.cache is None:
            return None
        raw = self.cache.get(self._cache_key(snippet_id))
        if raw is None:
            return None
        try:
            return ConstraintLabel.model_validate(raw)
        except Exception:
            return None

    def _cache_set(self, snippet_id: str, label: ConstraintLabel) -> None:
        if self.cache is not None:
            self.cache.set(
                self._cache_key(snippet_id), label.model_dump(mode="json"), CACHE_TTL_SECONDS
            )


def labels_by_layer(
    snippets: Iterable[FilingSnippet], labels: Mapping[str, ConstraintLabel]
) -> dict[str, list[tuple[FilingSnippet, ConstraintLabel]]]:
    """Group labelled snippets by the layer the *label* names (not the search hint)."""
    out: dict[str, list[tuple[FilingSnippet, ConstraintLabel]]] = {}
    for s in snippets:
        lbl = labels.get(s.id)
        if lbl is None or lbl.layer_id is None:
            continue
        out.setdefault(lbl.layer_id, []).append((s, lbl))
    return out
