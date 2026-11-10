"""compliance_node: the eight checks of section 13.1 on the text this run produced.

Renamed from ``verifier_node`` in step 10.1; step 10.3 added the ``[Sn]`` tag check and answer
runs; step 10.4 replaced the single verifier call with ``core.compliance.run_compliance`` and the
``compliance.check`` audit events. ``audit_node`` (``nodes/audit.py``) persists the outcome. The
Compliance agent is the only path from any LLM-written text to the user; a blocking failure sends
Education a ``retry_feedback`` string (bounded), after which the report node or the audit node
falls back to the deterministic text.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.compliance import fact_suitability_codes, run_compliance
from options_scout.core.models import ComplianceReport, Narrative, TextKind
from options_scout.observability import get_logger
from options_scout.rag.models import citation_of

ANSWER_INTENTS = ("concept", "why", "what_if", "off_topic", "goal", "holdings", "news", "tax")


def text_kind(state: AgentState) -> TextKind:
    if (state.get("question") or "").strip() or state.get("intent") in ANSWER_INTENTS:
        return "answer"
    return "report"


def narrative_under_review(state: AgentState) -> Narrative:
    """The LLM-written text this run produced: the answer for a question, else the narrative."""
    target: Narrative | None = state.get("answer") if text_kind(state) == "answer" else None
    if target is None:
        target = state.get("narrative")
    return target if target is not None else Narrative()


def text_under_review(state: AgentState) -> str:
    return narrative_under_review(state).markdown


def evaluate(deps: Deps, state: AgentState, *, attempts: int) -> ComplianceReport:
    """Run the eight checks for the current state (shared by the node and the report fallback)."""
    payload = dict(state.get("explain_payload") or {})
    payload.pop("previous_attempt_problems", None)  # feedback text must not ground numbers
    kind = text_kind(state)
    return run_compliance(
        narrative_under_review(state),
        payload=payload,
        sources=[citation_of(c) for c in (state.get("sources") or [])],
        facts=state.get("suitability_facts") if kind == "report" else None,
        cfg=deps.cfg.compliance,
        disclaimer=deps.cfg.settings.disclaimer,
        text_kind=kind,
        run_tickers=list(state.get("universe") or []),
        rel_tol=deps.cfg.settings.agent.verifier_number_tolerance,
        attempts=attempts,
        delayed_data=True,  # neither fixture data nor the free tiers are real-time
        today=deps.md.today(),
    )


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def compliance_node(state: AgentState) -> dict[str, Any]:
        attempts = int((state.get("retries") or {}).get("explainer", 0)) + 1
        report = evaluate(deps, state, attempts=attempts)
        log = get_logger(
            agent="compliance_agent", run_id=state.get("run_id"), audit_id=report.audit_id
        )
        for check in report.checks:
            log.info(
                "compliance.check",
                check=check.name,
                passed=check.passed,
                severity=check.severity,
                detail=check.detail,
                attempt=attempts,
                text_kind=report.text_kind,
            )
        out: dict[str, Any] = {
            "compliance": report,
            "verification": report.verification,
            "retries": {"explainer": attempts},
            "verifier_feedback": report.retry_feedback or None,
        }
        if not report.passed:
            out["errors"] = [f"compliance: attempt {attempts} failed ({report.retry_feedback})"]
        return out

    return compliance_node


def make_router(deps: Deps) -> Callable[[AgentState], str]:
    """Node-level decision: retry the explainer or go to the report. Agents map these names."""

    def route_after_compliance(state: AgentState) -> str:
        v = state.get("verification")
        n = int((state.get("retries") or {}).get("explainer", 0))
        if fact_suitability_codes(state.get("compliance")):
            # W12: the sized portfolio does not suit the account; rewriting the prose cannot
            # change that, so go straight to the report node's withheld path
            return "report_node"
        if v is not None and not v.passed and n < deps.cfg.settings.agent.max_explainer_retries + 1:
            return "explainer_node"
        return "report_node"

    return route_after_compliance
