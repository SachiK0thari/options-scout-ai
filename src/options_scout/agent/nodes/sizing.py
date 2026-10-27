"""sizing_node: greedy constrained sizing; each retry shrinks the budgets by 20%."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.sizing import size_portfolio

RETRY_SHRINK = 0.8


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def sizing_node(state: AgentState) -> dict[str, Any]:
        profile, allocation = state["profile"], state["allocation"]
        assert profile is not None and allocation is not None
        attempt = int((state.get("retries") or {}).get("sizing", 0))
        portfolio = size_portfolio(
            state.get("ranked", []),
            profile,
            allocation,
            deps.cfg.risk.constraints[profile.risk_profile],
            realistic_loss_drop=deps.cfg.risk.realistic_loss_drop,
            scale=RETRY_SHRINK**attempt,
            attempt=attempt + 1,
        )
        return {"portfolio": portfolio}

    return sizing_node
