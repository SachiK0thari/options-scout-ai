"""human_review: LangGraph interrupt() so the UI can confirm or fix the parsed profile."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.types import interrupt

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.intake import REQUIRED
from options_scout.agent.state import AgentState

MAX_REVIEW_ROUNDS = 3


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def human_review(state: AgentState) -> dict[str, Any]:
        parsed = state.get("parsed")
        rounds = int((state.get("retries") or {}).get("human_review", 0))
        if rounds >= MAX_REVIEW_ROUNDS:
            raise RuntimeError("profile still incomplete after human review rounds")
        payload = {
            "message": "Please confirm or complete your profile.",
            "parsed": parsed.model_dump(mode="json") if parsed else {},
            "needs_clarification": parsed.needs_clarification if parsed else list(REQUIRED),
            "required_fields": list(REQUIRED),
            "allowed": {
                "account_type": ["cash", "margin", "portfolio_margin"],
                "risk_profile": ["conservative", "balanced", "aggressive"],
                "strategies": ["csp", "leaps", "pmcc"],
            },
        }
        answer = interrupt(payload)  # execution pauses here until Command(resume=...)
        override = dict(state.get("profile_override") or {})
        if isinstance(answer, dict):
            override.update({k: v for k, v in answer.items() if v is not None})
        return {"profile_override": override, "retries": {"human_review": rounds + 1}}

    return human_review
