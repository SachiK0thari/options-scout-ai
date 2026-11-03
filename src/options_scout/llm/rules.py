"""Deterministic stand-ins for the LLM tasks (``--no-llm`` mode and fixture fallback).

These are intentionally simple and transparent. They are evaluated honestly in ``make eval``;
they are NOT meant to match a real model's quality.
"""

from __future__ import annotations

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
    Narrative,
    Paragraph,
    PostExtraction,
    ProfileParse,
    RiskProfile,
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
}
_NOT_TICKERS = {
    "I",
    "A",
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
    "TV",
    "PM",
    "AM",
    "K",
    "M",
    "MM",
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
    "FYI",
    "BTW",
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


def _tickers_after(low_text: str, text: str, keywords: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for kw in keywords:
        for m in re.finditer(kw, low_text):
            segment = text[m.end() : m.end() + 120]
            segment = re.split(
                r"[.;\n]| but | and (?:no|skip|avoid|exclude|exclud)", segment, maxsplit=1
            )[0]
            for t in _TICKER.findall(segment):
                if t not in _NOT_TICKERS and t not in found:
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
    """Sources as rendered by ``render_sources_block``: ``[{"tag", "title", "url", "kind", "text"}]``."""
    return [
        {"tag": tag, "title": title, "url": url, "kind": kind, "text": body.strip()}
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
            lines.append(
                f"{p.get('candidate_id')}: {p.get('contracts')} contract(s) of the {p.get('strategy')} with strike "
                f"{p.get('strike')} expiring {p.get('expiry')}, using {p.get('capital_used')} of capital with a "
                f"realistic loss of {p.get('realistic_loss')} if the underlying falls 30%.{extra}"
                + (
                    f" It is paired with short call {p.get('pmcc_short_call_id')}."
                    if p.get("pmcc_short_call_id")
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


def rule_answer_concept(user_prompt: str) -> Narrative:
    """``--no-llm`` concept answer: the top sources' opening sentences, each with its citation."""
    sources = parse_sources_block(user_prompt)
    m = re.search(r"copied exactly: (.*?)\n", user_prompt, re.DOTALL)
    disclaimer = m.group(1).strip() if m else ""
    paras = education_paragraphs(sources, limit=2)
    if not paras:
        paras = [Paragraph(mode="notice", text=NO_SOURCE_SENTENCE)]
    paras.append(Paragraph(mode="notice", text=disclaimer or "Education, not advice."))
    return Narrative(paragraphs=paras)


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
        "judge_explanation": rule_judge,
    }
