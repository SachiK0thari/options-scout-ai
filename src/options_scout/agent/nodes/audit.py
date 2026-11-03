"""audit_node (Compliance, step 10.4): persist every ComplianceReport and apply the chat fallback.

Appends the current ``ComplianceReport`` to the run's ``audit_log`` (one entry per evaluation,
pass or fail). When a **question** run has exhausted its retries without passing, the answer is
replaced by the fixed sentence from section 13.1 and re-checked, so the text the user sees always
carries a passing audit entry. Report runs fall back in ``report_node`` instead.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.compliance import evaluate, text_kind
from options_scout.agent.state import AgentState
from options_scout.core.models import Narrative, Paragraph

FALLBACK_SENTENCE = (
    "I can show the computed results but could not produce an explanation that passes compliance."
)


def fallback_answer(disclaimer: str) -> Narrative:
    return Narrative(
        paragraphs=[
            Paragraph(mode="notice", text=FALLBACK_SENTENCE),
            Paragraph(mode="notice", text=disclaimer),
        ]
    )


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def audit_node(state: AgentState) -> dict[str, Any]:
        report = state.get("compliance")
        if report is None:  # defensive: the agent always runs compliance_node first
            return {}
        out: dict[str, Any] = {"audit_log": [report]}
        attempts = int((state.get("retries") or {}).get("explainer", 0))
        exhausted = attempts >= deps.cfg.settings.agent.max_explainer_retries + 1
        if text_kind(state) == "answer" and not report.passed and exhausted:
            fallback_state: dict[str, Any] = {
                **state,
                "answer": fallback_answer(deps.cfg.settings.disclaimer),
                "sources": [],
                "explain_payload": {},
            }
            recheck = evaluate(deps, fallback_state, attempts=attempts)  # type: ignore[arg-type]
            out.update(
                {
                    "answer": fallback_state["answer"],
                    "citations": [],
                    "compliance": recheck,
                    "verification": recheck.verification,
                    "audit_log": [report, recheck],
                    "errors": ["compliance: answer replaced by the fixed fallback sentence"],
                }
            )
        return out

    return audit_node
