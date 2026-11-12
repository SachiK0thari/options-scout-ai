"""news_brief_node (News Desk, Phase 12 step 12.5): per-ticker briefs, candidate flags, reply.

Briefs keep the heaviest (most recent) headlines; flags come from calendar arithmetic on the
run's candidates (earnings inside the DTE window, an ex-dividend date before a short call's
expiry when one is known). On a ``news`` chat turn the node also writes the reply: deterministic
paragraphs that quote headlines verbatim (compliance check 10 verifies every quote against the
payload) plus one cited paragraph on earnings risk. Headlines never change a ranking.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.explainer import sources_payload
from options_scout.agent.state import AgentState
from options_scout.core.compliance import resolve_citations
from options_scout.core.models import (
    ClassifiedNews,
    Narrative,
    NewsBrief,
    NewsFlag,
    OptionCandidate,
    Paragraph,
)
from options_scout.core.news import build_brief, event_flags
from options_scout.core.screeners import earnings_unknown
from options_scout.llm.rules import education_paragraphs
from options_scout.rag.models import Chunk, RetrievalResult, citation_of

NO_NEWS = "No headlines in the last {days} days for {tickers}."
NO_TICKER = (
    "Name a ticker or company for the news desk, for example 'any news on COST before expiry?'; "
    "after a screen it covers every stock that passed the gate."
)


def short_option_candidates(state: AgentState) -> list[OptionCandidate]:
    """Every short option of the run once: the CSPs and the PMCC short calls (several LEAPS may
    pair with the same short call)."""
    seen: dict[str, OptionCandidate] = {}
    for c in state.get("candidates") or []:
        if c.strategy == "csp":
            seen.setdefault(c.id, c)
    for p in state.get("pmcc_pairs") or []:
        seen.setdefault(p.short_call.id, p.short_call)
    return list(seen.values())


def news_payload(
    briefs: list[NewsBrief], flags: list[NewsFlag], state: AgentState, days: int, disclaimer: str
) -> dict[str, Any]:
    cands = {c.id: c for c in short_option_candidates(state)}
    return {
        "news": {
            "lookback_days": days,
            "tickers": [b.ticker for b in briefs],
            "headline_count": sum(len(b.items) for b in briefs),
            # W14: a per-ticker count is a computed figure, so it is in the payload to ground it
            "headline_count_by_ticker": {b.ticker: len(b.items) for b in briefs},
            "headlines": [
                {
                    "ticker": b.ticker,
                    "id": c.item.id,
                    "title": c.item.title,
                    "source": c.item.source,
                    "published": c.item.published_at.date().isoformat(),
                    "category": c.category,
                    "relevance": c.relevance,
                    "sentiment": None if c.sentiment is None else round(c.sentiment, 2),
                    "stale": c.stale,
                }
                for b in briefs
                for c in b.items
            ],
            "flags": [
                {
                    "ticker": f.ticker,
                    "flag": f.flag,
                    "event_date": f.event_date.isoformat() if f.event_date else None,
                    "strike": cands[f.candidate_id].strike if f.candidate_id in cands else None,
                    "expiry": cands[f.candidate_id].expiry.isoformat()
                    if f.candidate_id in cands
                    else None,
                    "detail": f.detail,
                }
                for f in flags
            ],
        },
        "disclaimer": disclaimer,
    }


def news_narrative(payload: dict[str, Any], sources: list[Chunk], disclaimer: str) -> Narrative:
    n = payload["news"]
    paras: list[Paragraph] = []
    for ticker in n["tickers"]:
        rows = [h for h in n["headlines"] if h["ticker"] == ticker]
        if not rows:
            paras.append(
                Paragraph(
                    mode="notice",
                    text=NO_NEWS.format(days=n["lookback_days"], tickers=ticker),
                )
            )
            continue
        order = {"high": 0, "medium": 1, "low": 2}
        top = sorted(rows, key=lambda h: (order[h["relevance"]], h["published"]), reverse=False)[:3]
        quoted = "; ".join(
            f"“{h['title']}” ({h['source']}, {h['published']}, {h['category'].replace('_', ' ')}, "
            f"{h['relevance']} relevance"
            + (f", sentiment {h['sentiment']}" if h["sentiment"] is not None else "")
            + (", stale" if h["stale"] else "")
            + ")"
            for h in top
        )
        paras.append(
            Paragraph(
                mode="screen_result",
                text=(
                    f"**{ticker} news desk.** {len(rows)} headline(s) in the last "
                    f"{n['lookback_days']} days. Most relevant: {quoted}."
                ),
            )
        )
    if n["flags"]:
        parts = []
        for f in n["flags"][:6]:
            where = (
                f"the {f['ticker']} {f['strike']:g} short option expiring {f['expiry']}"
                if f["strike"] is not None
                else f["ticker"]
            )
            when = f" on {f['event_date']}" if f["event_date"] else ""
            parts.append(f"{where}: {f['flag'].replace('_', ' ')}{when}")
        paras.append(
            Paragraph(
                mode="screen_result",
                text="Calendar flags on screened candidates: " + "; ".join(parts) + ".",
            )
        )
    paras.extend(
        education_paragraphs(
            [
                {"tag": f"S{i}", "title": c.title, "url": c.url, "kind": c.kind, "text": c.text}
                for i, c in enumerate(sources, start=1)
            ],
            limit=1,
        )
    )
    paras.append(Paragraph(mode="notice", text=disclaimer))
    return Narrative(paragraphs=paras)


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def news_brief_node(state: AgentState) -> dict[str, Any]:
        cfg = deps.cfg.news
        now = deps.md.now()
        today = deps.md.today()
        classified: list[ClassifiedNews] = list(state.get("news_classified") or [])
        by_ticker: dict[str, list[ClassifiedNews]] = {}
        for c in classified:
            by_ticker.setdefault(c.ticker, []).append(c)
        snapshots = state.get("market_data") or {}
        flags: list[NewsFlag] = []
        for cand in short_option_candidates(state):
            snap = snapshots.get(cand.ticker)
            flags.extend(
                event_flags(
                    cand,
                    as_of=today,
                    earnings_date=snap.earnings_date if snap is not None else None,
                    ex_dividend_date=None,  # no provider in this repo exposes ex-dividend dates
                    capture_window_days=cfg.capture_window_days,
                    earnings_unknown=snap is not None and earnings_unknown(snap),
                )
            )
        tickers = sorted(by_ticker) or sorted({c.ticker for c in short_option_candidates(state)})
        briefs = [
            build_brief(t, by_ticker.get(t, []), flags, now, cfg.max_items_per_ticker)
            for t in tickers
        ]
        out: dict[str, Any] = {"news_briefs": briefs, "news_flags": flags}
        if state.get("intent") != "news":
            return out
        disclaimer = deps.cfg.settings.disclaimer
        if not briefs:
            out.update(
                answer=Narrative(
                    paragraphs=[
                        Paragraph(mode="notice", text=NO_TICKER),
                        Paragraph(mode="notice", text=disclaimer),
                    ]
                ),
                citations=[],
                sources=[],
                retrievals=[],
                explain_payload={"news": {"clarification": NO_TICKER}, "disclaimer": disclaimer},
            )
            return out
        sources: list[Chunk] = []
        retrievals: list[RetrievalResult] = []
        try:
            result = deps.knowledge().retrieve(
                "earnings risk for short options before expiry", kind="concepts", top_k=1
            )
            retrievals.append(result)
            sources = result.chunks[:1]
        except Exception:  # the citation is a convenience, never a blocker
            sources = []
        payload = news_payload(briefs, flags, state, cfg.lookback_days, disclaimer)
        payload["sources"] = sources_payload(sources)
        answer = news_narrative(payload, sources, disclaimer)
        out.update(
            answer=answer,
            citations=resolve_citations(answer, [citation_of(c) for c in sources]),
            sources=sources,
            retrievals=retrievals,
            explain_payload=payload,
        )
        return out

    return news_brief_node
