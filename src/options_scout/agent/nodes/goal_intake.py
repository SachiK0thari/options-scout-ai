"""goal_intake_node (Goal Planning, Phase 12 step 12.3): turn the chat turn into a ``Goal``.

The LLM (``parse_goal``) or the regex stand-in extracts the figures; this node decides what is
missing. A goal that cannot be planned (no kind, a FIRE goal without expenses, a growth goal
without a horizon) produces a ``goal_clarification`` sentence instead of a plan, which the
explainer returns as a notice. Numbers are never invented: the start balance comes from the
profile when the message did not state one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.route import profile_summary
from options_scout.agent.state import AgentState
from options_scout.core.models import FireVariant, Goal, GoalParse
from options_scout.llm.rules import rule_parse_goal

EXAMPLES = (
    "'I want $400 a month from this account', 'grow 40k to 55k in three years' or "
    "'I spend 48k a year and have 220k, when could I lean FIRE'"
)


def clarification_for(parsed: GoalParse, start_balance: float) -> str | None:
    """What a plan cannot do without, as one sentence for the user; None when complete."""
    if parsed.kind is None:
        return f"I could not tell what the goal is. Say, for example, {EXAMPLES}."
    if parsed.kind == "fire" and parsed.annual_expenses is None and parsed.minimum_expenses is None:
        return (
            "A FIRE plan needs your annual expenses (for example 'I spend 48k a year'); the FIRE "
            "number is those expenses divided by the withdrawal rate."
        )
    if parsed.kind in ("growth", "contribution") and parsed.target_balance is None:
        return "A growth goal needs the balance to reach, for example 'grow it to 55k'."
    if parsed.kind in ("growth", "contribution") and not (
        parsed.horizon_years or (parsed.target_age and parsed.current_age)
    ):
        return (
            "A growth goal needs a horizon: a number of years ('in 5 years') or a target age with "
            "your current age ('I'm 35, by 50')."
        )
    if parsed.kind == "income" and parsed.target_monthly_income is None:
        return "An income goal needs the amount per month, for example '$400 a month'."
    if start_balance <= 0 and parsed.kind != "fire":
        return (
            "I need a starting balance: run a screen first or say how much the account holds, "
            "for example 'I have 60k'."
        )
    return None


def goal_from(parsed: GoalParse, start_balance: float) -> Goal:
    variant: FireVariant | None = parsed.variant
    if parsed.kind == "fire" and variant is None:
        variant = "regular"
    expenses = parsed.annual_expenses
    if parsed.kind == "fire" and expenses is None:
        expenses = parsed.minimum_expenses
    return Goal(
        kind=parsed.kind or "growth",
        start_balance=start_balance,
        monthly_contribution=parsed.monthly_contribution or 0.0,
        target_monthly_income=parsed.target_monthly_income,
        target_balance=parsed.target_balance,
        horizon_years=parsed.horizon_years,
        variant=variant,
        annual_expenses=expenses,
        minimum_expenses=parsed.minimum_expenses,
        fat_expenses=parsed.fat_expenses,
        part_time_income=parsed.part_time_income or 0.0,
        withdrawal_rate=parsed.withdrawal_rate,
        current_age=parsed.current_age,
        target_age=parsed.target_age,
    )


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def goal_intake_node(state: AgentState) -> dict[str, Any]:
        text = (state.get("goal_text") or state.get("message") or "").strip()
        profile = state.get("profile")
        errors: list[str] = []
        usage_before = len(deps.llm.usage)
        try:
            parsed = deps.llm.parse_goal(text, profile_summary(profile))
        except Exception as exc:
            errors.append(f"goal_intake: LLM parser failed ({exc}); using the rule-based parser")
            parsed = rule_parse_goal(f"<message>\n{text}\n</message>")
        start = parsed.start_balance
        if start is None:
            start = profile.account_value if profile is not None else 0.0
        clarification = clarification_for(parsed, start)
        goal: Goal | None = None
        if clarification is None:
            try:
                goal = goal_from(parsed, start)
            except ValidationError as exc:
                clarification = (
                    f"I could not build a plan from those figures ({exc.error_count()} invalid)."
                )
                errors.append(f"goal_intake: invalid goal ({exc})")
        return {
            "goal": goal,
            "goal_clarification": clarification,
            "goal_plan": None,
            "token_usage": deps.llm.usage[usage_before:],
            "errors": errors,
        }

    return goal_intake_node
