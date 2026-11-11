"""goal_explainer_node (Goal Planning, Phase 12 step 12.3): the cited narrative of a GoalPlan.

Retrieves the concept documents the plan rests on (compound growth, the profile's return cap, the
4% rule, the savings-rate relationship) from the knowledge base, builds a payload of rounded
numbers from the computed plan, and asks the LLM (``explain_goal``) or the rule-based stand-in to
write tagged paragraphs. A clarification (the goal could not be planned) is returned as a notice
without calling the LLM. The text reaches the user only through Compliance (check 9 applies).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.explainer import render_sources_block, rule_prompt, sources_payload
from options_scout.agent.state import AgentState
from options_scout.core.compliance import resolve_citations
from options_scout.core.models import GoalPlan, Narrative, Paragraph
from options_scout.llm.rules import rule_explain_goal
from options_scout.rag.models import Chunk, RetrievalResult, citation_of

STATUS_TEXT = {"fits": "fits", "stretch": "stretch", "does_not_fit": "does not fit"}
MAX_SOURCES = 4

_QUERIES_ALL = [
    "compound growth with regular monthly contributions",
    "how the risk profile caps the return a goal can assume",
]
_QUERIES_BY_KIND = {
    "income": ["why reinvested option premium is not a bond coupon"],
    "fire": [
        "the 4% rule and the Trinity study safe withdrawal rate",
        "why safe withdrawal research does not transfer to options premium income",
        "savings rate and years to financial independence",
    ],
}


def _pct(x: float | None, digits: int = 1) -> float | None:
    return None if x is None else round(x * 100, digits)


def _money(x: float | None) -> int | None:
    return None if x is None else round(x)


def goal_payload(plan: GoalPlan, disclaimer: str, risk_profile: str) -> dict[str, Any]:
    """Rounded numbers the narrative may quote; every value here is grounded by construction."""
    g, v, y = plan.goal, plan.feasibility, plan.yield_estimate
    years = plan.projection[0].points[-1].year if plan.projection else None
    last = {p.label: _money(p.points[-1].balance) for p in plan.projection}
    payload: dict[str, Any] = {
        "goal_plan": {
            "goal": {
                "kind": g.kind,
                "variant": g.variant,
                "risk_profile": risk_profile,
                "start_balance": _money(g.start_balance),
                "monthly_contribution": _money(g.monthly_contribution),
                "target_monthly_income": _money(g.target_monthly_income),
                "target_balance": _money(g.target_balance),
                "horizon_years": None if g.horizon_years is None else round(g.horizon_years, 1),
                "annual_expenses": _money(g.annual_expenses),
                "current_age": g.current_age,
                "target_age": g.target_age,
            },
            "status": v.status,
            "status_text": STATUS_TEXT[v.status],
            "required_return_pct": _pct(v.required_return),
            "available_return_pct": _pct(v.available_return),
            "profile_cap_pct": _pct(v.profile_cap, 0),
            "gap_pct": _pct(v.gap),
            "levers": [lever.detail for lever in v.levers],
            "lever_values": {lever.name: lever.value for lever in v.levers},
            "notes": v.notes,
            "yield": {
                "gross_pct": _pct(y.gross_yield),
                "expected_pct": _pct(y.expected_yield),
                "expected_drift_pct": _pct(y.expected_drift, 0),
                "realised_to_implied": round(y.realised_to_implied, 2),
                "cash_rate_pct": _pct(y.cash_rate, 2),
                "realistic_loss": _money(y.realistic_loss),
                "total_capital": _money(y.total_capital),
            },
            "projection": {
                "years": years,
                "stress_drop_pct": 30,
                "stress": last.get("stress"),
                "base": last.get("base"),
                "best": last.get("best"),
                "assumed": last.get("assumed"),
                # W21: the real rate the assumed path compounds at (balances in today's dollars)
                "assumed_real_return_pct": _pct(
                    next((p.annual_return for p in plan.projection if p.label == "assumed"), None),
                ),
            },
            "assumptions": plan.assumptions,
        },
        "disclaimer": disclaimer,
    }
    if plan.fire is not None:
        f = plan.fire
        payload["goal_plan"]["fire"] = {
            "variant": f.variant,
            "expense_target": _money(f.expense_target),
            "withdrawal_rate_pct": _pct(f.withdrawal_rate),
            "fire_number": _money(f.fire_number),
            "assumed_return_pct": _pct(f.assumed_return, 0),
            "real_return_pct": _pct(f.real_return),
            "inflation_pct": _pct(f.inflation),
            "years_to_fi": None if f.years_to_fi is None else round(f.years_to_fi, 1),
            "coast_balance": _money(f.coast_balance),
            "savings_rate_pct": _pct(f.savings_rate, 0),
            "income_coverage_pct": _pct(f.income_coverage, 0),
            "buying_power_for_full_coverage": _money(f.buying_power_for_full_coverage),
            "targets": {k: _money(val) for k, val in f.targets.items()},
            "notes": f.notes,
        }
    return payload


def goal_sources(deps: Deps, plan: GoalPlan) -> tuple[list[Chunk], list[RetrievalResult]]:
    """One chunk per document for the concepts the plan rests on, basics collection first."""
    retriever = deps.knowledge()
    queries = [*_QUERIES_ALL, *_QUERIES_BY_KIND.get(plan.goal.kind, [])]
    chosen: list[Chunk] = []
    results: list[RetrievalResult] = []
    seen_docs: set[str] = set()
    for q in queries:
        result = retriever.retrieve(q, kind="basics", top_k=3)
        results.append(result)
        for hit in result.hits:
            if hit.chunk.doc_id not in seen_docs:
                seen_docs.add(hit.chunk.doc_id)
                chosen.append(hit.chunk)
                break
        if len(chosen) >= MAX_SOURCES:
            break
    return chosen, results


def clarification_answer(text: str, disclaimer: str) -> Narrative:
    return Narrative(
        paragraphs=[Paragraph(mode="notice", text=text), Paragraph(mode="notice", text=disclaimer)]
    )


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def goal_explainer_node(state: AgentState) -> dict[str, Any]:
        disclaimer = deps.cfg.settings.disclaimer
        plan = state.get("goal_plan")
        clarification = state.get("goal_clarification")
        errors: list[str] = []
        usage_before = len(deps.llm.usage)
        if plan is None:
            text = clarification or "I could not build a goal plan from that message."
            return {
                "answer": clarification_answer(text, disclaimer),
                "citations": [],
                "sources": [],
                "retrievals": [],
                "explain_payload": {"goal_plan": {"clarification": text}, "disclaimer": disclaimer},
                "token_usage": [],
                "errors": errors,
            }
        profile = state.get("profile")
        risk_profile = profile.risk_profile if profile is not None else "balanced"
        try:
            sources, retrievals = goal_sources(deps, plan)
        except Exception as exc:  # retrieval is a convenience for citations, never a blocker
            errors.append(f"goal_explainer: retrieval failed ({exc})")
            sources, retrievals = [], []
        payload = goal_payload(plan, disclaimer, risk_profile)
        payload["sources"] = sources_payload(sources)
        feedback = state.get("verifier_feedback")
        if feedback:
            payload["previous_attempt_problems"] = feedback
        block = render_sources_block(sources)
        try:
            answer: Narrative = deps.llm.explain_goal(payload, block, disclaimer)
        except Exception as exc:
            errors.append(f"goal_explainer: LLM failed ({exc}); using the deterministic narrative")
            answer = rule_explain_goal(
                f"copied exactly: {disclaimer}\n" + rule_prompt(payload, block)
            )
        citations = resolve_citations(answer, [citation_of(c) for c in sources])
        return {
            "answer": answer,
            "citations": citations,
            "sources": sources,
            "retrievals": retrievals,
            "explain_payload": payload,
            "token_usage": deps.llm.usage[usage_before:],
            "errors": errors,
        }

    return goal_explainer_node
