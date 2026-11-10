"""Deterministic stand-ins for the LLM tasks (``--no-llm`` mode and fixture fallback).

These are intentionally simple and transparent. They are evaluated honestly in ``make eval``;
they are NOT meant to match a real model's quality.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from options_scout.config import AppConfig
from options_scout.core.models import (
    NO_SOURCE_SENTENCE,
    AccountType,
    EntityType,
    ExtractedEntity,
    ExtractionBatch,
    FireVariant,
    GoalKind,
    GoalParse,
    Holding,
    HoldingsParse,
    Intent,
    KnowledgeLevel,
    Narrative,
    Paragraph,
    PostExtraction,
    ProfileParse,
    RiskProfile,
    RouteDecision,
    Strategy,
)
from options_scout.social.resolution import BrandMap

# ------------------------------------------------------------------------- profile parsing
_MONEY = re.compile(
    r"(?<![\w.])\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|m|mm|thousand|grand|million|mil)?\b(?!\s*%)",
    re.IGNORECASE,
)
_WORDS = {
    "quarter million": 250_000.0,
    "half a million": 500_000.0,
    "half million": 500_000.0,
    "a million": 1_000_000.0,
    "one million": 1_000_000.0,
}
_MULT = {"k": 1e3, "thousand": 1e3, "grand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "mil": 1e6}
_TICKER = re.compile(r"\b[A-Z]{1,5}\b")
_COMPANY_TICKERS = {
    "costco": "COST",
    "nike": "NKE",
    "starbucks": "SBUX",
    "tesla": "TSLA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "chipotle": "CMG",
    "deckers": "DECK",
    "hoka": "DECK",
    "e.l.f.": "ELF",
    "elf beauty": "ELF",
    "crocs": "CROX",
    "lululemon": "LULU",
    "amazon": "AMZN",
    "nvidia": "NVDA",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "meta": "META",
    "spy": "SPY",
    "qqq": "QQQ",
    "amd": "AMD",
    "palantir": "PLTR",
    "gamestop": "GME",
    "coinbase": "COIN",
    "walmart": "WMT",
    "target": "TGT",
    "disney": "DIS",
    "netflix": "NFLX",
    "pepsi": "PEP",
    "coca-cola": "KO",
    "coke": "KO",
    "bloom energy": "BE",
    "freeport": "FCX",
    "philip morris": "PM",
}
# Options and account jargon users capitalise on purpose: never a ticker (unless written $CSP).
_JARGON = {
    "CSP",
    "CSPS",
    "LEAPS",
    "PMCC",
    "PMCCS",
    "IRA",
    "ROTH",
    "USD",
    "OK",
    "ETF",
    "ETFS",
    "US",
    "DTE",
    "IV",
    "OTM",
    "ITM",
    "ATM",
    "YOLO",
    "AI",
    "K",
    "M",
    "MM",
    "FYI",
    "BTW",
}

# Everyday words that are also real tickers (BE, SO, IT, PM, UP, DO, ON ...). A match counts as a
# ticker only when it is clearly deliberate: written as a cashtag ($BE), or capitalised inside a
# message that is otherwise lower case. Single letters (I, A) need the cashtag.
_ENGLISH_WORDS = {
    "I",
    "A",
    "TV",
    "PM",
    "AM",
    "NO",
    "AND",
    "OR",
    "THE",
    "FOR",
    "WITH",
    "BUT",
    "NOT",
    "MY",
    "ME",
    "TO",
    "IN",
    "ON",
    "OF",
    "AT",
    "IS",
    "IT",
    "BE",
    "DO",
    "SO",
    "IF",
    "UP",
    "BP",
    "IMO",
    "ASAP",
    "LOL",
    "APR",
    "REIT",
    "REITS",
    "VIX",
    "FAANG",
    "MAG",
    "ONLY",
    "PUTS",
    "CALLS",
    "PUT",
    "CALL",
    "LLC",
    "CEO",
    "PE",
    "EPS",
    "YTD",
    "KEEP",
    "SKIP",
    "NONE",
    "ALL",
    "MAX",
    "MIN",
    "NYSE",
    "SP",
    "S&P",
    "WSB",
    "SEC",
    "ROI",
}


def _parse_amount(text: str) -> float | None:
    low = text.lower()
    for phrase, val in _WORDS.items():
        if phrase in low:
            return val
    best: float | None = None
    for m in _MONEY.finditer(text):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        val *= _MULT.get(unit, 1.0)
        # ignore things that are clearly not account sizes (position counts, deltas, DTE, years)
        if val < 1_000:
            continue
        best = val if best is None else max(best, val)
    return best


def _account_type(low: str) -> AccountType | None:
    if re.search(r"\b(portfolio margin|pm account|\bpm\b)", low):
        return "portfolio_margin"
    negated_margin = bool(re.search(r"\b(no|not|without|non|zero)[- ]?margin\b", low))
    has_margin = bool(re.search(r"\bmargin\b", low)) and not negated_margin
    has_cash = bool(
        re.search(r"\b(ira|roth|401k|cash account|cash acct|cash only|in cash)\b", low)
        or re.search(r"\bcash\b(?![- ]secured)", low)
        or negated_margin
    )
    if has_margin and has_cash:
        return None  # contradictory → ask
    if has_margin:
        return "margin"
    if has_cash:
        return "cash"
    return None


def _risk(low: str) -> tuple[RiskProfile | None, bool]:
    cons = bool(
        re.search(
            r"\b(conservative|cautious|low[- ]risk|safe|capital preservation|risk[- ]averse|"
            r"zero risk|no risk|can(?:no|')t afford to lose|preserve)\b",
            low,
        )
    )
    bal = bool(re.search(r"\b(balanced|moderate|medium[- ]risk|middle of the road|neutral)\b", low))
    agg = bool(
        re.search(r"\b(aggressive|high[- ]risk|yolo|risk[- ]on|swing for the fences|degen)\b", low)
    )
    hits: list[RiskProfile] = []
    if cons:
        hits.append("conservative")
    if bal:
        hits.append("balanced")
    if agg:
        hits.append("aggressive")
    if len(hits) == 1:
        return hits[0], False
    if len(hits) > 1:
        return None, True
    return None, False


def _strategies(low: str) -> list[Strategy] | None:
    out: list[Strategy] = []
    if re.search(
        r"\b(csp|csps|cash[- ]secured puts?|sell(?:ing)? puts?|wheel|short puts?)\b",
        low,
    ):
        out.append("csp")
    if re.search(r"\b(leaps?|long[- ]dated calls?|long calls?)\b", low):
        out.append("leaps")
    if re.search(r"\b(pmcc|pmccs|poor man'?s covered call|diagonal)\b", low):
        out.append("pmcc")
    return out or None


def _is_ticker(token: str, before: str, *, shouted: bool) -> bool:
    """Decide whether an upper-case word is a ticker. ``before`` is the text preceding it."""
    if before.endswith("$"):
        return True  # a cashtag is always deliberate
    if token in _JARGON:
        return False
    if token in _ENGLISH_WORDS:
        if shouted or len(token) < 2:
            return False  # "I LIKE IT" or "I like AAPL": not a ticker
        if re.search(r"\d\s*$", before):
            return False  # "3 PM", "9 AM"
    return True


def _tickers_after(low_text: str, text: str, keywords: tuple[str, ...]) -> list[str]:
    # Someone writing in lower case who types BE in capitals means Bloom Energy; in an all-caps
    # message the same letters are just the verb.
    shouted = re.search(r"[a-z]{2,}", text) is None
    found: list[str] = []
    for kw in keywords:
        for m in re.finditer(kw, low_text):
            segment = text[m.end() : m.end() + 120]
            segment = re.split(
                r"[.;\n]| but | and (?:no|skip|avoid|exclude|exclud)", segment, maxsplit=1
            )[0]
            for tm in _TICKER.finditer(segment):
                t = tm.group(0)
                if t not in found and _is_ticker(t, segment[: tm.start()], shouted=shouted):
                    found.append(t)
            seg_low = segment.lower()
            for name, t in _COMPANY_TICKERS.items():
                if name in seg_low and t not in found:
                    found.append(t)
    return found


_BP_PHRASE = re.compile(
    r"(buying power|\bbp\b|to allocate|to deploy|to work with|to put to work)", re.IGNORECASE
)
_AV_PHRASE = re.compile(
    r"(account (?:is )?(?:worth|value|total|size)|portfolio (?:is )?(?:worth|value)|total account|"
    r"account of|net liq(?:uidation)?)",
    re.IGNORECASE,
)
_UNSURE = re.compile(r"\b(not sure|unsure|maybe|haven't decided|undecided|somewhere between)\b")


def _amount_near(text: str, phrase: re.Pattern[str], window: int = 45) -> float | None:
    for m in phrase.finditer(text):
        after = _parse_amount(text[m.end() : m.end() + window])
        if after is not None:
            return after
        before = _parse_amount(text[max(0, m.start() - window) : m.start()])
        if before is not None:
            return before
    return None


_LEVEL_BEGINNER = re.compile(
    r"\b(never (?:traded|sold|bought|used) (?:an? )?options?|new to options|new to (?:this|investing|"
    r"trading)|beginner|complete novice|first (?:time|option)|just (?:starting|getting started)|"
    r"don'?t (?:really )?(?:know|understand) (?:options|much)|explain (?:everything|like i'?m new))\b",
    re.IGNORECASE,
)
_LEVEL_ADVANCED = re.compile(
    r"\b(advanced|experienced|been (?:trading|selling) options for|years of options|"
    r"i (?:know|understand) the greeks|skip the basics|no need to explain|professional)\b",
    re.IGNORECASE,
)
_LEVEL_INTERMEDIATE = re.compile(
    r"\b(intermediate|some experience|traded (?:a few|some) options|know the basics|"
    r"comfortable with (?:options|puts|calls))\b",
    re.IGNORECASE,
)


def parse_knowledge_level(text: str) -> KnowledgeLevel | None:
    """beginner / intermediate / advanced from self-descriptions, or None (Phase 12)."""
    if _LEVEL_BEGINNER.search(text):
        return "beginner"
    if _LEVEL_ADVANCED.search(text):
        return "advanced"
    if _LEVEL_INTERMEDIATE.search(text):
        return "intermediate"
    return None


def rule_parse_profile(user_prompt: str) -> ProfileParse:
    m = re.search(r"<request>\n?(.*?)\n?</request>", user_prompt, re.DOTALL)
    text = m.group(1) if m else user_prompt
    low = text.lower()
    amounts = [
        a for a in (_parse_amount(seg) for seg in re.split(r"[,;]| or | and |\bbut\b", text)) if a
    ]
    av_explicit = _amount_near(text, _AV_PHRASE)
    bp = _amount_near(text, _BP_PHRASE)
    if bp is None:
        others = [a for a in amounts if a != av_explicit]
        bp = others[0] if others else _parse_amount(text)
    if _UNSURE.search(low) and len(set(amounts)) > 1 and _amount_near(text, _BP_PHRASE) is None:
        bp = None  # "maybe 10k, maybe 50k" → ask
    acct = _account_type(low)
    risk, contradictory = _risk(low)
    strategies = _strategies(low)
    exclude = _tickers_after(
        low, text, (r"\b(?:no|skip|avoid|exclude|excluding|without|not|never)\b",)
    )
    watch = [
        t
        for t in _tickers_after(
            low,
            text,
            (
                r"\b(?:like|watchlist|watch list|interested in|focus on|favou?rite|love|own|prefer|such as|e\.g\.|including|in)\b",
                r"\b(?:puts?|calls?|csps?|leaps|pmccs?|wheel|options?|trades?) (?:on|for|against)\b",
            ),
        )
        if t not in exclude
    ]
    mp = re.search(r"(\d{1,2})\s*(?:positions|names|tickers|trades)", low)
    needs = [
        f
        for f, v in (("buying_power", bp), ("account_type", acct), ("risk_profile", risk))
        if v is None
    ]
    if contradictory and "risk_profile" not in needs:
        needs.append("risk_profile")
    account_value = av_explicit if av_explicit is not None else bp
    return ProfileParse(
        buying_power=bp,
        account_value=account_value,
        account_type=acct,
        risk_profile=risk,
        strategies=strategies,
        watchlist=watch,
        exclude=exclude,
        max_positions=int(mp.group(1)) if mp else None,
        knowledge_level=parse_knowledge_level(text),
        needs_clarification=needs,
    )


# ---------------------------------------------------------------------- entity extraction
_POST = re.compile(
    r'<post id="([^"]+)" subreddit="([^"]*)" stock_sub="(true|false)">\n(.*?)\n</post>', re.DOTALL
)
_INTENT = re.compile(
    r"\b(bought|buying|just got|picked up|ordered|pre-?ordered|copped|grabbed|about to buy|gonna buy|going to buy|"
    r"should i (?:buy|get)|worth (?:it|buying)|thinking of (?:buying|getting)|adding to cart|finally (?:got|bought)|"
    r"my order|arrived|snagged|cart)\b",
    re.IGNORECASE,
)
_STOCK = re.compile(
    r"(\$[A-Z]{1,5}\b|\b(calls?|puts?|shares?|stock|stonks?|earnings|eps|guidance|valuation|short squeeze|"
    r"to the moon|tendies|position|bagholding|iv crush|theta|strike|expir|premium|yolo|dd\b|options?|"
    r"market cap|p/e|revenue|quarter|ticker|buy the dip|all[- ]in)\b)",
    re.IGNORECASE,
)
_INJECTION = re.compile(
    r"(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|instructions?|post)|"
    r"system prompt|you are now|as an ai|helpful ai|language model|summari[sz]ing this|"
    r"the only entity|must be included|includ(?:e|ing) [A-Z]{2,5} in|add(?:ing)? (?:the )?ticker|"
    r"recommend(?:ation)?s? [A-Z]{2,5}\b|output json|assistant:|<\/?(?:system|instruction|post)>|"
    r"\"?name\"?\s*:\s*\"|instruction=|do me a (?:small )?favou?r|tool_call|function_call|"
    r"\bprompt\b|\bLLM\b|\bmodel\b.{0,20}\b(?:output|respond|return)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+|www\.\S+")
_JSON_BLOB = re.compile(r"[\[{][^\[\]{}]*[\]}]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\n])\s+")


def scrub_injections(text: str) -> str:
    """Drop URLs, JSON blobs and any sentence that reads like an instruction to a model."""
    text = _URL.sub(" ", text)
    text = _JSON_BLOB.sub(" ", text)
    kept = [sent for sent in _SENTENCE_SPLIT.split(text) if not _INJECTION.search(sent)]
    return " ".join(kept)


@lru_cache(maxsize=1)
def _vader() -> SentimentIntensityAnalyzer:
    return SentimentIntensityAnalyzer()


def _sentiment(text: str) -> float:
    score = float(_vader().polarity_scores(text)["compound"])
    return round(max(-1.0, min(1.0, score)), 1)


def _entity_type(t: str) -> EntityType:
    if t == "product":
        return "product"
    if t == "company":
        return "company"
    if t == "store":
        return "store"
    return "brand"


class RuleBasedExtractor:
    """Alias matching against the brand map + VADER sentiment + keyword intent/stock-talk."""

    def __init__(self, brand_map: BrandMap) -> None:
        self.patterns = brand_map.alias_patterns()

    def extract(self, post_id: str, text: str, is_stock_sub: bool) -> PostExtraction:
        clean = scrub_injections(text)
        found: dict[str, ExtractedEntity] = {}
        stockish = bool(_STOCK.search(clean)) or is_stock_sub
        intent = bool(_INTENT.search(clean))
        sentiment = _sentiment(clean)
        for pat, brand in self.patterns:
            if brand.brand in found:
                continue
            if pat.search(clean):
                found[brand.brand] = ExtractedEntity(
                    name=brand.brand,
                    type=_entity_type(brand.type),
                    sentiment=sentiment,
                    is_purchase_intent=intent and not is_stock_sub,
                    is_stock_talk=stockish,
                )
        return PostExtraction(post_id=post_id, entities=list(found.values()))

    def extract_batch(self, user_prompt: str) -> ExtractionBatch:
        results = [
            self.extract(pid, body, stock == "true")
            for pid, _sub, stock, body in _POST.findall(user_prompt)
        ]
        return ExtractionBatch(results=results)


# ----------------------------------------------------------------------------- explainer
def _payload_from(user_prompt: str) -> dict[str, Any]:
    m = re.search(r"<payload>\n?(.*?)\n?</payload>", user_prompt, re.DOTALL)
    try:
        data = json.loads(m.group(1)) if m else {}
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


_SOURCE_BLOCK = re.compile(
    r'<source id="(S\d+)" title="([^"]*)" url="([^"]*)" kind="([^"]*)">\n?(.*?)\n?</source>',
    re.DOTALL,
)


def parse_sources_block(text: str) -> list[dict[str, str]]:
    """Sources as rendered by ``render_sources_block``: ``[{"tag", "title", "url", "kind", "text"}]``.
    The renderer escapes every field, so a block ends only where the renderer ended it; the
    fields are unescaped after the split."""
    return [
        {
            "tag": tag,
            "title": html.unescape(title),
            "url": html.unescape(url),
            "kind": kind,
            "text": html.unescape(body.strip()),
        }
        for tag, title, url, kind, body in _SOURCE_BLOCK.findall(text)
    ]


def _first_sentences(text: str, limit: int = 420) -> str:
    """Opening sentence(s) of a chunk, whole sentences only, up to ``limit`` characters."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    idx = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: idx + 1] if idx > limit // 3 else cut.rsplit(" ", 1)[0] + "."


def education_paragraphs(sources: list[dict[str, str]], limit: int = 3) -> list[Paragraph]:
    """One cited education paragraph per source (verbatim excerpt, so every number is grounded).

    An excerpt that happens to contain a banned phrase (a 10-K saying "we cannot guarantee…") is
    skipped so the deterministic stand-in always passes the language check; the allow-list for
    quoted sources arrives with the Compliance agent in step 10.4.
    """
    from options_scout.core.compliance import BANNED_PHRASES

    out: list[Paragraph] = []
    seen_titles: set[str] = set()
    for src in sources:
        if src["title"] in seen_titles:
            continue
        excerpt = _first_sentences(src["text"])
        if any(b in excerpt.lower() for b in BANNED_PHRASES):
            continue
        seen_titles.add(src["title"])
        out.append(
            Paragraph(
                mode="education",
                text=f"**{src['title']}.** {excerpt} [{src['tag']}]",
                citations=[src["tag"]],
            )
        )
        if len(out) >= limit:
            break
    return out


def rule_explain(user_prompt: str) -> Narrative:
    """Template narrative that only echoes payload numbers verbatim (so the verifier passes),
    with education paragraphs assembled from the retrieved sources, each carrying its tag."""
    payload = _payload_from(user_prompt)
    sources = parse_sources_block(user_prompt)
    prof = payload.get("profile", {})
    alloc = payload.get("allocation", {})
    regime = payload.get("regime", {})
    positions = payload.get("positions", [])
    risk = payload.get("risk", {})
    trends = payload.get("trends", [])
    paras: list[Paragraph] = []

    def result(text: str) -> None:
        paras.append(Paragraph(mode="screen_result", text=text))

    result(
        f"**Allocation.** With {prof.get('buying_power')} of buying power in a {prof.get('account_type')} "
        f"account and a {prof.get('risk_profile')} profile, the plan sets aside {alloc.get('csp_dollars')} "
        f"for cash-secured put collateral, {alloc.get('leaps_dollars')} for LEAPS/PMCC and keeps "
        f"{alloc.get('cash_dollars')} in reserve. The VIX reading of {regime.get('vix')} sits at the "
        f"{regime.get('vix_percentile')} percentile of its past year, so the regime is "
        f'{str(regime.get("label", "")).replace("_", " ")} and the tilt applied was "{alloc.get("tilt")}".'
    )
    qs = payload.get("quality_screen", {})
    if qs:
        kept = qs.get("passed", [])
        names = ", ".join(f"{q.get('ticker')} (quality {q.get('quality_score')})" for q in kept[:8])
        dropped = qs.get("excluded", [])
        drop_txt = (
            " Excluded: "
            + "; ".join(
                f"{q.get('ticker')} ({'; '.join(q.get('reasons', [])[:2])})" for q in dropped[:5]
            )
            + "."
            if dropped
            else ""
        )
        result(
            f"**Quality screen.** {qs.get('passed_count')} underlying(s) passed the good-to-own gate "
            f"(curated list plus limits on realised and implied volatility, price, liquidity and distance "
            f"below the {qs.get('drawdown_lookback_days')}-day high): {names or 'none'}.{drop_txt} "
            f"Only these were screened for options."
        )
    if trends:
        tr = ", ".join(
            f"{t.get('entity')} (score {t.get('score')}{', ' + str(t.get('ticker')) if t.get('ticker') else ', not investable'})"
            for t in trends[:5]
        )
        result(
            f"**Trend board.** The consumer-trend scan surfaced {tr}. Scores combine mention velocity, "
            f"purchase intent, cross-source confirmation and the gap between social and news attention; "
            f"stock-forum hype is penalised rather than rewarded."
        )
    else:
        result("**Trend board.** No social trend signals were available for this run.")
    board = payload.get("bottlenecks") or {}
    if board.get("layers"):
        top = ", ".join(
            f"{ly.get('layer')} (score {ly.get('score')}, thesis {ly.get('thesis_state')})"
            for ly in board["layers"][:3]
        )
        comps = board.get("companies") or []
        names = (
            ", ".join(f"{c.get('ticker')} {c.get('score')}" for c in comps[:5])
            if comps
            else "none of the screened underlyings"
        )
        weakening = [
            ly.get("layer") for ly in board["layers"] if ly.get("thesis_state") == "weakening"
        ]
        result(
            f"**Bottleneck board.** The supply-constraint scan is a secondary signal that re-orders "
            f"quality-gated stocks and never adds one. Tightest layers: {top}. Curated suppliers with "
            f"a company score: {names}."
            + (
                f" Thesis weakening (a falsifier tripped, so scores in the layer are decayed): "
                f"{', '.join(weakening)}."
                if weakening
                else ""
            )
            + " A layer score describes the state of a shortage, not a forecast."
        )
    # education paragraphs sit between the screen and the positions they explain
    paras.extend(education_paragraphs(sources))
    if positions:
        lines = []
        for p in positions:
            payoff = p.get("payoff") or {}
            extra = ""
            if payoff.get("breakeven") is not None:
                extra = f" Breakeven at expiry {payoff.get('breakeven')}"
                if payoff.get("max_loss") is not None:
                    extra += f", maximum loss {payoff.get('max_loss')}"
                extra += "."
            bflags = p.get("bottleneck_flags") or []
            flag_txt = ""
            if bflags:
                parts = []
                if "bottleneck_easing" in bflags:
                    parts.append(
                        "bottleneck_easing (new supply or decelerating prices in its layer)"
                    )
                if "bottleneck_support" in bflags:
                    parts.append("bottleneck_support (its supply layer is scored tight)")
                if "catalyst_inside_dte" in bflags:
                    parts.append(
                        "catalyst_inside_dte (a catalyst falls inside the contract's life)"
                    )
                flag_txt = ", flagged " + " and ".join(parts)
            lines.append(
                f"{p.get('candidate_id')}: {p.get('contracts')} contract(s) of the {p.get('strategy')} with strike "
                f"{p.get('strike')} expiring {p.get('expiry')}, using {p.get('capital_used')} of capital with a "
                f"realistic loss of {p.get('realistic_loss')} if the underlying falls 30%{flag_txt}.{extra}"
                + (
                    f" It is paired with short call {p.get('pmcc_short_call_id')}."
                    if p.get("pmcc_short_call_id")
                    else ""
                )
                + (
                    f" The earnings date for {p.get('candidate_id')} is unknown and could fall "
                    "before expiry."
                    if p.get("earnings_unknown")
                    else ""
                )
            )
        result("**Sized positions.** " + " ".join(lines))
    else:
        result(
            "**Sized positions.** No candidate fit inside the risk constraints for this profile."
        )
    checks = risk.get("checks", [])
    passed = sum(1 for c in checks if c.get("passed"))
    stress = risk.get("stress", [])
    stress_txt = "; ".join(f"a {s.get('shock')} move gives {s.get('pnl')}" for s in stress)
    result(
        f"**Risk.** {passed} of {len(checks)} constraint checks pass. Stress test with an instant move and "
        f"an IV shock: {stress_txt}. The combined loss at a 30% drop across all positions is "
        f"{payload.get('portfolio', {}).get('realistic_loss')}."
    )
    warnings = risk.get("warnings", [])
    if warnings:
        paras.append(
            Paragraph(
                mode="notice",
                text="**Warnings and limitations.** " + " ".join(str(w) for w in warnings[:6]),
            )
        )
    paras.append(
        Paragraph(
            mode="notice",
            text=(
                "Market data is delayed and Greeks are model-derived; these are screened candidates that "
                "meet the configured criteria, not recommendations."
            ),
        )
    )
    paras.append(Paragraph(mode="notice", text=str(payload.get("disclaimer", ""))))
    return Narrative(paragraphs=paras)


def _tag(user_prompt: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\n?(.*?)\n?</{tag}>", user_prompt, re.DOTALL)
    return m.group(1).strip() if m else ""


def _question_terms(question: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z][A-Za-z.\-]+", question) if len(t) > 2]


def is_run_data(source: dict[str, str]) -> bool:
    """Run facts and the run's evidence posts are data about *this* screen, never education."""
    return source.get("kind") in ("evidence", "run")


def why_paragraphs(sources: list[dict[str, str]], question: str) -> list[Paragraph]:
    """``why`` answers: the run-facts source lines that mention a term of the question, reported
    as ``screen_result`` (run data may not appear in an education paragraph), then any evidence
    posts behind the trend signal."""
    # the facts are found by their reserved kind; a title is text a post can imitate (W13)
    facts = [s for s in sources if s.get("kind") == "run"]
    posts = [s for s in sources if s.get("kind") == "evidence"]
    if not facts and not posts:
        return []
    terms = {t.lower() for t in _question_terms(question)}
    tickers = {t for t in re.findall(r"\b[A-Z]{2,5}\b", question)}
    out: list[Paragraph] = []
    for src in facts:
        lines = [ln.strip() for ln in src["text"].splitlines() if ln.strip()]
        hits = [
            ln
            for ln in lines
            if any(tk in ln for tk in tickers) or any(t in ln.lower() for t in terms if len(t) > 4)
        ]
        picked = hits[:4] or lines[1:4]
        head = (
            "**What the bottleneck board recorded.**"
            if src["title"].startswith("Bottleneck board")
            else "**What the screen recorded.**"
        )
        out.append(
            Paragraph(
                mode="screen_result",
                text=f"{head} {' '.join(picked)} [{src['tag']}]",
                citations=[src["tag"]],
            )
        )
    if posts:
        quoted = " ".join(f"“{_first_sentences(p['text'], 200)}” [{p['tag']}]" for p in posts[:2])
        out.append(
            Paragraph(
                mode="screen_result",
                text=f"**Evidence behind the signal.** {quoted}",
                citations=[p["tag"] for p in posts[:2]],
            )
        )
    return out


def rule_answer_concept(user_prompt: str) -> Narrative:
    """``--no-llm`` answer: for ``why`` the run facts as screen_result, then the top knowledge
    sources' opening sentences as cited education paragraphs."""
    sources = parse_sources_block(user_prompt)
    m = re.search(r"copied exactly: (.*?)\n", user_prompt, re.DOTALL)
    disclaimer = m.group(1).strip() if m else ""
    intent = re.search(r"Intent of this question: (\w+)", user_prompt)
    question = _tag(user_prompt, "question")
    paras: list[Paragraph] = []
    if (intent and intent.group(1) == "why") or any(is_run_data(s) for s in sources):
        # run facts, or the bottleneck board attached to a question outside a screen (Phase 11)
        paras.extend(why_paragraphs(sources, question))
    knowledge = [s for s in sources if not is_run_data(s)]
    paras.extend(education_paragraphs(knowledge, limit=2 if not paras else 1))
    if not paras:
        paras = [Paragraph(mode="notice", text=NO_SOURCE_SENTENCE)]
    paras.append(Paragraph(mode="notice", text=disclaimer or "Education, not advice."))
    return Narrative(paragraphs=paras)


# ------------------------------------------------------------------- goals (Phase 12, 12.3)
_AMOUNT = re.compile(
    r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|m|mm|thousand|grand|million|mil)?\b(?!\s*%)",
    re.IGNORECASE,
)
_PER_MONTH = r"(?:a|per|each|every|/)\s*(?:month|mo\b|mth)"
_PER_YEAR = r"(?:a|per|each|every|/)\s*(?:year|yr|annum)|annually|yearly"
_MONTHLY = re.compile(_PER_MONTH, re.IGNORECASE)
_YEARLY = re.compile(_PER_YEAR, re.IGNORECASE)
_INCOME_CUE = re.compile(
    r"\b(make|earn|generate|collect|take home|bring in|want|need|live (?:on|off)|income|premium)\b",
    re.IGNORECASE,
)
_CONTRIB_CUE = re.compile(
    r"\b(add|adding|contribute|contributing|save|saving|put (?:in|away|aside)|invest(?:ing)?|"
    r"deposit(?:ing)?|dca)\b",
    re.IGNORECASE,
)
_EXPENSE_CUE = re.compile(
    r"\b(spend|spending|expenses?|cost of living|costs? me|burn|budget|live on|retire on|"
    r"need to live)\b",
    re.IGNORECASE,
)
_MIN_EXPENSE_CUE = re.compile(
    r"\b(bare[- ]?minimum|minimum|lean|at least|barebones)\b", re.IGNORECASE
)
_PART_TIME_CUE = re.compile(r"part[- ]time", re.IGNORECASE)
_TARGET_BALANCE = re.compile(
    r"\b(?:grow|get|turn|build|take|double|go)\b[^.?!]{0,40}?\b(?:to|into|of)\s+("
    + _AMOUNT.pattern
    + r")|\b(?:reach|hit|get to|end up with)\s+(?:about |around )?("
    + _AMOUNT.pattern
    + r")",
    re.IGNORECASE,
)
_GROW_FROM = re.compile(
    r"\b(?:grow|turn|take|double)\s+(?:my |the )?(" + _AMOUNT.pattern + r")\s+(?:to|into)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
}
_HORIZON = re.compile(
    r"\b(?:in|within|over|for|during|next)\s+(\d+(?:\.\d+)?|[a-z]+)\s*(?:years?|yrs?)\b|"
    r"\b(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\s+(?:from now|out|horizon|away)\b",
    re.IGNORECASE,
)
_TARGET_AGE = re.compile(r"\b(?:by|at|before)\s+(?:age\s+)?(\d{2})\b", re.IGNORECASE)
_CURRENT_AGE = re.compile(
    r"\b(?:i(?:'| a)?m|i am|age|aged)\s+(\d{2})\b(?!\s*(?:k|%|years? (?:from|out|away)))|"
    r"\b(\d{2})\s+years?\s+old\b",
    re.IGNORECASE,
)
_HAVE = re.compile(
    r"\b(?:have|got|hold(?:ing)?|sitting on|saved|balance of|portfolio of|account of|on my)\s+"
    r"(?:about |around |roughly |some )?(" + _AMOUNT.pattern + r")"
    r"(?!\s*(?:" + _PER_MONTH + r"|" + _PER_YEAR + r"))",
    re.IGNORECASE,
)
_WITHDRAWAL = re.compile(
    r"(\d(?:\.\d+)?)\s?%\s*(?:withdrawal|rule|swr|safe withdrawal)", re.IGNORECASE
)
_FIRE_WORDS = re.compile(
    r"\b(fire|f\.i\.r\.e\.|financial(?:ly)? independen(?:ce|t)|retire(?:ment|d)?|"
    r"early retirement|lean fire|fat fire|coast fire|barista fire|coast|barista)\b",
    re.IGNORECASE,
)
_VARIANTS: tuple[tuple[FireVariant, re.Pattern[str]], ...] = (
    ("lean", re.compile(r"\blean\b", re.IGNORECASE)),
    ("fat", re.compile(r"\bfat\b", re.IGNORECASE)),
    ("coast", re.compile(r"\bcoast(?:ing)?\b", re.IGNORECASE)),
    ("barista", re.compile(r"\bbarista\b|\bpart[- ]time\b", re.IGNORECASE)),
)
_GOAL_VERB = re.compile(
    r"\b(can i|could i|will i|would i|when (?:can|could|will|would|am|do) i|how long|"
    r"how many years|years (?:to|until)|i want|i'?d like|i need|"
    r"is it (?:possible|realistic|feasible|doable)|is \S+ enough|enough to|"
    r"does (?:this|that|it) (?:fit|work|get me|cover)|plan(?:ning)? (?:for|to)|on track|"
    r"retire|be financially independent|reach|grow|double|make|earn|generate|"
    r"cover my|live (?:off|on)|get to|want to|would like to|hope to|aim to|spend)\b",
    re.IGNORECASE,
)
_GOAL_NOUN = re.compile(
    r"\b(goal|fire|financial(?:ly)? independen(?:ce|t)|retire\w*|coast|barista|savings rate|"
    r"income|premium|a month|per month|monthly|/month|million|target|expenses?)\b|"
    r"\d+\s?k\b|\$\s?\d",
    re.IGNORECASE,
)
_DEFINITION_START = re.compile(
    r"^\s*(what (?:is|are|does|do)|define|explain what|how does .* work)", re.IGNORECASE
)


def _amount_value(m: re.Match[str]) -> float | None:
    raw, unit = m.group(1), (m.group(2) or "").lower()
    try:
        val = float(raw.replace(",", ""))
    except ValueError:
        return None
    return val * _MULT.get(unit, 1.0)


def _amount_in(text: str | None) -> float | None:
    """The first money amount in ``text`` (None when there is none)."""
    m = _AMOUNT.search(text or "")
    return _amount_value(m) if m else None


def _amounts_with_context(text: str) -> list[tuple[float, str, str]]:
    """(value, 40 chars before, 30 chars after) for every money amount in the text."""
    out: list[tuple[float, str, str]] = []
    for m in _AMOUNT.finditer(text):
        val = _amount_value(m)
        if val is None:
            continue
        out.append((val, text[max(0, m.start() - 40) : m.start()], text[m.end() : m.end() + 30]))
    return out


def _horizon_years(message: str) -> float | None:
    for m in _HORIZON.finditer(message):
        token = (m.group(1) or m.group(2) or "").lower()
        if token in _NUMBER_WORDS:
            return float(_NUMBER_WORDS[token])
        try:
            return float(token)
        except ValueError:
            continue
    return None


def rule_parse_goal(user_prompt: str) -> GoalParse:
    """Regex goal parser: the ``--no-llm`` stand-in for ``parse_goal`` and the fallback when the
    LLM is unavailable. Amounts are read with their surrounding words: "add $500 a month" is a
    contribution, "make $400 a month" an income target, "spend 48k a year" expenses."""
    message = _tag(user_prompt, "message") or user_prompt
    low = message.lower()
    fields: dict[str, Any] = {}
    for val, before, after in _amounts_with_context(message):
        lead = after.lstrip()
        per_month = bool(_MONTHLY.match(lead))
        per_year = bool(_YEARLY.match(lead))
        near_part_time = bool(_PART_TIME_CUE.search(before[-25:] + after[:25]))
        if per_month and _CONTRIB_CUE.search(before):
            fields.setdefault("monthly_contribution", val)
        elif per_month and _EXPENSE_CUE.search(before):
            key = "minimum_expenses" if _MIN_EXPENSE_CUE.search(before) else "annual_expenses"
            fields.setdefault(key, val * 12.0)
        elif per_month:
            fields.setdefault("target_monthly_income", val)
        elif per_year and _EXPENSE_CUE.search(before[-20:]):
            key = "minimum_expenses" if _MIN_EXPENSE_CUE.search(before) else "annual_expenses"
            fields.setdefault(key, val)
        elif (per_year and near_part_time) or near_part_time:
            fields.setdefault("part_time_income", val)
    m_t = _TARGET_BALANCE.search(message)
    if m_t:
        target = _amount_in(m_t.group(1) or m_t.group(4))
        if target is not None and target >= 1_000:
            fields["target_balance"] = target
    m_g = _GROW_FROM.search(message)
    if m_g:
        grow_from = _amount_in(m_g.group(1))
        if grow_from is not None and grow_from >= 1_000:
            fields["start_balance"] = grow_from
    m_h = _HAVE.search(message)
    if m_h and "start_balance" not in fields:
        start = _amount_in(m_h.group(1))
        if start is not None and start >= 1_000 and start != fields.get("target_balance"):
            fields["start_balance"] = start
    horizon = _horizon_years(message)
    if horizon is not None:
        fields["horizon_years"] = horizon
    m_a = _TARGET_AGE.search(message)
    if m_a:
        fields["target_age"] = float(m_a.group(1))
    m_c = _CURRENT_AGE.search(message)
    if m_c:
        fields["current_age"] = float(m_c.group(1) or m_c.group(2))
    m_w = _WITHDRAWAL.search(message)
    if m_w:
        fields["withdrawal_rate"] = float(m_w.group(1)) / 100.0
    if _FIRE_WORDS.search(low):
        fields["kind"] = "fire"
        fields["variant"] = next((v for v, pat in _VARIANTS if pat.search(low)), "regular")
        if "annual_expenses" not in fields and "minimum_expenses" in fields:
            fields["annual_expenses"] = fields["minimum_expenses"]
    elif "target_monthly_income" in fields:
        fields["kind"] = "income"
    elif "target_balance" in fields:
        kind: GoalKind = "contribution" if fields.get("monthly_contribution") else "growth"
        fields["kind"] = kind
    needs: list[str] = []
    k = fields.get("kind")
    if k is None:
        needs.append("goal")
    elif k == "fire" and "annual_expenses" not in fields:
        needs.append("annual_expenses")
    elif k in ("growth", "contribution") and not (
        fields.get("horizon_years") or fields.get("target_age")
    ):
        needs.append("horizon_years")
    fields["needs_clarification"] = needs
    return GoalParse(**fields)


def is_goal_message(message: str) -> bool:
    """Router test for the ``goal`` intent: a goal verb and a goal noun (or FIRE wording), not a
    definition question and not a hypothetical profile change."""
    low = message.lower()
    if _DEFINITION_START.match(low) or _WHAT_IF.search(low):
        return False
    if _FIRE_WORDS.search(low):
        return True
    if not (_GOAL_VERB.search(low) and _GOAL_NOUN.search(low)):
        return False
    return rule_parse_goal(message).kind is not None


def rule_explain_goal(user_prompt: str) -> Narrative:
    """Deterministic goal narrative: numbers copied from the payload, concepts quoted from the
    sources, the status and the stress path always stated (compliance check 9)."""
    payload = _payload_from(user_prompt)
    sources = parse_sources_block(user_prompt)
    m_disc = re.search(r"copied exactly: (.+)", user_prompt)
    disc = m_disc.group(1).strip() if m_disc else "Education, not advice."
    plan = payload.get("goal_plan") or {}
    paras: list[Paragraph] = []
    if plan.get("clarification"):
        paras.append(Paragraph(mode="notice", text=str(plan["clarification"])))
    else:
        goal = plan.get("goal", {})
        status = plan.get("status_text", "does not fit")
        req, avail, cap = (
            plan.get("required_return_pct"),
            plan.get("available_return_pct"),
            plan.get("profile_cap_pct"),
        )
        text = f"**Goal check: this goal {status}.**"
        if req is not None:
            text += f" The {goal.get('kind', 'goal')} goal needs about {req}% a year"
            if avail is not None:
                text += (
                    f"; the stress-adjusted yield available is {avail}% and the "
                    f"{goal.get('risk_profile', 'current')} profile's cap is {cap}%."
                )
            else:
                text += "."
        for note in plan.get("notes") or []:
            text += f" {note}."
        paras.append(Paragraph(mode="screen_result", text=text))
        levers = plan.get("levers") or []
        if levers:
            paras.append(
                Paragraph(
                    mode="screen_result",
                    text="Levers, none of them a recommendation: " + " ".join(levers) + ".",
                )
            )
        proj = plan.get("projection") or {}
        if proj.get("base") is not None:
            paras.append(
                Paragraph(
                    mode="screen_result",
                    text=(
                        f"At the base yield the balance would be about ${proj['base']:,} after "
                        f"{proj['years']} years; on the stress path, which takes the "
                        f"{proj['stress_drop_pct']}% scenario's realistic loss in year one, it "
                        f"would be about ${proj['stress']:,}."
                    ),
                )
            )
        fire = plan.get("fire")
        if fire:
            text = (
                f"This is a {fire['variant']} FIRE plan: expenses of ${fire['expense_target']:,} "
                f"a year at a {fire['withdrawal_rate_pct']}% withdrawal rate give a FIRE number "
                f"of ${fire['fire_number']:,}"
            )
            if fire.get("years_to_fi") is not None:
                text += (
                    f", which the diversified-portfolio projection at "
                    f"{fire['assumed_return_pct']}% would reach in about {fire['years_to_fi']} years"
                )
            text += (
                ". The withdrawal rate comes from research on diversified stock and bond "
                "portfolios, not from options income"
            )
            if fire.get("income_coverage_pct") is not None:
                text += (
                    f"; the screen's premium yield would cover about "
                    f"{fire['income_coverage_pct']}% of those expenses and is not a safe "
                    "withdrawal rate"
                )
            paras.append(Paragraph(mode="screen_result", text=text + "."))
    paras.extend(education_paragraphs(sources, limit=2))
    paras.append(Paragraph(mode="notice", text=disc))
    return Narrative(paragraphs=paras)


# -------------------------------------------------------------- holdings (Phase 12, 12.4)
_HOLDING_FORMS = (
    # "200 AAPL at $150", "200 shares of AAPL bought at 150", "200 AAPL @150"
    re.compile(
        r"(?P<shares>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:shares?\s+(?:of\s+)?|x\s*)?(?P<ticker>[A-Z]{1,5})\b"
        r"(?:[^,;\n]{0,25}?(?:@|at|for|cost(?: basis)?(?: of)?|basis(?: of)?|paid)\s*\$?\s*(?P<cost>\d+(?:,\d{3})*(?:\.\d+)?))?",
    ),
    # "AAPL 200 @ 150", "AAPL: 200 shares at 150", "AAPL,200,150"
    re.compile(
        r"\b(?P<ticker>[A-Z]{1,5})\b[:,\s]+(?P<shares>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:shares?|sh)?"
        r"(?:[^,;\n]{0,25}?(?:@|at|for|cost(?: basis)?(?: of)?|basis(?: of)?|paid|,)\s*\$?\s*(?P<cost>\d+(?:,\d{3})*(?:\.\d+)?))?",
    ),
)
_HOLDINGS_CUE = re.compile(
    r"\b(my (?:holdings|positions|portfolio|shares|stocks|account holds)|i (?:own|hold|have|bought)|"
    r"holdings?:|portfolio:|positions?:|here (?:are|is) (?:my|what i)|analy[sz]e (?:my|these|this)|"
    r"shares? of|long \d)\b",
    re.IGNORECASE,
)
_NOT_TICKERS = {
    "CSP",
    "LEAPS",
    "PMCC",
    "IRA",
    "ETF",
    "USD",
    "AT",
    "FOR",
    "AND",
    "OR",
    "THE",
    "MY",
    "IN",
    "ON",
    "TO",
    "OF",
    "A",
    "I",
    "DTE",
    "IV",
    "OTM",
    "ITM",
    "ROTH",
    "K",
}
_ACCOUNT_WORDS = (("ira", "ira"), ("roth", "ira"), ("margin", "margin"), ("cash", "cash"))


def _holding_from(match: re.Match[str]) -> Holding | None:
    ticker = match.group("ticker").upper()
    if ticker in _NOT_TICKERS or (len(ticker) < 2 and ticker not in {"V", "F", "T", "C", "K"}):
        return None
    try:
        shares = float(match.group("shares").replace(",", ""))
    except (TypeError, ValueError):
        return None
    if shares <= 0 or shares > 10_000_000:
        return None
    cost_raw = match.group("cost")
    cost = float(cost_raw.replace(",", "")) if cost_raw else None
    return Holding(ticker=ticker, shares=shares, cost_basis=cost)


_CSV_ROW = re.compile(
    r"^\s*(?P<ticker>[A-Za-z]{1,5})\s*[,;\t|]\s*(?P<shares>\d+(?:\.\d+)?)\s*"
    r"(?:[,;\t|]\s*\$?(?P<cost>\d+(?:\.\d+)?)?)?\s*(?:[,;\t|]\s*(?P<account>\w+))?\s*$"
)


def _merge_into(found: dict[str, Holding], h: Holding) -> None:
    prev = found.get(h.ticker)
    if prev is None:
        found[h.ticker] = h
        return
    shares = prev.shares + h.shares
    basis = (
        (prev.shares * prev.cost_basis + h.shares * h.cost_basis) / shares
        if prev.cost_basis is not None and h.cost_basis is not None
        else None
    )
    found[h.ticker] = Holding(ticker=h.ticker, shares=shares, cost_basis=basis)


def rule_parse_holdings(user_prompt: str) -> HoldingsParse:
    """Regex holdings parser: the ``--no-llm`` stand-in for ``parse_holdings``. Reads CSV rows
    ("AAPL,200,150"), "200 AAPL at 150", "AAPL 200 @ 150" and "200 shares of MSFT"; lots of one
    ticker are merged."""
    message = _tag(user_prompt, "message") or user_prompt
    low = message.lower()
    account = next((acct for word, acct in _ACCOUNT_WORDS if re.search(rf"\b{word}\b", low)), None)
    found: dict[str, Holding] = {}
    prose_lines: list[str] = []
    for line in message.splitlines():
        m_csv = _CSV_ROW.match(line)
        if m_csv and m_csv.group("ticker").upper() not in _NOT_TICKERS | {"TICKER", "SYMBOL"}:
            cost = m_csv.group("cost")
            _merge_into(
                found,
                Holding(
                    ticker=m_csv.group("ticker"),
                    shares=float(m_csv.group("shares")),
                    cost_basis=float(cost) if cost else None,
                ),
            )
        elif m_csv and m_csv.group("ticker").upper() in {"TICKER", "SYMBOL"}:
            continue  # a CSV header
        else:
            prose_lines.append(line)
    prose = "\n".join(prose_lines)
    spans: list[tuple[int, int]] = []
    for form in _HOLDING_FORMS:
        for m in form.finditer(prose):
            if any(a <= m.start() < b for a, b in spans):
                continue
            h = _holding_from(m)
            if h is None:
                continue
            spans.append((m.start(), m.end()))
            _merge_into(found, h)
    holdings = [h.model_copy(update={"account": account}) if account else h for h in found.values()]
    needs = [] if holdings else ["holdings"]
    return HoldingsParse(
        holdings=sorted(holdings, key=lambda h: h.ticker), needs_clarification=needs
    )


def is_holdings_message(message: str) -> bool:
    """Router test for the ``holdings`` intent: a holdings cue plus at least one parsable
    position, or two or more parsable positions on their own (a pasted list)."""
    parsed = rule_parse_holdings(message)
    if not parsed.holdings:
        return False
    return bool(_HOLDINGS_CUE.search(message)) or len(parsed.holdings) >= 2


# ------------------------------------------------------------------ news (Phase 12, 12.5)
_HEADLINE_BLOCK = re.compile(r'<headline id="([^"]+)"[^>]*>\n?(.*?)\n?</headline>', re.DOTALL)
_NEWS_CUE = re.compile(
    r"\b(news|headlines?|in the press|announce[ds]?|any (?:news|updates?)|"
    r"what(?:'s| is) (?:happening|going on|new) (?:with|at|on)|earnings (?:date|call|report|release)|"
    r"ex[- ]dividend|dividend date|before (?:my |the )?(?:expiry|expiration)|catalysts?|"
    r"events? (?:before|coming|ahead)|recall|lawsuit)\b",
    re.IGNORECASE,
)


def rule_classify_news(user_prompt: str) -> BaseModel:
    """The ``--no-llm`` stand-in for ``classify_news``: the keyword classifier of ``core/news.py``
    on each rendered headline; the summary is the headline itself (data, never rewritten)."""
    from options_scout.core.models import NewsClassification, NewsClassificationBatch
    from options_scout.core.news import classify_rule_based

    items = []
    for hid, title in _HEADLINE_BLOCK.findall(user_prompt):
        category, relevance = classify_rule_based(title)
        items.append(
            NewsClassification(
                id=hid, category=category, relevance=relevance, summary=title.strip()[:300]
            )
        )
    return NewsClassificationBatch(items=items)


def is_news_message(message: str) -> bool:
    """Router test for the ``news`` intent: a news cue that is not a definition question."""
    low = message.lower()
    if _DEFINITION_START.match(low) or _WHAT_IF.search(low):
        return False
    return bool(_NEWS_CUE.search(low))


# -------------------------------------------------------------------- tax (Phase 12, 12.6)
_TAX_CUE = re.compile(
    r"\b(tax(?:es|ed|able|ation)?|wash[- ]sale|cost basis|\bbasis\b|holding period|long[- ]term|"
    r"short[- ]term|1256|1099|8949|6781|form \d{4}\b|schedule d|capital gains?|"
    r"qualified covered call|straddle rule|"
    r"early withdrawal|59 ?1/2|59\.5|roth|\bira\b|retirement account|pattern day|pdt\b|"
    r"portfolio margin|approval level|which account|what account|kind of account|"
    r"type of account|in an? (?:cash|margin|ira|roth) account|allowed in (?:an? )?(?:ira|roth|cash|margin))",
    re.IGNORECASE,
)


def is_tax_message(message: str) -> bool:
    """Router test for the ``tax`` intent: a tax or account-type cue, not a hypothetical, and not
    a profile description (which carries a buying-power amount)."""
    low = message.lower()
    if _WHAT_IF.search(low) or not _TAX_CUE.search(low):
        return False
    has_amount = _parse_amount(message) is not None
    strong = re.search(r"\b(tax|wash|basis|1256|1099|8949|6781|holding period|withdrawal)", low)
    return bool(strong) or not has_amount


def rule_answer_tax(user_prompt: str) -> Narrative:
    """``--no-llm`` tax answer: the illustrative facts as one screen_result paragraph, the tax
    sources' opening sentences as cited education, the tax disclaimer, the app disclaimer."""
    sources = parse_sources_block(user_prompt)
    m = re.search(r"copied exactly: (.*?)\n", user_prompt, re.DOTALL)
    disclaimer = m.group(1).strip() if m else "Education, not advice."
    m_tax = re.search(r"tax disclaimer: (.*?)\n", user_prompt, re.DOTALL)
    tax_disc = m_tax.group(1).strip() if m_tax else ""
    facts = _tag(user_prompt, "facts")
    question = _tag(user_prompt, "question").lower()
    paras: list[Paragraph] = []
    try:
        f = json.loads(facts) if facts else {}
    except json.JSONDecodeError:
        f = {}
    asks_basis = any(w in question for w in ("assign", "basis", "premium", "expire", "taxed"))
    asks_wash = any(w in question for w in ("wash", "loss"))
    if asks_basis and f.get("ticker") and f.get("assigned_basis_per_share") is not None:
        paras.append(
            Paragraph(
                mode="screen_result",
                text=(
                    f"Illustration with the screened {f['ticker']} {f['strike']:g} put: the premium "
                    f"of {f['premium']} per share is not taxed when received; if the put is assigned "
                    f"the shares' basis would be {f['assigned_basis_per_share']} per share "
                    f"({f['assigned_total_basis']:,} in total for the cash paid of "
                    f"{f['cash_paid_at_assignment']:,}); if it expires the whole "
                    f"{f['premium_if_expired']:,} would be a short-term gain."
                ),
            )
        )
    if asks_wash and f.get("wash_sale_window_start"):
        paras.append(
            Paragraph(
                mode="screen_result",
                text=(
                    f"A loss realised on {f['as_of']} would carry a wash-sale window from "
                    f"{f['wash_sale_window_start']} to {f['wash_sale_window_end']} "
                    f"({f['wash_sale_window_days']} days)."
                ),
            )
        )
    knowledge = [s for s in sources if not is_run_data(s)]
    if tax_disc:  # every tax document carries the sentence; the reply states it once, below
        knowledge = [
            {**s, "text": " ".join(s["text"].replace(tax_disc, " ").split())} for s in knowledge
        ]
    paras.extend(education_paragraphs(knowledge, limit=2))
    if not knowledge:
        paras.append(Paragraph(mode="notice", text=NO_SOURCE_SENTENCE))
    if tax_disc:
        paras.append(Paragraph(mode="notice", text=tax_disc))
    paras.append(Paragraph(mode="notice", text=disclaimer))
    return Narrative(paragraphs=paras)


# ------------------------------------------------------------------------ intent routing
_OFF_TOPIC = re.compile(
    r"\b(weather|joke|poem|recipe|movie|song|football|soccer|basketball|election|president|"
    r"bitcoin|crypto|ethereum|forex|real estate|mortgage|lottery|horoscope|translate|capital of|"
    r"who (won|is|was)|how old|birthday|hello|hi there|good morning|thanks?|thank you|"
    r"ignore (all )?(previous|prior|your) instructions|place (the|a|an|this) (trade|order)|"
    r"should i (buy|sell)|tell me what to (buy|sell|do)|what (stock )?should i buy|"
    r"which (one|stock|put|call) (should|would you)|do you recommend|your (favorite|favourite)|"
    r"price target|will (the market|it|[A-Z]{2,5}) (go|crash|rally|rise|fall|hit)|next week|tomorrow)\b",
    re.IGNORECASE,
)
_WHAT_IF = re.compile(
    r"\b(what if|suppose|supposing|hypothetically|instead of|if (i|it|my account) (had|were|was|only)|"
    r"and (with|if) (an? )?(aggressive|conservative|balanced|cash|margin)|how would (it|this|that) change)\b",
    re.IGNORECASE,
)
_WHY = re.compile(
    r"^\s*why\b|\bwhy (was|is|are|were|did|does|do|only|not|isn't|wasn't|didn't)\b|"
    r"\b(explain|justify) (the|this|that) (ranking|exclusion|order|choice|screen result)\b|"
    r"\bhow come\b",
    re.IGNORECASE,
)
_CONCEPT = re.compile(
    r"\b(what (is|are|does|do) (an? |the )?|define|definition of|meaning of|explain (what|how)|"
    r"how (does|do|is|are) .* (work|computed|calculated|defined|measured)|"
    r"difference between|tell me about|teach me|walk me through|what happens (when|at|if))\b",
    re.IGNORECASE,
)
_PROFILE_WORDS = re.compile(
    r"\b(buying power|account|margin|cash|conservative|balanced|aggressive|csp|cash[- ]secured|"
    r"puts?|leaps|pmcc|covered call|wheel|watchlist|exclud\w*|positions?|\$\s?\d|\d+\s?k\b|"
    r"thousand|million|risk (tolerance|appetite|profile)|ira|roth|401k)\b",
    re.IGNORECASE,
)
_SCREEN_VERBS = re.compile(
    r"\b(show me|find( me)?|screen|scan|look for|run (a|the|another|it)|rerun|re-run|start over|"
    r"new screen|from scratch|i have|i've got|i got|my (account|buying power) is|ideas?|candidates?)\b",
    re.IGNORECASE,
)
_STRONG_NEW_SCREEN = re.compile(  # phrasing that asks for a screen from scratch, even mid-thread
    r"\b(start over|from scratch|new screen|rerun|re-run|run (a|another) (new |fresh )?screen|"
    r"i have|i've got|i got|show me|find me|looking for|screen for|my (account|buying power) is)\b",
    re.IGNORECASE,
)
_REFINE = re.compile(
    r"\b(switch|change|make (it|that|me|my)|set (my|the|it)|use (a|an|my)|actually|instead,?\b|"
    r"rather|update|add|remove|drop|exclude|include|also (consider|include)|only|just|limit|cap|max(imum)?|"
    r"i'?m (actually |really )?(more )?(conservative|balanced|aggressive)|it'?s (a )?(cash|margin))\b",
    re.IGNORECASE,
)
_WHY_RUN_WORDS = re.compile(
    r"\b(excluded?|exclusion|ranked?|ranking|skipped|chosen|picked|selected|screened (in|out)|"
    r"gate|quality|position|candidate|above|below|first|last|missing|not (shown|listed|included|in))\b",
    re.IGNORECASE,
)


def rule_route(user_prompt: str) -> RouteDecision:
    """Regex router: the ``--no-llm`` stand-in for ``route_message`` and the fallback the
    Orchestrator uses when the LLM router is unavailable."""
    message = _tag(user_prompt, "message") or user_prompt
    has_report = "report exists" in user_prompt or "a report exists" in user_prompt
    low = message.lower()
    parsed = rule_parse_profile(message)
    changes: dict[str, Any] = {}
    if parsed.buying_power is not None:
        changes["buying_power"] = parsed.buying_power
        changes["account_value"] = parsed.account_value or parsed.buying_power
    if parsed.account_type:
        changes["account_type"] = parsed.account_type
    if parsed.risk_profile:
        changes["risk_profile"] = parsed.risk_profile
    if parsed.strategies:
        changes["strategies"] = parsed.strategies
    if parsed.watchlist:
        changes["watchlist"] = parsed.watchlist
    if parsed.exclude:
        changes["exclude"] = parsed.exclude
    if parsed.max_positions:
        changes["max_positions"] = parsed.max_positions

    # the stated experience level rides along with a profile change but never decides the intent
    # on its own account below ("I'm new to this, what is a put?" stays a concept question)
    level = parse_knowledge_level(message)

    def decide(intent: Intent, reason: str) -> RouteDecision:
        q = message.strip() if intent in ("concept", "why") else None
        carried = {**changes, **({"knowledge_level": level} if level else {})}
        return RouteDecision(
            intent=intent,
            question=q,
            profile_changes=carried if intent in ("refine_profile", "what_if") else {},
            reason=reason,
        )

    if _OFF_TOPIC.search(low) and not (_CONCEPT.search(low) and _PROFILE_WORDS.search(low)):
        return decide("off_topic", "off-topic keyword or advice request")
    if is_holdings_message(message) and not is_goal_message(message):
        return decide("holdings", "a list of positions the user already owns")
    if is_news_message(message) and not is_goal_message(message):
        return decide("news", "news or calendar events for a ticker")
    if is_tax_message(message) and not is_goal_message(message):
        return decide("tax", "a tax or account-type question")
    if is_goal_message(message):
        return decide("goal", "a goal the account should reach")
    if _WHAT_IF.search(low) and (changes or _PROFILE_WORDS.search(low)):
        return decide("what_if" if has_report else "new_screen", "hypothetical profile change")
    if _WHY.search(low) and (has_report or _WHY_RUN_WORDS.search(low)):
        return decide("why", "question about this run's results")
    if _CONCEPT.search(low) or (low.rstrip().endswith("?") and not changes):
        return decide("concept", "education question")
    if (
        has_report
        and _REFINE.search(low)
        and not _STRONG_NEW_SCREEN.search(low)
        and (changes or _PROFILE_WORDS.search(low))
    ):
        return decide("refine_profile", "profile field changed on an existing thread")
    if has_report and level and not changes and not _STRONG_NEW_SCREEN.search(low):
        # "treat me as a beginner" after a screen: same profile, explanations at the new level
        return decide("refine_profile", "knowledge level stated on an existing thread")
    if changes or _SCREEN_VERBS.search(low) or _PROFILE_WORDS.search(low):
        return decide("new_screen", "profile description or screen request")
    return decide("off_topic", "no options-screening content recognised")


class _Judge(BaseModel):
    faithfulness: int
    clarity: int
    policy: int
    notes: str = ""


def rule_judge(user_prompt: str) -> _Judge:
    return _Judge(faithfulness=0, clarity=0, policy=0, notes="LLM judge not run (no API key).")


def handlers(cfg: AppConfig) -> dict[str, Callable[[str], BaseModel]]:
    extractor: RuleBasedExtractor | None = None

    def extract(user: str) -> BaseModel:
        nonlocal extractor
        if extractor is None:
            extractor = RuleBasedExtractor(BrandMap.load(cfg.paths.brand_map))
        return extractor.extract_batch(user)

    return {
        "parse_profile": rule_parse_profile,
        "extract_entities": extract,
        "explain_report": rule_explain,
        "answer_concept": rule_answer_concept,
        "route_message": rule_route,
        "judge_explanation": rule_judge,
        "parse_goal": rule_parse_goal,
        "explain_goal": rule_explain_goal,
        "parse_holdings": rule_parse_holdings,
        "classify_news": rule_classify_news,
        "answer_tax": rule_answer_tax,
        "classify_bottleneck": _bottleneck_handler(cfg),
    }


def _bottleneck_handler(cfg: AppConfig) -> Callable[[str], BaseModel]:
    """Phase 11 (4A.6): lexicon + keyword stand-in; built lazily so the import stays cheap."""
    handler: Callable[[str], BaseModel] | None = None

    def handle(user: str) -> BaseModel:
        nonlocal handler
        if handler is None:
            from options_scout.bottleneck.classify import rule_handler
            from options_scout.bottleneck.themes import sec_ticker_validator

            handler = rule_handler(cfg.themes, sec_ticker_validator(cfg.paths.fixtures_dir))
        return handler(user)

    return handle
