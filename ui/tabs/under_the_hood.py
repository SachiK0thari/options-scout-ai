"""Under the hood: agent trace, tokens and cost, compliance audit log, retrieval log, downloads."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from options_scout.agent.graph import AGENT_ORDER
from ui import charts, session, theme


def render(view: session.View) -> None:
    st.subheader("Under the hood")
    st.markdown(
        "Orchestrator → 2 · Market Intelligence → 1 · Market Data (quality gate) → 3 · Strategy → "
        "4 · Portfolio ↔ 5 · Risk → 6 · Education ↔ Compliance → report. Eight LangGraph subgraphs "
        "composed by one parent graph; **the LLM never does math**."
    )
    report = view.report
    state = view.state
    if report is None and not view.history:
        st.info("Run a screen or ask a question to see the trace.")
        return
    if report is not None:
        meta = report.metadata
        u1, u2, u3, u4 = st.columns(4)
        u1.metric("LLM cost", f"${meta.total_cost_usd:.4f}")
        u2.metric("Specialists run", len(meta.agents_visited))
        u3.metric("Nodes run", len(meta.nodes_visited))
        u4.metric("Universe considered", len(report.universe))
        a1, a2 = st.columns([3, 2])
        with a1:
            if meta.agent_latency_ms:
                theme.show(
                    charts.agent_latency(meta.agent_latency_ms, AGENT_ORDER),
                    "Wall-clock time inside each specialist subgraph for this run.",
                )
        with a2:
            st.markdown("**Nodes visited (in order)**")
            st.dataframe(
                pd.DataFrame(
                    {
                        "node": meta.nodes_visited,
                        "ms (summed)": [
                            meta.node_latency_ms.get(n, 0.0) for n in meta.nodes_visited
                        ],
                    }
                ),
                width="stretch",
                hide_index=True,
                height=300,
            )
        st.markdown("**Tokens and cost**")
        if meta.token_usage:
            st.dataframe(
                pd.DataFrame([u.model_dump() for u in meta.token_usage]),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No LLM calls were made in this run.")

    st.markdown("**Compliance audit log**")
    audits = list(report.audit_log) if report is not None else []
    for turn in view.history:
        if turn.compliance is not None and all(
            a.audit_id != turn.compliance.audit_id for a in audits
        ):
            audits.append(turn.compliance)
    if audits:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "audit id": a.audit_id,
                        "text": a.text_kind,
                        "attempt": a.attempts,
                        "passed": "✓" if a.passed else "✗",
                        "failed checks": ", ".join(c.name for c in a.failed_checks),
                        "warnings": ", ".join(c.name for c in a.warnings),
                    }
                    for a in audits
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No compliance evaluations yet.")

    st.markdown("**Retrieval log**")
    retrievals = state.get("retrievals") or []
    if retrievals:
        rows = [
            {
                "query": r.query,
                "kind": r.kind or "all",
                "rank": h.rank,
                "chunk": h.chunk.id,
                "dense": h.dense,
                "bm25": h.bm25,
                "fused": h.fused,
            }
            for r in retrievals
            for h in r.hits
        ]
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=300)
        empty = [r.query for r in retrievals if r.empty]
        if empty:
            st.caption("No chunk above the floor for: " + "; ".join(f"“{q}”" for q in empty))
        st.caption(
            f"Embedder {retrievals[0].embedder}, similarity floor {retrievals[0].floor}; hybrid "
            "reciprocal-rank fusion of dense cosine and BM25."
        )
    else:
        st.caption("No retrievals in this thread yet.")

    if report is not None:
        meta = report.metadata
        d1, d2 = st.columns(2)
        d1.download_button(
            "Download JSON",
            report.model_dump_json(indent=1),
            f"{report.run_id}.json",
            "application/json",
            key="dl_json",
        )
        d2.download_button(
            "Download Markdown", view.markdown, f"{report.run_id}.md", "text/markdown", key="dl_md"
        )
        if report.errors:
            st.markdown("**Notes and degraded sources**")
            for e in report.errors:
                st.caption(f"• {e}")
        st.json(
            {
                "run_id": report.run_id,
                "thread_id": view.thread_id,
                "data_mode": meta.data_mode,
                "llm_mode": meta.llm_mode,
                "models": meta.models,
                "prompt_versions": meta.prompt_versions,
                "config_hash": meta.config_hash,
                "data_source_status": meta.data_source_status,
            },
            expanded=False,
        )
