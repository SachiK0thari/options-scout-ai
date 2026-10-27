"""explainer_node: narrative written ONLY from a compact payload of computed numbers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.llm.rules import rule_explain


def _money(x: float | None) -> int | None:
    return None if x is None else round(x)


def build_explain_payload(
    state: AgentState, disclaimer: str, *, loss_drop: float = 0.30
) -> dict[str, Any]:
    profile, regime, alloc = state["profile"], state["regime"], state["allocation"]
    portfolio, risk = state["portfolio"], state["risk"]
    assert profile and regime and alloc and portfolio and risk
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
            "warnings": risk.warnings,
        },
        "errors": state.get("errors", [])[:8],
        "disclaimer": disclaimer,
    }
    return payload


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def explainer_node(state: AgentState) -> dict[str, Any]:
        payload = build_explain_payload(
            state, deps.cfg.settings.disclaimer, loss_drop=deps.cfg.risk.realistic_loss_drop
        )
        feedback = state.get("verifier_feedback")
        if feedback:
            payload["previous_attempt_problems"] = feedback
        usage_before = len(deps.llm.usage)
        errors: list[str] = []
        try:
            narrative = deps.llm.explain(payload)
        except Exception as exc:
            errors.append(f"explainer: LLM failed ({exc}); using deterministic narrative")
            narrative = rule_explain(f"<payload>\n{_json(payload)}\n</payload>").text
        return {
            "narrative": narrative,
            "explain_payload": payload,
            "token_usage": deps.llm.usage[usage_before:],
            "errors": errors,
        }

    return explainer_node


def _json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=1, sort_keys=True, default=str)
