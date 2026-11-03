"""concept_answer_node (Education, step 10.3): a cited answer to an education question.

With no source above the similarity floor the node does not call the LLM at all and answers with
the fixed sentence from PRD 5.6. Otherwise the LLM (or the ``--no-llm`` stand-in, which assembles
the top chunks' opening sentences with their tags) writes tagged paragraphs; the answer then goes
through Compliance like every other LLM-written string.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.explainer import render_sources_block, sources_payload
from options_scout.agent.state import AgentState
from options_scout.core.compliance import resolve_citations
from options_scout.core.models import NO_SOURCE_SENTENCE, Narrative, Paragraph
from options_scout.llm.rules import rule_answer_concept
from options_scout.rag.models import citation_of


def no_source_answer(disclaimer: str) -> Narrative:
    return Narrative(
        paragraphs=[
            Paragraph(mode="education", text=NO_SOURCE_SENTENCE),
            Paragraph(mode="notice", text=disclaimer),
        ]
    )


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def concept_answer_node(state: AgentState) -> dict[str, Any]:
        question = (state.get("question") or "").strip()
        sources = list(state.get("sources") or [])
        disclaimer = deps.cfg.settings.disclaimer
        errors: list[str] = []
        usage_before = len(deps.llm.usage)
        if not sources:
            answer = no_source_answer(disclaimer)
        else:
            block = render_sources_block(sources)
            try:
                answer = deps.llm.answer_concept(question, block, disclaimer)
            except Exception as exc:
                errors.append(f"concept_answer: LLM failed ({exc}); using source excerpts")
                answer = rule_answer_concept(
                    f"copied exactly: {disclaimer}\n<question>\n{question}\n</question>\n"
                    f"<sources>\n{block}\n</sources>"
                )
        citations = resolve_citations(answer, [citation_of(c) for c in sources])
        return {
            "answer": answer,
            "citations": citations,
            "explain_payload": {"question": question, "sources": sources_payload(sources)},
            "token_usage": deps.llm.usage[usage_before:],
            "errors": errors,
        }

    return concept_answer_node
