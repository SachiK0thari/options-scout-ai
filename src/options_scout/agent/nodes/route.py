"""route_node (Orchestrator, step 10.5): classify the turn and prepare the state for its path.

* A thread started from a request or a profile (no chat ``message``) is a ``new_screen``.
* An explicit ``question`` (CLI ``--ask``) is a ``concept`` question, or ``why`` when the message
  reads like one and a report exists.
* A chat ``message`` goes through the ``route_message`` prompt (or the regex fallback) with the
  thread's context: whether a report exists and the current profile.

The node writes ``intent`` and, per intent: ``question`` (concept/why), ``what_if_profile``
(what_if), or a ``handoff`` describing the new thread the session must start (a new or refined
screen requested on a thread that already holds a report; LangGraph's list reducers would otherwise
append a second run onto the first).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.models import Intent, UserProfile
from options_scout.llm.rules import rule_route

PROFILE_KEYS = (
    "buying_power",
    "account_value",
    "account_type",
    "risk_profile",
    "strategies",
    "watchlist",
    "exclude",
    "max_positions",
)


def profile_summary(profile: UserProfile | None) -> str:
    if profile is None:
        return "none"
    return (
        f"buying power {profile.buying_power:,.0f}, {profile.account_type} account, "
        f"{profile.risk_profile}, strategies {sorted(profile.strategies)}"
    )


def apply_changes(profile: UserProfile | None, changes: dict[str, Any]) -> dict[str, Any]:
    """The current profile as a dict with the router's ``profile_changes`` applied."""
    base: dict[str, Any] = profile.model_dump(mode="json") if profile else {}
    for key in PROFILE_KEYS:
        if key in changes and changes[key] is not None:
            base[key] = changes[key]
    if "buying_power" in changes and "account_value" not in changes:
        base["account_value"] = changes["buying_power"]
    if "strategies" in base and isinstance(base["strategies"], set | list | tuple):
        base["strategies"] = sorted(base["strategies"])
    return base


def profile_diff(before: UserProfile | None, after: dict[str, Any]) -> list[str]:
    out: list[str] = []
    old = before.model_dump(mode="json") if before else {}
    for key in PROFILE_KEYS:
        a, b = old.get(key), after.get(key)
        if isinstance(a, list | set):
            a = sorted(a)
        if isinstance(b, list | set):
            b = sorted(b)
        if a != b and (a is not None or b is not None):
            fmt = (lambda v: f"{v:,.0f}") if key in ("buying_power", "account_value") else str
            out.append(
                f"{key.replace('_', ' ')}: {fmt(a) if a is not None else 'unset'} → "
                f"{fmt(b) if b is not None else 'unset'}"
            )
    return out


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def route_node(state: AgentState) -> dict[str, Any]:
        message = (state.get("message") or "").strip()
        question = (state.get("question") or "").strip()
        has_report = state.get("report") is not None
        profile = state.get("profile")
        errors: list[str] = []
        usage_before = len(deps.llm.usage)

        if not message:
            if question:
                decision = rule_route(f"<message>\n{question}\n</message>")
                intent: Intent = "why" if (decision.intent == "why" and has_report) else "concept"
                return {"intent": intent, "question": question, "handoff": None}
            return {"intent": "new_screen", "handoff": None}

        try:
            decision = deps.llm.route_message(
                message, has_report=has_report, profile=profile_summary(profile)
            )
        except Exception as exc:
            errors.append(f"route: LLM router failed ({exc}); using the rule-based router")
            decision = rule_route(
                f"<message>\n{message}\n</message>\n"
                f"Context: a report {'exists' if has_report else 'does not exist yet'}"
            )
        intent = decision.intent
        if intent == "why" and not has_report:
            intent = "concept"
        if intent in ("refine_profile", "what_if") and not has_report:
            intent = "new_screen"
        out: dict[str, Any] = {
            "intent": intent,
            "handoff": None,
            "errors": errors,
            "token_usage": deps.llm.usage[usage_before:],
        }
        if intent in ("concept", "why"):
            out["question"] = decision.question or message
        elif intent == "what_if":
            proposed = apply_changes(profile, decision.profile_changes)
            try:
                UserProfile.model_validate(proposed)
            except ValidationError as exc:
                out["intent"] = "off_topic"
                out["errors"] = [*errors, f"route: what-if profile invalid ({exc})"]
                return out
            out["what_if_profile"] = proposed
            out["what_if_diff"] = profile_diff(profile, proposed)
        elif intent == "off_topic":
            pass  # redirect_node writes the fixed reply
        elif has_report:  # new_screen / refine_profile on a thread that already ran
            proposed = apply_changes(profile, decision.profile_changes)
            out["handoff"] = {
                "intent": intent,
                "request_text": message if intent == "new_screen" else "",
                "profile": proposed if intent == "refine_profile" else None,
                "review_requested": intent == "refine_profile",
                "diff": profile_diff(profile, proposed) if intent == "refine_profile" else [],
            }
        else:  # first turn of a thread: the message is the request
            out["request_text"] = message
        return out

    return route_node


def route_after_route(state: AgentState) -> str:
    """Inside the Orchestrator: continue to intake, to the what-if / redirect writers, or end."""
    intent = state.get("intent") or "new_screen"
    if intent in ("new_screen", "refine_profile"):
        return "__end__" if state.get("handoff") else "intake_node"
    if intent == "what_if":
        return "what_if_node"
    if intent == "off_topic":
        return "redirect_node"
    return "__end__"  # concept / why: the Education agent takes over
