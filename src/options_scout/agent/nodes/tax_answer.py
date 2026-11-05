"""tax_answer_node (Tax & Accounts, Phase 12 step 12.6): the cited reply.

The LLM (``answer_tax``) or the deterministic stand-in writes tagged paragraphs from the tax
sources and the illustrative facts. The reply must carry the tax disclaimer exactly once, no rate
a reader will pay and no filing instruction; Compliance check 11 enforces it before release.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.explainer import render_sources_block, sources_payload
from options_scout.agent.state import AgentState
from options_scout.core.compliance import resolve_citations
from options_scout.core.models import NO_SOURCE_SENTENCE, Narrative, Paragraph, TaxFacts
from options_scout.llm.rules import rule_answer_tax
from options_scout.rag.models import citation_of


def rule_prompt(
    question: str, facts: dict[str, Any], block: str, disclaimer: str, tax_disclaimer: str
) -> str:
    return (
        f"copied exactly: {disclaimer}\n"
        f"tax disclaimer: {tax_disclaimer}\n"
        f"<question>\n{question}\n</question>\n"
        f"<facts>\n{json.dumps(facts, default=str)}\n</facts>\n"
        f"<sources>\n{block}\n</sources>"
    )


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def tax_answer_node(state: AgentState) -> dict[str, Any]:
        disclaimer = deps.cfg.settings.disclaimer
        tax_disclaimer = deps.cfg.compliance.tax.disclaimer
        question = (state.get("question") or state.get("tax_text") or "").strip()
        sources = list(state.get("sources") or [])
        facts_model = state.get("tax_facts") or TaxFacts(as_of=deps.md.today())
        facts = facts_model.model_dump(mode="json")
        errors: list[str] = []
        usage_before = len(deps.llm.usage)
        payload: dict[str, Any] = {
            "tax": {"question": question, "facts": facts},
            "sources": sources_payload(sources),
            "disclaimer": disclaimer,
            "tax_disclaimer": tax_disclaimer,
        }
        if not sources:
            answer = Narrative(
                paragraphs=[
                    Paragraph(mode="notice", text=NO_SOURCE_SENTENCE),
                    Paragraph(mode="notice", text=tax_disclaimer),
                    Paragraph(mode="notice", text=disclaimer),
                ]
            )
        else:
            block = render_sources_block(sources)
            try:
                answer = deps.llm.answer_tax(question, block, facts, disclaimer, tax_disclaimer)
            except Exception as exc:
                errors.append(f"tax_answer: LLM failed ({exc}); using source excerpts")
                answer = rule_answer_tax(
                    rule_prompt(question, facts, block, disclaimer, tax_disclaimer)
                )
        feedback = state.get("verifier_feedback")
        if feedback:
            payload["previous_attempt_problems"] = feedback
        return {
            "answer": answer,
            "citations": resolve_citations(answer, [citation_of(c) for c in sources]),
            "explain_payload": payload,
            "token_usage": deps.llm.usage[usage_before:],
            "errors": errors,
        }

    return tax_answer_node
