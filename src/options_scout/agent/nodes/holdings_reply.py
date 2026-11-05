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
            "beta_weighted_exposure": (
                None if a.beta_weighted_exposure is None else round(a.beta_weighted_exposure, 2)
            ),
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
                }
                for x in a.post_assignment
            ],
            "notes": a.notes,
        },
        "disclaimer": disclaimer,
    }


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
                f"(HHI {h['hhi']}, about {h['effective_positions']} effective positions)."
            ),
        )
    )
    extras: list[str] = []
    if h["weighted_expense_ratio_pct"] is not None:
        er = h["weighted_expense_ratio_pct"]
        extras.append(f"the ETFs carry a weighted expense ratio of {er}% a year")
    if h["beta_weighted_exposure"] is not None:
        extras.append(f"beta-weighted exposure to the index is {h['beta_weighted_exposure']}")
    if h["covered_call_eligible"]:
        extras.append(
            "lots of 100 shares that could write a covered call: "
            + ", ".join(h["covered_call_eligible"])
        )
    if extras:
        paras.append(Paragraph(mode="screen_result", text="; ".join(extras).capitalize() + "."))
    if h["post_assignment"]:
        rows = "; ".join(
            f"the {x['ticker']} {x['strike']:g} put would take {x['ticker']} from "
            f"{x['weight_before_pct']}% to {x['weight_after_pct']}% of holdings plus buying power"
            for x in h["post_assignment"][:5]
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
