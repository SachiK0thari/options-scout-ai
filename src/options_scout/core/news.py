"""News Desk math (Phase 12, docs/capstone-plan.md section 12.3): dedupe, recency weights,
a rule-based classifier for ``--no-llm`` mode, and the calendar flags that touch a candidate.

Headlines never change a ranking. They become ``NewsFlag`` entries on candidates (an earnings
date inside the DTE window, an ex-dividend date before a short call's expiry) and a ``NewsBrief``
per ticker. The LLM classifier (step 12.5) replaces :func:`classify_rule_based` when a key is
present; the rule-based version is what the eval measures without one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from urllib.parse import urlsplit

from options_scout.config import NewsConfig
from options_scout.core.models import (
    ClassifiedNews,
    NewsBrief,
    NewsCategory,
    NewsFlag,
    NewsItem,
    NewsRelevance,
    OptionCandidate,
)

_WORD = re.compile(r"[a-z0-9]+")
_CATEGORY_PATTERNS: tuple[tuple[NewsCategory, re.Pattern[str]], ...] = (
    (  # guidance first: "lifts profit forecast" is an outlook, not a result
        "guidance",
        re.compile(
            r"\b(guidance|outlook|raises?|lifts?|cuts?|lowers?|trims?|warns?|expects|reaffirms?)\b",
            re.I,
        ),
    ),
    (  # macro before earnings so "retail sales" stays macro
        "macro",
        re.compile(
            r"\b(fed|federal reserve|interest rates?|inflation|tariffs?|economy|gdp|jobs report|"
            r"treasury yields?|consumer spending|dollar (strengthens|weakens)|rate (hikes?|cuts?|"
            r"expectations)|recession|unemployment|retail sales|strong dollar|weak dollar|"
            r"commodity prices)\b",
            re.I,
        ),
    ),
    (
        "earnings",
        re.compile(
            r"\b(earnings|quarterly results|results|q[1-4]\b|eps|revenue|profit|loss|sales)\b",
            re.I,
        ),
    ),
    (
        "m_and_a",
        re.compile(
            r"\b(acquire[sd]?|acquisition|merger|takeover|buyout|deal to buy|to buy|"
            r"in talks to buy)\b",
            re.I,
        ),
    ),
    (
        "legal_regulatory",
        re.compile(
            r"\b(lawsuit|sue[sd]?|settle[sd]?|settlement|antitrust|ftc|doj|sec probe|probe|"
            r"regulator|investigation|fine[sd]?|recalls?|ban|court|class action|patent|"
            r"trademark|complaint|disclosure rules|\bsec proposes)\b",
            re.I,
        ),
    ),
    (
        "product",
        re.compile(
            r"\b(launch(es)?|unveils?|introduces?|new (product|model|service)|rollout|release[sd]?|"
            r"debuts?)\b",
            re.I,
        ),
    ),
)
_RELEVANCE: dict[NewsCategory, NewsRelevance] = {
    "earnings": "high",
    "guidance": "high",
    "m_and_a": "high",
    "legal_regulatory": "high",
    "product": "medium",
    "macro": "low",
    "other": "low",
}


# ------------------------------------------------------------------------------- dedupe
def normalise_title(title: str) -> str:
    """Lower-case content tokens joined by one space; publisher suffixes after " - " or " | "
    are dropped so the same wire story under two mastheads collapses."""
    head = re.split(r"\s[-|–—]\s", title, maxsplit=1)[0]
    return " ".join(_WORD.findall(head.lower()))


def normalise_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}" if host else None


def dedupe(items: Iterable[NewsItem]) -> list[NewsItem]:
    """Newest first; a later item with the same normalised title or URL is dropped."""
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    out: list[NewsItem] = []
    for item in sorted(items, key=lambda i: i.published_at, reverse=True):
        t = normalise_title(item.title)
        u = normalise_url(item.url)
        if (t and t in seen_titles) or (u and u in seen_urls):
            continue
        if t:
            seen_titles.add(t)
        if u:
            seen_urls.add(u)
        out.append(item)
    return out


# ------------------------------------------------------------------------------ recency
def age_days(published_at: datetime, now: datetime) -> float:
    return max((now - published_at).total_seconds(), 0.0) / 86400.0


def recency_weight(published_at: datetime, now: datetime, half_life_days: float) -> float:
    """0.5 ** (age / half-life): 1.0 for a fresh item, 0.5 one half-life later."""
    if half_life_days <= 0:
        raise ValueError("half-life must be positive")
    return float(0.5 ** (age_days(published_at, now) / half_life_days))


def is_stale(published_at: datetime, now: datetime, stale_days: int) -> bool:
    return age_days(published_at, now) > stale_days


# ------------------------------------------------------------------------- classifying
def classify_rule_based(title: str) -> tuple[NewsCategory, NewsRelevance]:
    """Keyword classifier used without an LLM; the first matching category in priority order."""
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(title):
            return category, _RELEVANCE[category]
    return "other", "low"


def classify_items(
    items: Sequence[NewsItem], ticker: str, now: datetime, cfg: NewsConfig
) -> list[ClassifiedNews]:
    out: list[ClassifiedNews] = []
    for item in dedupe(items):
        category, relevance = classify_rule_based(item.title)
        out.append(
            ClassifiedNews(
                item=item,
                ticker=ticker.upper(),
                category=category,
                relevance=relevance,
                summary=item.title.strip(),
                weight=recency_weight(item.published_at, now, cfg.half_life_days),
                stale=is_stale(item.published_at, now, cfg.stale_days),
            )
        )
    return out


# ------------------------------------------------------------------------ event flags
def event_flags(
    candidate: OptionCandidate,
    *,
    as_of: date,
    earnings_date: date | None,
    ex_dividend_date: date | None,
    capture_window_days: int,
    earnings_unknown: bool = False,
) -> list[NewsFlag]:
    """Calendar events that touch a short option before it expires. Earnings matter to every
    short option (CSP and the PMCC short call); an ex-dividend date matters to a short call,
    whose holder may be exercised early for the dividend, most of all inside the capture window."""
    flags: list[NewsFlag] = []
    if candidate.strategy == "leaps":
        return flags
    if earnings_unknown:  # W5: a single stock with no known date may report before expiry
        flags.append(
            NewsFlag(
                candidate_id=candidate.id,
                ticker=candidate.ticker,
                flag="earnings_date_unknown",
                event_date=None,
                detail=(
                    "the earnings date could not be confirmed; it may fall before the "
                    f"{candidate.expiry.isoformat()} expiry"
                ),
            )
        )
    elif earnings_date is not None and as_of <= earnings_date <= candidate.expiry:
        flags.append(
            NewsFlag(
                candidate_id=candidate.id,
                ticker=candidate.ticker,
                flag="earnings_within_dte",
                event_date=earnings_date,
                detail=(
                    f"earnings on {earnings_date.isoformat()} fall before the "
                    f"{candidate.expiry.isoformat()} expiry"
                ),
            )
        )
    if (
        candidate.strategy == "pmcc_short_call"
        and ex_dividend_date is not None
        and as_of <= ex_dividend_date <= candidate.expiry
    ):
        days_before = (candidate.expiry - ex_dividend_date).days
        flags.append(
            NewsFlag(
                candidate_id=candidate.id,
                ticker=candidate.ticker,
                flag="ex_dividend_before_expiry",
                event_date=ex_dividend_date,
                detail=(
                    f"ex-dividend {ex_dividend_date.isoformat()} is {days_before} days before "
                    "expiry; early assignment of the short call is possible"
                ),
            )
        )
        if days_before <= capture_window_days:
            flags.append(
                NewsFlag(
                    candidate_id=candidate.id,
                    ticker=candidate.ticker,
                    flag="ex_dividend_capture_window",
                    event_date=ex_dividend_date,
                    detail=(
                        f"ex-dividend within {capture_window_days} days of expiry: a "
                        "dividend-capture exercise is likely if the call is in the money"
                    ),
                )
            )
    return flags


# -------------------------------------------------------------------------------- brief
def build_brief(
    ticker: str,
    items: Sequence[ClassifiedNews],
    flags: Sequence[NewsFlag],
    now: datetime,
    max_items: int,
) -> NewsBrief:
    """Heaviest (most recent) items first, high relevance before low at equal weight."""
    order = {"high": 0, "medium": 1, "low": 2}
    ranked = sorted(
        items,
        key=lambda c: (-round(c.weight, 6), order[c.relevance], -c.item.published_at.timestamp()),
    )
    return NewsBrief(
        ticker=ticker.upper(),
        items=list(ranked[:max_items]),
        flags=[f for f in flags if f.ticker == ticker.upper()],
        as_of=now,
    )
