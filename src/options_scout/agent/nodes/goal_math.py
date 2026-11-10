"""goal_math_node (Goal Planning, Phase 12 step 12.3): ``core.goals.plan_goal`` on the thread.

The sized portfolio and candidates of the thread's report give the yield; without a report the
whole balance sits in cash at the T-bill rate and the plan says so. Nothing here calls an LLM.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core import goals
from options_scout.core.models import (
    Goal,
    PortfolioTotals,
    SizedPortfolio,
    UserProfile,
)


def cash_only_portfolio(cash: float) -> SizedPortfolio:
    totals = PortfolioTotals(
        short_put_notional=0.0,
        capital_used=0.0,
        margin_used=0.0,
        leaps_cost=0.0,
        realistic_loss=0.0,
        dollar_delta=0.0,
        premium_income=0.0,
        cash_reserve=max(cash, 0.0),
        buying_power_used_pct=0.0,
    )
    return SizedPortfolio(positions=[], totals=totals, skipped=[])


def default_profile(goal: Goal) -> UserProfile:
    balance = max(goal.start_balance, 1.0)
    return UserProfile(
        buying_power=balance, account_value=balance, account_type="cash", risk_profile="balanced"
    )


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def goal_math_node(state: AgentState) -> dict[str, Any]:
        goal = state.get("goal")
        if goal is None:
            return {}
        profile = state.get("profile")
        notes: list[str] = []
        if profile is None:
            profile = default_profile(goal)
            notes.append("no profile on this thread: a balanced cash profile is assumed")
        portfolio = state.get("portfolio")
        if portfolio is None:
            portfolio = cash_only_portfolio(goal.start_balance or profile.buying_power)
            rep = state.get("report")
            if rep is not None and rep.withheld:
                notes.append(
                    "this thread's screen was withheld, so its positions are not used: the "
                    "balance is treated as cash at the T-bill rate"
                )
            else:
                notes.append(
                    "no screen on this thread: the balance is treated as cash at the T-bill "
                    "rate; run a screen to see what the current candidates would yield"
                )
        regime = state.get("regime")
        try:
            if regime is not None:
                cash_rate = regime.risk_free_rate
            else:
                cash_rate = deps.md.get_risk_free_rate()
        except Exception as exc:  # the rate is a cash-reserve assumption, never a blocker
            cash_rate = 0.0
            notes.append(f"risk-free rate unavailable ({type(exc).__name__}); cash counted at 0%")
        candidates = {c.id: c for c in state.get("candidates") or []}
        plan = goals.plan_goal(goal, profile, portfolio, candidates, cash_rate, deps.cfg.goals)
        if notes:
            plan = plan.model_copy(update={"assumptions": [*plan.assumptions, *notes]})
        return {"goal_plan": plan}

    return goal_math_node
