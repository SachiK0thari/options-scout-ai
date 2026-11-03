"""what_if_node (Orchestrator, step 10.5): describe the hypothetical as a profile diff.

The full run itself happens on a **new thread** (the session starts it from ``what_if_profile``);
this node only writes the reply text, a deterministic ``notice`` narrative listing what changed,
which still goes through Compliance like every other reply.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.models import Narrative, Paragraph


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def what_if_node(state: AgentState) -> dict[str, Any]:
        diff = list(state.get("what_if_diff") or [])
        if diff:
            text = (
                "**What-if.** Compared with the current profile, this changes: "
                + "; ".join(diff)
                + ". A new screen with that profile is running on a separate thread; its report "
                "will show the full candidate list, sizing and risk picture."
            )
        else:
            text = (
                "**What-if.** The message did not change any profile field, so the result would "
                "be the current report."
            )
        answer = Narrative(
            paragraphs=[
                Paragraph(mode="notice", text=text),
                Paragraph(mode="notice", text=deps.cfg.settings.disclaimer),
            ]
        )
        return {"answer": answer, "citations": [], "sources": [], "explain_payload": {}}

    return what_if_node
