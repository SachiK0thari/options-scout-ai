"""holdings_reply_node (Portfolio, Phase 12 step 12.4): the reply to a ``holdings`` chat turn.

Deterministic ``screen_result`` paragraphs quote the analysis (every number is in the payload),
one cited ``education`` paragraph comes from the basics documents on diversification and
concentration, and the disclaimer closes. The text still passes Compliance like every reply.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.explainer import sources_payload
from options_scout.agent.nodes.holdings_intake import CLARIFICATION
from options_scout.agent.state import AgentState
from options_scout.core.compliance import resolve_citations
from options_scout.core.models import HoldingsAnalysis, Narrative, Paragraph
from options_scout.llm.rules import education_paragraphs
from options_scout.rag.models import Chunk, RetrievalResult, citation_of

_QUERIES = [
    "diversification idiosyncratic versus market risk",
    "concentration risk after a cash-secured put is assigned",
]

# W25 step 5: the score has no look-through, so say what it counts
DIVERSIFICATION_CAPTION = (
    "The score counts each ticker as one position: an index fund is treated as a single holding."
)


def holdings_payload(a: HoldingsAnalysis, disclaimer: str) -> dict[str, Any]:
    return {
        "holdings": {
            "total_value": round(a.total_value),
            "position_count": len(a.positions),
            "score_max": 100,
            "lot_size": 100,
            "positions": [
                {
                    "ticker": p.ticker,
                    "shares": round(p.shares, 2),
                    "price": round(p.price, 2),
                    "market_value": round(p.market_value),
                    "weight_pct": round(p.weight * 100),
                    "sector": p.sector,
                    "unrealised_pnl": None if p.unrealised_pnl is None else round(p.unrealised_pnl),
                    "expense_ratio_pct": (
                        None if p.expense_ratio is None else round(p.expense_ratio * 100, 3)
                    ),
                    "beta": None if p.beta is None else round(p.beta, 2),
                    "beta_low": None if p.beta_low is None else round(p.beta_low, 2),
                    "beta_high": None if p.beta_high is None else round(p.beta_high, 2),
                    "covered_call_lots": p.covered_call_lots,
                }
                for p in a.positions
            ],
            "by_sector_pct": {k: round(v * 100) for k, v in a.by_sector.items()},
            "hhi": round(a.hhi, 3),
            "effective_positions": round(a.effective_positions, 1),
            "diversification_score": round(a.diversification_score),
            "weighted_expense_ratio_pct": (
                None
                if a.weighted_expense_ratio is None
                else round(a.weighted_expense_ratio * 100, 3)
            ),
            "etf_expense_ratio_pct": (
                None if a.etf_expense_ratio is None else round(a.etf_expense_ratio * 100, 3)
            ),
            "beta_weighted_exposure": (
                None if a.beta_weighted_exposure is None else round(a.beta_weighted_exposure, 2)
            ),
            "beta_weighted_exposure_low": (
                None
                if a.beta_weighted_exposure_low is None
                else round(a.beta_weighted_exposure_low, 2)
            ),
            "beta_weighted_exposure_high": (
                None
                if a.beta_weighted_exposure_high is None
                else round(a.beta_weighted_exposure_high, 2)
            ),
            "beta_interval_pct": None if a.beta_interval is None else round(a.beta_interval * 100),
            "largest_position": a.largest_position,
            "largest_sector": a.largest_sector,
            "covered_call_eligible": a.covered_call_eligible,
            "post_assignment": [
                {
                    "candidate_id": x.candidate_id,
                    "ticker": x.ticker,
                    "strike": x.strike,
                    "weight_before_pct": round(x.weight_before * 100),
                    "weight_after_pct": round(x.weight_after * 100),
                    "cash_used": round(x.cash_used),
                    "includes_other_puts": x.includes_other_puts,
                }
                for x in a.post_assignment
            ],
            "notes": a.notes,
        },
        "disclaimer": disclaimer,
    }


def _one_row_per_combined_ticker(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows that already count every sized put on their ticker repeat the same figure; keep one."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for x in rows:
        if x.get("includes_other_puts"):
            if x["ticker"] in seen:
                continue
            seen.add(x["ticker"])
        out.append(x)
    return out


def holdings_narrative(payload: dict[str, Any], sources: list[Chunk], disclaimer: str) -> Narrative:
    h = payload["holdings"]
    paras: list[Paragraph] = []
    top = sorted(h["positions"], key=lambda p: -p["weight_pct"])[:3]
    top_text = ", ".join(f"{p['ticker']} {p['weight_pct']}%" for p in top)
    by_sector = sorted(h["by_sector_pct"].items(), key=lambda kv: -kv[1])
    sectors = ", ".join(f"{k} {v}%" for k, v in by_sector)
    paras.append(
        Paragraph(
            mode="screen_result",
            text=(
                f"**Holdings analysis.** {len(h['positions'])} position(s) worth "
                f"${h['total_value']:,} at the run's prices. Largest weights: {top_text}. "
                f"By sector: {sectors}. "
                f"Diversification score {h['diversification_score']} out of 100 "
                f"(HHI {h['hhi']}, about {h['effective_positions']} effective positions). "
                f"{DIVERSIFICATION_CAPTION}"
            ),
        )
    )
    extras: list[str] = []
    if h["weighted_expense_ratio_pct"] is not None and h.get("etf_expense_ratio_pct") is not None:
        extras.append(  # W25: the ETFs' own ratio, and what it costs the whole portfolio
            f"the ETF holdings carry an average expense ratio of {h['etf_expense_ratio_pct']}% a "
            f"year, a drag of {h['weighted_expense_ratio_pct']}% a year on the whole portfolio"
        )
    if h["beta_weighted_exposure"] is not None:
        exposure = f"beta-weighted exposure to the index is {h['beta_weighted_exposure']}"
        lo, hi = h.get("beta_weighted_exposure_low"), h.get("beta_weighted_exposure_high")
        if lo is not None and hi is not None and h.get("beta_interval_pct") is not None:
            # W25: an estimate from daily returns, so its range is stated with it
            exposure += (
                f" ({h['beta_interval_pct']}% range {lo} to {hi}, estimated from daily returns)"
            )
        extras.append(exposure)
    if h["covered_call_eligible"]:
        extras.append(
            "lots of 100 shares that could write a covered call: "
            + ", ".join(h["covered_call_eligible"])
        )
    if extras:
        joined = "; ".join(extras)  # str.capitalize() would lower-case "ETF" and the tickers
        paras.append(Paragraph(mode="screen_result", text=joined[0].upper() + joined[1:] + "."))
    if h["post_assignment"]:
        rows = "; ".join(
            (
                f"the sized {x['ticker']} puts, all assigned, would take {x['ticker']} from "
                if x.get("includes_other_puts")
                else f"the {x['ticker']} {x['strike']:g} put would take {x['ticker']} from "
            )
            + f"{x['weight_before_pct']}% to {x['weight_after_pct']}% of holdings plus buying power"
            for x in _one_row_per_combined_ticker(h["post_assignment"])[:5]
        )
        paras.append(
            Paragraph(
                mode="screen_result",
                text=(
                    f"Concentration if a screened put is assigned: {rows}. The sizer caps this "
                    "share at the profile's limit (the seventh constraint)."
                ),
            )
        )
    for note in h["notes"]:
        paras.append(Paragraph(mode="notice", text=note))
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
    def holdings_reply_node(state: AgentState) -> dict[str, Any]:
        disclaimer = deps.cfg.settings.disclaimer
        analysis = state.get("holdings_analysis")
        if analysis is None or not analysis.positions:
            text = CLARIFICATION
            if analysis is not None and analysis.notes:
                text = " ".join(analysis.notes) + " " + CLARIFICATION
            answer = Narrative(
                paragraphs=[
                    Paragraph(mode="notice", text=text),
                    Paragraph(mode="notice", text=disclaimer),
                ]
            )
            return {
                "answer": answer,
                "citations": [],
                "sources": [],
                "retrievals": [],
                "explain_payload": {"holdings": {"clarification": text}, "disclaimer": disclaimer},
            }
        sources: list[Chunk] = []
        retrievals: list[RetrievalResult] = []
        try:
            retriever = deps.knowledge()
            for q in _QUERIES:
                result = retriever.retrieve(q, kind="basics", top_k=2)
                retrievals.append(result)
                for hit in result.hits:
                    if all(c.doc_id != hit.chunk.doc_id for c in sources):
                        sources.append(hit.chunk)
                        break
        except Exception:  # citations are a convenience here, never a blocker
            sources = []
        payload = holdings_payload(analysis, disclaimer)
        payload["sources"] = sources_payload(sources)
        answer = holdings_narrative(payload, sources, disclaimer)
        return {
            "answer": answer,
            "citations": resolve_citations(answer, [citation_of(c) for c in sources]),
            "sources": sources,
            "retrievals": retrievals,
            "explain_payload": payload,
        }

    return holdings_reply_node
