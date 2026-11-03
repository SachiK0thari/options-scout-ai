"""compliance_node: numeric grounding + policy; bounded retry back to the explainer.

Renamed from ``verifier_node`` in Phase 10 step 10.1 with the body unchanged; step 10.4 extends it
to the eight checks of section 13.1. The Compliance agent (``agent/agents/compliance.py``) is the
only path from any LLM-written text to the user.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.compliance import verify_narrative


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def compliance_node(state: AgentState) -> dict[str, Any]:
        attempts = int((state.get("retries") or {}).get("explainer", 0)) + 1
        payload = dict(state.get("explain_payload") or {})
        payload.pop("previous_attempt_problems", None)  # feedback text must not ground numbers
        result = verify_narrative(
            state.get("narrative") or "",
            payload,
            disclaimer=deps.cfg.settings.disclaimer,
            rel_tol=deps.cfg.settings.agent.verifier_number_tolerance,
            attempts=attempts,
        )
        out: dict[str, Any] = {"verification": result, "retries": {"explainer": attempts}}
        if not result.passed:
            problems = []
            if result.ungrounded_numbers:
                problems.append(f"numbers not in payload: {', '.join(result.ungrounded_numbers)}")
            if result.banned_phrases_found:
                problems.append(f"banned phrases: {', '.join(result.banned_phrases_found)}")
            if not result.disclaimer_present:
                problems.append("disclaimer missing")
            out["verifier_feedback"] = "; ".join(problems)
            out["errors"] = [f"verifier: attempt {attempts} failed ({out['verifier_feedback']})"]
        return out

    return compliance_node


def make_router(deps: Deps) -> Callable[[AgentState], str]:
    """Node-level decision: retry the explainer or go to the report. Agents map these names."""

    def route_after_compliance(state: AgentState) -> str:
        v = state.get("verification")
        n = int((state.get("retries") or {}).get("explainer", 0))
        if v is not None and not v.passed and n < deps.cfg.settings.agent.max_explainer_retries + 1:
            return "explainer_node"
        return "report_node"

    return route_after_compliance
