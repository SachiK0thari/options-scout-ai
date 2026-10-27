"""intake_node: free text (or a UI-supplied profile) → UserProfile, or route to human review."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.models import ProfileParse, UserProfile

REQUIRED = ("buying_power", "account_type", "risk_profile")


def profile_from_parse(
    parsed: ProfileParse, override: dict[str, Any] | None = None
) -> UserProfile | None:
    data: dict[str, Any] = {
        "buying_power": parsed.buying_power,
        "account_value": parsed.account_value or parsed.buying_power,
        "account_type": parsed.account_type,
        "risk_profile": parsed.risk_profile,
        "watchlist": parsed.watchlist,
        "exclude": parsed.exclude,
    }
    if parsed.strategies:
        data["strategies"] = set(parsed.strategies)
    if parsed.max_positions:
        data["max_positions"] = parsed.max_positions
    for k, v in (override or {}).items():
        if v is not None:
            data[k] = v
    if any(data.get(k) is None for k in REQUIRED):
        return None
    try:
        return UserProfile.model_validate(data)
    except ValidationError:
        return None


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def intake_node(state: AgentState) -> dict[str, Any]:
        override = state.get("profile_override") or None
        text = state.get("request_text", "") or ""
        parsed = state.get("parsed")
        usage_before = len(deps.llm.usage)
        errors: list[str] = []
        if parsed is None:
            if text.strip():
                try:
                    parsed = deps.llm.parse_profile(text)
                except Exception as exc:  # degrade: ask the human instead of failing the run
                    errors.append(
                        f"intake: profile parsing failed ({exc}); asking for confirmation"
                    )
                    parsed = ProfileParse(needs_clarification=list(REQUIRED))
            else:
                parsed = ProfileParse(needs_clarification=list(REQUIRED))
        profile = profile_from_parse(parsed, override)
        out: dict[str, Any] = {
            "parsed": parsed,
            "profile": profile,
            "profile_complete": profile is not None,
            "token_usage": deps.llm.usage[usage_before:],
            "errors": errors,
        }
        return out

    return intake_node


def route_after_intake(state: AgentState) -> str:
    return "regime_node" if state.get("profile_complete") else "human_review"
