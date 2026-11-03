"""redirect_node (Orchestrator, step 10.5): the fixed polite reply for off-topic messages.

Nothing is generated: the text is a constant, but it still passes through Compliance so the
invariant "every reply carries an audit entry" has no exceptions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.models import OFF_TOPIC_REPLY, Narrative, Paragraph


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def redirect_node(state: AgentState) -> dict[str, Any]:
        answer = Narrative(
            paragraphs=[
                Paragraph(mode="notice", text=OFF_TOPIC_REPLY),
                Paragraph(mode="notice", text=deps.cfg.settings.disclaimer),
            ]
        )
        return {"answer": answer, "citations": [], "sources": [], "explain_payload": {}}

    return redirect_node
