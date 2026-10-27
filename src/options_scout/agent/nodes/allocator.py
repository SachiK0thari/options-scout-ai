"""allocator_node: section 3.1 split with regime tilt."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.allocation import allocate


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def allocator_node(state: AgentState) -> dict[str, Any]:
        profile = state["profile"]
        regime = state["regime"]
        assert profile is not None and regime is not None
        return {"allocation": allocate(profile, regime, deps.cfg.risk)}

    return allocator_node
