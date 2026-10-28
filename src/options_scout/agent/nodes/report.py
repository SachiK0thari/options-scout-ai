"""report_node: assemble the ScreeningReport (JSON) and its Markdown rendering."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.agent.verifier import verify_narrative
from options_scout.core import report as md
from options_scout.core.models import RunMetadata, ScreeningReport, utcnow
from options_scout.llm.prompts import prompt_versions
from options_scout.llm.rules import rule_explain


def config_hash(deps: Deps) -> str:
    h = hashlib.sha256()
    for p in sorted((deps.cfg.root / "config").glob("*.yaml")):
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def render_markdown(rep: ScreeningReport) -> str:
    pairs = rep.pmcc_candidates
    parts = [
        f"# OptionsScout AI screening report: run `{rep.run_id}`",
        f"_As of {rep.as_of:%Y-%m-%d %H:%M UTC} · {rep.metadata.data_mode} market data · "
        f"LLM mode {rep.metadata.llm_mode} · delayed data, for education only._",
        "",
        f"> {rep.disclaimer}",
        "",
        "## Profile",
        md.render_profile(rep.profile),
        "",
        "## Regime and allocation",
        md.render_regime(rep.regime),
        "",
        md.render_allocation(rep.allocation),
        "",
        "## Trend board (consumer trends)",
        md.render_trends(rep.trends),
        "",
        f"Universe considered: {', '.join(rep.universe) if rep.universe else 'n/a'}",
        "",
        "## Good-to-own quality screen",
        md.render_quality(rep.quality),
        "",
        "## CSP candidates",
        md.render_csp(rep.csp_candidates),
        "",
        "## LEAPS / PMCC candidates",
        md.render_leaps(rep.leaps_candidates, pairs),
        "",
        "## Sized portfolio",
        md.render_portfolio(rep.portfolio, rep.ranked),
        "",
        "## Risk",
        md.render_risk(rep.risk),
        "",
        "## Explanation",
        rep.narrative,
        "",
        "## Verification",
        (
            f"{'PASS' if rep.verification.passed else 'FAIL'}: "
            f"{rep.verification.numbers_checked} numbers checked, "
            f"{len(rep.verification.ungrounded_numbers)} ungrounded, banned phrases: "
            f"{', '.join(rep.verification.banned_phrases_found) or 'none'}, disclaimer "
            f"{'present' if rep.verification.disclaimer_present else 'MISSING'}, "
            f"attempts {rep.verification.attempts}."
        ),
        "",
        "## Run metadata",
        f"- Models: {json.dumps(rep.metadata.models)}",
        f"- Prompt versions: {json.dumps(rep.metadata.prompt_versions)}",
        f"- Config hash: `{rep.metadata.config_hash}`",
        f"- Data sources: {json.dumps(rep.metadata.data_source_status)}",
        f"- Tokens: {sum(u.input_tokens for u in rep.metadata.token_usage)} in / "
        f"{sum(u.output_tokens for u in rep.metadata.token_usage)} out · "
        f"cost ${rep.metadata.total_cost_usd:.4f}",
        f"- Nodes visited: {' → '.join(rep.metadata.nodes_visited)}",
        f"- Latency per node (ms): {json.dumps(rep.metadata.node_latency_ms)}",
    ]
    if rep.errors:
        parts += ["", "## Notes and degraded sources", *[f"- {e}" for e in rep.errors]]
    parts += ["", f"> {rep.disclaimer}", ""]
    return "\n".join(parts)


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def report_node(state: AgentState) -> dict[str, Any]:
        profile, regime, alloc = state["profile"], state["regime"], state["allocation"]
        portfolio, risk, verification = state["portfolio"], state["risk"], state["verification"]
        assert profile and regime and alloc and portfolio and risk and verification
        errors = list(state.get("errors", []))
        narrative = state.get("narrative") or ""
        payload = state.get("explain_payload") or {}
        if not verification.passed:
            # Final fallback: deterministic narrative that only echoes payload numbers.
            narrative = rule_explain(
                f"<payload>\n{json.dumps(payload, default=str)}\n</payload>"
            ).text
            fallback = verify_narrative(
                narrative,
                payload,
                disclaimer=deps.cfg.settings.disclaimer,
                attempts=verification.attempts,
            )
            errors.append(
                f"report: LLM narrative failed verification after {verification.attempts} "
                f"attempt(s); deterministic narrative used (grounded={fallback.passed})"
            )
            verification = fallback
        started = (
            datetime.fromisoformat(state["started_at"]) if state.get("started_at") else utcnow()
        )
        usage = list(state.get("token_usage", []))
        meta = RunMetadata(
            run_id=state.get("run_id", "run"),
            started_at=started,
            finished_at=utcnow(),
            data_mode=deps.md.source.name,
            llm_mode=deps.llm.mode,
            models={
                "extraction": deps.llm.models.extraction_model,
                "explanation": deps.llm.models.explanation_model,
                "provider": deps.llm.provider.name,
            },
            prompt_versions=prompt_versions(deps.cfg.paths.prompts_dir),
            config_hash=config_hash(deps),
            data_source_status=dict(state.get("data_source_status", {})),
            token_usage=usage,
            total_cost_usd=round(sum(u.cost_usd for u in usage), 6),
            node_latency_ms={**state.get("node_latency_ms", {}), "report_node": 0.0},
            nodes_visited=[*state.get("nodes_visited", []), "report_node"],
        )
        cands = state.get("candidates", [])
        rep = ScreeningReport(
            run_id=meta.run_id,
            as_of=deps.md.now(),
            profile=profile,
            regime=regime,
            allocation=alloc,
            trends=state.get("trends", []),
            universe=state.get("universe", []),
            quality=[
                q for t in state.get("universe", []) if (q := state.get("quality", {}).get(t))
            ],
            csp_candidates=[c for c in cands if c.strategy == "csp"],
            leaps_candidates=[c for c in cands if c.strategy == "leaps"],
            pmcc_candidates=state.get("pmcc_pairs", []),
            ranked=state.get("ranked", []),
            portfolio=portfolio,
            risk=risk,
            narrative=narrative,
            verification=verification,
            errors=sorted(set(errors)),
            metadata=meta,
            disclaimer=deps.cfg.settings.disclaimer,
        )
        return {
            "report": rep,
            "report_markdown": render_markdown(rep),
            "narrative": narrative,
            "verification": verification,
        }

    return report_node
