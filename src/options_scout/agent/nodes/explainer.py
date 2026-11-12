"""explainer_node: narrative written ONLY from a compact payload of computed numbers.

Phase 10 step 10.3: the narrative is a ``Narrative`` of tagged paragraphs; the retrieved
``sources`` are rendered as an ``[S1]…[Sn]`` block the LLM must cite, and they are also copied
into the payload so a number quoted from a source counts as grounded. Each sized position gets
a payoff summary (breakeven, maximum loss) from ``core/payoff.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from html import escape
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.knowledge_retrieval import audience_for
from options_scout.agent.state import AgentState
from options_scout.core import payoff
from options_scout.core.compliance import resolve_citations
from options_scout.core.grounding import add_missing_realistic_losses, render_narrative
from options_scout.core.models import (
    BottleneckSignal,
    Narrative,
    OptionCandidate,
    PMCCCandidate,
    SizedPortfolio,
    SizedPosition,
)
from options_scout.core.screeners import BOTTLENECK_FLAGS
from options_scout.llm.rules import rule_explain
from options_scout.rag.models import Chunk, citation_of


def _money(x: float | None) -> int | None:
    return None if x is None else round(x)


SKIPPED_IN_PAYLOAD = 8  # the best-ranked skipped candidates sent to the explainer


def skipped_candidates_payload(
    portfolio: SizedPortfolio, warnings: Sequence[str]
) -> list[dict[str, Any]]:
    """The best-ranked size-limited skips, plus any a warning names, with the realistic loss of
    one contract (``SkipDetail.per_contract_loss``) and the account size it would fit from."""
    named = {
        d.candidate_id
        for d in portfolio.skipped_detail
        if any(d.candidate_id in w for w in warnings)
    }
    ordered = sorted(portfolio.skipped_detail, key=lambda d: d.rank)
    chosen = [d for d in ordered if d.candidate_id in named]
    chosen += [d for d in ordered if d.candidate_id not in named][
        : max(SKIPPED_IN_PAYLOAD - len(chosen), 0)
    ]
    return [
        {
            "candidate_id": d.candidate_id,
            "rank": d.rank,
            "reason": d.reason,
            "realistic_loss_per_contract": _money(d.per_contract_loss),
            "fits_from_account": _money(d.min_account_value),
        }
        for d in sorted(chosen, key=lambda d: d.rank)
    ]


def _pct(x: float | None) -> int | None:
    return None if x is None else round(x * 100)


def _quality_section(state: AgentState) -> dict[str, Any]:
    checks = list((state.get("quality") or {}).values())
    passed = sorted((q for q in checks if q.passed), key=lambda q: -q.score)
    failed = [q for q in checks if not q.passed]
    return {
        "passed_count": len(passed),
        "excluded_count": len(failed),
        "drawdown_lookback_days": 90,
        # W14: plain names for the `list` slot filter (`passed` and `excluded` hold records)
        "passed_tickers": [q.ticker for q in passed],
        "excluded_tickers": [q.ticker for q in failed],
        "passed": [
            {
                "ticker": q.ticker,
                "name": q.name,
                "quality_score": round(q.score * 100),
                "hv30_pct": _pct(q.metrics.get("hv30")),
                "below_90d_high_pct": _pct(q.metrics.get("drawdown_90d")),
                "curated": q.curated,
                "why": q.why_good_to_own,
            }
            for q in passed
        ],
        "excluded": [{"ticker": q.ticker, "reasons": q.reasons} for q in failed],
    }


def bottleneck_section(signals: Sequence[BottleneckSignal]) -> dict[str, Any]:
    """The board as the explainer may describe it (Phase 11): every layer with its integer score
    and thesis state, the curated suppliers with their company score, layer and flags. Numbers
    are rounded here exactly as the rule-based narrative quotes them."""
    layers = sorted((s for s in signals if s.ticker is None), key=lambda s: -s.score)
    best: dict[str, BottleneckSignal] = {}
    for s in signals:
        t = s.ticker or ""
        scored = bool(t) and s.role == "supplier" and s.curated
        if scored and (t not in best or s.score > best[t].score):
            best[t] = s
    return {
        "note": "secondary signal: re-orders quality-gated stocks, never adds one",
        "layers": [
            {
                "layer": f"{s.theme_id}/{s.layer_id}",
                "name": s.layer_name,
                "score": round(s.score),
                "thesis_state": "weakening" if s.thesis_weakening else "holding",
            }
            for s in layers
        ],
        "companies": [
            {
                "ticker": t,
                "score": round(s.score),
                "layer": f"{s.theme_id}/{s.layer_id}",
                "flags": s.flags,
            }
            for t, s in sorted(best.items(), key=lambda kv: -kv[1].score)
        ],
    }


def position_payoff(
    pos: SizedPosition,
    candidates: dict[str, OptionCandidate],
    pairs_by_short_call: dict[str, PMCCCandidate],
) -> dict[str, Any]:
    """Breakeven / max loss / max gain at expiry for one sized position (``core/payoff.py``)."""
    cand = candidates.get(pos.candidate_id)
    spot = cand.spot if cand else None
    basis = "at expiry"
    if pos.strategy == "csp":
        legs = payoff.csp_legs(pos.strike, pos.mid, pos.contracts)
    elif pos.pmcc_short_call_id and pos.pmcc_short_call_id in pairs_by_short_call:
        pair = pairs_by_short_call[pos.pmcc_short_call_id]
        legs = payoff.pmcc_legs(
            pos.strike, pos.mid, pair.short_call.strike, pair.short_call.mid, pos.contracts
        )
        basis = "at the short call's expiry, LEAPS valued at intrinsic"
    else:
        legs = payoff.long_call_legs(pos.strike, pos.mid, pos.contracts)
    summary = payoff.summarize_strategy(legs, spot)
    return {
        "breakeven": round(summary.breakevens[0], 2) if summary.breakevens else None,
        "max_loss": _money(summary.max_loss),
        "max_gain": _money(summary.max_gain) if summary.max_gain is not None else None,
        "basis": basis,
    }


def sources_payload(sources: Sequence[Chunk]) -> list[dict[str, str]]:
    return [
        {"tag": f"S{i}", "title": c.title, "url": c.url, "kind": c.kind, "text": c.text}
        for i, c in enumerate(sources, start=1)
    ]


def render_sources_block(sources: Sequence[Chunk]) -> str:
    """The numbered ``<source id="Sn" …>`` block handed to the prompts (and parsed by the
    rule-based stand-ins). Text, title and url are HTML-escaped, so retrieved text (a social
    post, a headline) can neither close its own block nor open a forged one (W13); the kind is
    assigned by this app, and ``run`` marks the facts it computed."""
    parts = []
    for i, c in enumerate(sources, start=1):
        title = escape(c.title, quote=True)
        url = escape(c.url, quote=True)
        text = escape(c.text, quote=False)
        parts.append(
            f'<source id="S{i}" title="{title}" url="{url}" kind="{c.kind}">\n{text}\n</source>'
        )
    return "\n".join(parts)


def rule_prompt(payload: dict[str, Any], sources_block: str) -> str:
    """What the rule-based explainer parses: the same blocks the LLM prompt carries."""
    return f"<sources>\n{sources_block}\n</sources>\n\n<payload>\n{_json(payload)}\n</payload>"


def build_explain_payload(
    state: AgentState,
    disclaimer: str,
    *,
    loss_drop: float = 0.30,
    sources: Sequence[Chunk] | None = None,
) -> dict[str, Any]:
    profile, regime, alloc = state["profile"], state["regime"], state["allocation"]
    portfolio, risk = state["portfolio"], state["risk"]
    assert profile and regime and alloc and portfolio and risk
    candidates = {c.id: c for c in state.get("candidates", [])}
    pairs = {p.short_call.id: p for p in state.get("pmcc_pairs", [])}
    payload: dict[str, Any] = {
        "profile": {
            "buying_power": _money(profile.buying_power),
            "account_value": _money(profile.account_value),
            "account_type": profile.account_type,
            "risk_profile": profile.risk_profile,
            "strategies": sorted(profile.strategies),
        },
        "regime": {
            "vix": round(regime.vix, 2),
            "vix_percentile": round(regime.vix_percentile),
            "label": regime.label,
            "risk_free_rate_pct": round(regime.risk_free_rate * 100, 2),
        },
        "allocation": {
            "csp_pct": round(alloc.csp_pct * 100),
            "leaps_pct": round(alloc.leaps_pct * 100),
            "cash_pct": round(alloc.cash_pct * 100),
            "csp_dollars": _money(alloc.csp_dollars),
            "leaps_dollars": _money(alloc.leaps_dollars),
            "cash_dollars": _money(alloc.cash_dollars),
            "tilt": alloc.tilt,
        },
        "trends": [
            {
                "entity": t.entity,
                "ticker": t.ticker,
                "investable": t.investable,
                "score": round(t.score),
                "velocity_z": round(t.components.get("velocity_z", 0.0), 1),
                "coverage_gap": round(t.components.get("coverage_gap", 0.0), 1),
                "flags": t.flags,
            }
            for t in state.get("trends", [])[:5]
        ],
        "universe": state.get("universe", []),
        "quality_screen": _quality_section(state),
        "positions": [
            {
                "candidate_id": p.candidate_id,
                "strategy": p.strategy,
                "ticker": p.ticker,
                "contracts": p.contracts,
                "strike": p.strike,
                "expiry": p.expiry.isoformat(),
                "mid": round(p.mid, 2),
                "capital_used": _money(p.capital_used),
                "margin_used": _money(p.margin_used),
                "realistic_loss": _money(p.realistic_loss),
                "dollar_delta": _money(p.dollar_delta),
                "premium": _money(p.premium),
                "pmcc_short_call_id": p.pmcc_short_call_id,
                "payoff": position_payoff(p, candidates, pairs),
                "bottleneck_flags": [
                    f
                    for f in (
                        candidates[p.candidate_id].flags if p.candidate_id in candidates else []
                    )
                    if f in BOTTLENECK_FLAGS
                ],
                # W5: the position or its short call has no confirmed earnings date
                "earnings_unknown": any(
                    "earnings_unknown" in c.flags
                    for c in (
                        candidates.get(p.candidate_id),
                        pairs[p.pmcc_short_call_id].short_call
                        if p.pmcc_short_call_id in pairs
                        else None,
                    )
                    if c is not None
                ),
            }
            for p in portfolio.positions
        ],
        "portfolio": {
            "short_put_notional": _money(portfolio.totals.short_put_notional),
            "capital_used": _money(portfolio.totals.capital_used),
            "margin_used": _money(portfolio.totals.margin_used),
            "realistic_loss": _money(portfolio.totals.realistic_loss),
            "dollar_delta": _money(portfolio.totals.dollar_delta),
            "premium_income": _money(portfolio.totals.premium_income),
            "cash_reserve": _money(portfolio.totals.cash_reserve),
            "skipped_count": len(portfolio.skipped),
        },
        # W11: candidates that did not fit, with the realistic loss of one contract, so a
        # paragraph that names one (the sizing warnings do) can state its downside
        "skipped_candidates": skipped_candidates_payload(portfolio, risk.warnings),
        "risk": {
            "passed": risk.passed,
            "checks_passed": sum(1 for c in risk.checks if c.passed),
            "checks_total": len(risk.checks),
            "realistic_loss_drop_pct": round(loss_drop * 100),
            "checks": [
                {"name": c.name, "value": round(c.value, 3), "limit": c.limit, "passed": c.passed}
                for c in risk.checks
            ],
            "stress": [
                {
                    "shock": f"{round(s.shock * 100)}%",
                    "iv_shock": f"+{round(s.iv_shock * 100)}%",
                    "pnl": _money(s.pnl),
                }
                for s in risk.stress
            ],
            "warnings": risk.warnings,  # W6: the sizing warnings come first
            "sizing_flags": risk.sizing_flags,
        },
        "errors": state.get("errors", [])[:8],
        "disclaimer": disclaimer,
    }
    # W14: ready-made counts, so the writer slots a count instead of working it out
    payload["counts"] = {
        "positions_sized": len(payload["positions"]),
        "skipped_total": len(portfolio.skipped),
        "skipped_listed": len(payload["skipped_candidates"]),
        "warnings": len(risk.warnings),
        "underlyings_screened": len(payload["universe"]),
        "quality_passed": payload["quality_screen"]["passed_count"],
        "quality_excluded": payload["quality_screen"]["excluded_count"],
    }
    if state.get("bottlenecks"):  # Phase 11: the board, when the engine produced one
        payload["bottlenecks"] = bottleneck_section(list(state["bottlenecks"]))
    plan = state.get("goal_plan")
    if plan is not None:  # Phase 12: a screen seeded with a goal
        from options_scout.agent.nodes.goal_explainer import goal_payload

        payload["goal_plan"] = goal_payload(plan, disclaimer, profile.risk_profile)["goal_plan"]
    if sources is not None:
        payload["sources"] = sources_payload(sources)
    return payload


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def explainer_node(state: AgentState) -> dict[str, Any]:
        sources = list(state.get("sources") or [])
        payload = build_explain_payload(
            state,
            deps.cfg.settings.disclaimer,
            loss_drop=deps.cfg.risk.realistic_loss_drop,
            sources=sources,
        )
        feedback = state.get("verifier_feedback")
        if feedback:
            payload["previous_attempt_problems"] = feedback
        block = render_sources_block(sources)
        usage_before = len(deps.llm.usage)
        errors: list[str] = []
        source = "model" if deps.llm.is_live else "fixture"
        try:
            narrative: Narrative = deps.llm.explain(
                payload, block, audience=audience_for(state.get("profile"))
            )
        except Exception as exc:
            errors.append(f"explainer: LLM failed ({exc}); using deterministic narrative")
            narrative = rule_explain(rule_prompt(payload, block))
            source = "rules"
        # W14: the writer names payload fields as {{slots}}; Python fills them and each paragraph
        # keeps its template, so the Compliance agent can tell filled figures from typed ones
        # a short option named without its realistic loss gets that slot added (the figure still
        # comes from the payload); the report records the repair
        narrative, patches = add_missing_realistic_losses(narrative, payload)
        narrative = render_narrative(narrative, payload)
        citations = resolve_citations(narrative, [citation_of(c) for c in sources])
        return {
            "narrative": narrative,
            "narrative_source": source,
            "narrative_patches": patches,
            "citations": citations,
            "explain_payload": payload,
            "token_usage": deps.llm.usage[usage_before:],
            "errors": errors,
        }

    return explainer_node


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=1, sort_keys=True, default=str)
