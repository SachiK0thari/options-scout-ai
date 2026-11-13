"""report_node: assemble the ScreeningReport (JSON) and its Markdown rendering."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.nodes.compliance import evaluate
from options_scout.agent.nodes.explainer import render_sources_block, rule_prompt
from options_scout.agent.state import AgentState
from options_scout.core import report as md
from options_scout.core.compliance import (
    WITHHELD_NOTICE,
    fact_suitability_codes,
    resolve_citations,
    withheld_narrative,
    withheld_reason_codes,
)
from options_scout.core.grounding import SLOT, render_narrative
from options_scout.core.models import (
    Citation,
    ComplianceReport,
    Narrative,
    PortfolioTotals,
    RunMetadata,
    ScreeningReport,
    SizedPortfolio,
    utcnow,
)
from options_scout.llm.prompts import prompt_versions
from options_scout.llm.rules import rule_explain
from options_scout.rag.models import citation_of


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
        md.render_allocation(rep.allocation, rep.profile.account_type),
        "",
        "## Trend board (consumer trends)",
        md.render_trends(rep.trends),
        "",
        "## Bottleneck board (secondary)",
        md.render_bottlenecks(rep.bottlenecks),
        "",
        f"Universe considered: {', '.join(rep.universe) if rep.universe else 'n/a'}",
        "",
        "## News desk",
        md.render_news(rep.news_briefs, rep.news_flags),
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
        (
            f"{WITHHELD_NOTICE} Reason codes: {', '.join(rep.withheld_reasons)}."
            if rep.withheld
            else md.render_portfolio(
                rep.portfolio, rep.ranked, rep.risk.sizing_warnings, rep.profile.account_type
            )
        ),
        "",
        "## Risk",
        md.render_risk(rep.risk),
        "",
        *(["## Goal plan", md.render_goal(rep.goal_plan), ""] if rep.goal_plan else []),
        "## Explanation",
        rep.narrative_markdown,
        "",
        "## Sources",
        md.render_sources(rep.citations),
        "",
        "## Compliance",
        md.render_compliance(rep.compliance, rep.audit_log),
        "",
        "## Verification",
        (
            f"{'PASS' if rep.verification.passed else 'FAIL'}: "
            f"{rep.verification.numbers_checked} numbers checked, "
            f"{len(rep.verification.ungrounded_numbers)} ungrounded, banned phrases: "
            f"{', '.join(rep.verification.banned_phrases_found) or 'none'}, disclaimer "
            f"{'present' if rep.verification.disclaimer_present else 'MISSING'}, "
            f"citations {rep.verification.citations_checked} checked / "
            f"{len(rep.verification.unknown_citations)} unknown, "
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


def _withheld_portfolio(portfolio: SizedPortfolio, compliance: ComplianceReport) -> SizedPortfolio:
    """No positions and zero totals: the sized portfolio is what the gate refused to release."""
    zero = PortfolioTotals(
        short_put_notional=0.0,
        capital_used=0.0,
        margin_used=0.0,
        leaps_cost=0.0,
        realistic_loss=0.0,
        dollar_delta=0.0,
        premium_income=0.0,
        cash_reserve=0.0,
        buying_power_used_pct=0.0,
    )
    note = f"withheld: {', '.join(withheld_reason_codes(compliance))}"
    return SizedPortfolio(positions=[], totals=zero, skipped=[note], attempt=portfolio.attempt)


_PARAGRAPH = re.compile(r"^paragraph (\d+)\b")
MAX_REPLACED = 2  # W14: paragraphs the rule writer may supply in a "mixed" narrative


def _failing_paragraphs(report: ComplianceReport) -> list[int] | None:
    """0-based indices of the paragraphs a failed report blames, or None when a blocking check
    failed on something no single paragraph owns (the disclaimer count, a suitability code, an
    unknown source tag), which only the whole deterministic narrative can fix."""
    out: set[int] = set()
    for c in report.failed_checks:
        if c.severity != "block":
            continue
        if not c.locations:
            return None
        for loc in c.locations:
            m = _PARAGRAPH.match(loc)
            if not m:
                return None
            out.add(int(m.group(1)) - 1)
    return sorted(out)


def _score(report: ComplianceReport) -> tuple[int, int]:
    blocking = [c for c in report.failed_checks if c.severity == "block"]
    return len(blocking), sum(max(len(c.locations), 1) for c in blocking)


# W14: the report section a paragraph covers, by the payload area its slots read most
_SECTIONS = {
    "profile": "allocation",
    "regime": "allocation",
    "allocation": "allocation",
    "quality_screen": "quality",
    "trends": "trends",
    "bottlenecks": "bottlenecks",
    "positions": "positions",
    "skipped_candidates": "positions",
    "risk": "risk",
    "portfolio": "risk",
}


def section_of(p: Any) -> str | None:
    """The section a paragraph covers: the one most of its slots read (first on a tie), or None
    for a paragraph without run slots (education, the caveats, the disclaimer)."""
    tally: dict[str, int] = {}
    for m in SLOT.finditer(p.template if p.template is not None else p.text):
        head = re.match(r"([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?", m.group(1).strip())
        if head is None:
            continue
        # the sizer's warnings and flags are their own section, not the risk picture
        warn = head.group(1) == "risk" and head.group(2) in ("warnings", "sizing_flags")
        sec = "warnings" if warn else _SECTIONS.get(head.group(1))
        if sec:
            tally[sec] = tally.get(sec, 0) + 1
    return max(tally, key=lambda k: tally[k]) if tally else None


def mixed_narrative(
    deps: Deps,
    state: AgentState,
    failed: ComplianceReport,
    rules: Narrative,
    *,
    attempts: int,
) -> tuple[Narrative, ComplianceReport, list[str]] | None:
    """W14: the model's last attempt with its failing paragraphs dropped, and rule-writer
    paragraphs added back only where the full check still finds something missing (the
    disclaimer, the delayed-data statement, a flag the text must state). At most
    ``MAX_REPLACED`` paragraphs, and at most a quarter of the model's, may change; the result
    must pass every check, or None (the caller uses the whole deterministic narrative)."""
    model: Narrative = state.get("narrative") or Narrative()
    bad = _failing_paragraphs(failed)
    paragraphs = list(model.paragraphs)
    if not bad or len(bad) > min(MAX_REPLACED, len(paragraphs) // 4):
        return None
    if any(i >= len(paragraphs) for i in bad):
        return None
    kept = [p for i, p in enumerate(paragraphs) if i not in bad]
    at = min(bad[0], len(kept))
    notes = [f"paragraph {i + 1} of the model's text dropped (failed compliance)" for i in bad]

    def check(ps: list[Any]) -> ComplianceReport:
        return evaluate(deps, {**state, "narrative": Narrative(paragraphs=ps)}, attempts=attempts)

    current = check(kept)
    added = 0
    # a section the dropped paragraphs covered and no kept paragraph does comes back as the
    # rule writer's paragraph for it, where the dropped one stood (if that makes nothing worse)
    covered = {section_of(p) for p in kept}
    for i in bad:
        sec = section_of(paragraphs[i])
        if sec is None or sec in covered or added >= len(bad):
            continue
        match = next(((j, r) for j, r in enumerate(rules.paragraphs) if section_of(r) == sec), None)
        if match is None:
            continue
        pos = sum(1 for k in range(i) if k not in bad) + added
        trial = [*kept[:pos], match[1], *kept[pos:]]
        rep = check(trial)
        if _score(rep) <= _score(current):
            kept, current = trial, rep
            covered.add(sec)
            added += 1
            notes.append(f"paragraph {match[0] + 1} of the deterministic text added ({sec})")
    at = min(at, len(kept))
    disclaimer = deps.cfg.settings.disclaimer.strip()[:60]
    while not current.passed and added < len(bad):
        best: tuple[tuple[int, int], list[Any], int] | None = None
        for j, r in enumerate(rules.paragraphs):
            if r in kept:
                continue
            pos = len(kept) if disclaimer and disclaimer in r.text else at
            trial = [*kept[:pos], r, *kept[pos:]]
            rep = check(trial)
            if _score(rep) < _score(current) and (best is None or _score(rep) < best[0]):
                best = (_score(rep), trial, j)
        if best is None:
            return None
        kept = best[1]
        current = check(kept)
        added += 1
        notes.append(f"paragraph {best[2] + 1} of the deterministic text added")
    if not current.passed:
        return None
    return Narrative(paragraphs=kept), current, notes


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def report_node(state: AgentState) -> dict[str, Any]:
        profile, regime, alloc = state["profile"], state["regime"], state["allocation"]
        portfolio, risk, verification = state["portfolio"], state["risk"], state["verification"]
        assert profile and regime and alloc and portfolio and risk and verification
        errors = list(state.get("errors", []))
        narrative: Narrative = state.get("narrative") or Narrative()
        payload = dict(state.get("explain_payload") or {})
        payload.pop("previous_attempt_problems", None)
        sources = list(state.get("sources") or [])
        source_cites: list[Citation] = [citation_of(c) for c in sources]
        compliance = state.get("compliance")
        audit_log = list(state.get("audit_log") or [])
        withheld = False
        source = state.get("narrative_source") or "rules"
        patches = list(state.get("narrative_patches") or [])
        rules_paragraphs = 0
        if not verification.passed and not fact_suitability_codes(compliance):
            # Final fallback (13.1): deterministic narrative that only echoes payload numbers and
            # quotes the retrieved sources verbatim, checked again so the audit log stays honest.
            rules = render_narrative(
                rule_explain(rule_prompt(payload, render_sources_block(sources))), payload
            )
            # W14: first try keeping the model's text with its failing paragraphs replaced
            mixed = (
                mixed_narrative(deps, state, compliance, rules, attempts=verification.attempts)
                if compliance is not None
                and source in ("model", "fixture")  # a replay is model text
                else None
            )
            if mixed is not None:
                narrative, recheck, notes = mixed
                rules_paragraphs = sum(1 for n in notes if "of the deterministic text added" in n)
                patches += notes
                errors.append(
                    f"report: LLM narrative failed compliance after {verification.attempts} "
                    f"attempt(s); {len(notes) - rules_paragraphs} paragraph(s) dropped and "
                    f"{rules_paragraphs} deterministic paragraph(s) added (passed=True)"
                )
                source = "mixed"
            else:
                narrative = rules
                fallback_state: dict[str, Any] = {**state, "narrative": narrative}
                recheck = evaluate(deps, fallback_state, attempts=verification.attempts)  # type: ignore[arg-type]
                errors.append(
                    f"report: LLM narrative failed compliance after {verification.attempts} "
                    f"attempt(s); deterministic narrative used (passed={recheck.passed})"
                )
                source = "rules"
                patches = []
            compliance = recheck
            verification = recheck.verification
            audit_log.append(recheck)
        if compliance is None or not audit_log:
            raise RuntimeError("report assembled without a ComplianceReport")  # 13.1 invariant
        if not compliance.passed:
            # W12: nothing the gate failed is released. The narrative becomes the fixed notice
            # and the sized positions are dropped; the failing report stays attached and on the
            # audit log, so the run says exactly why it was withheld.
            withheld = True
            source = "withheld"
            rules_paragraphs, patches = 0, []
            narrative = withheld_narrative(compliance, deps.cfg.settings.disclaimer)
            errors.append(
                f"report: withheld ({', '.join(withheld_reason_codes(compliance))}); "
                f"{WITHHELD_NOTICE}"
            )
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
            agent_latency_ms=dict(state.get("agent_latency_ms", {})),
            agents_visited=list(state.get("agents_visited", [])),
            narrative_source=source,
            rules_paragraphs=rules_paragraphs,
            narrative_patches=patches,
        )
        # The report lists the ranker's shortlist (best N per ticker and strategy, in rank order),
        # not every strike the screeners emitted: otherwise one ETF's ladder fills the tables.
        ranked = state.get("ranked", [])
        cands = [r.candidate for r in ranked] or state.get("candidates", [])
        kept_leaps = {c.id for c in cands if c.strategy == "leaps"}
        pairs = [p for p in state.get("pmcc_pairs", []) if p.leaps.id in kept_leaps]
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
            pmcc_candidates=pairs,
            ranked=ranked,
            portfolio=_withheld_portfolio(portfolio, compliance) if withheld else portfolio,
            risk=risk,
            narrative=narrative,
            narrative_markdown=narrative.markdown,
            citations=resolve_citations(narrative, source_cites),
            verification=verification,
            compliance=compliance,
            audit_log=audit_log,
            goal_plan=None if withheld else state.get("goal_plan"),  # built on the positions
            news_briefs=list(state.get("news_briefs") or []),
            news_flags=list(state.get("news_flags") or []),
            bottlenecks=list(state.get("bottlenecks") or []),
            errors=sorted(set(errors)),
            metadata=meta,
            disclaimer=deps.cfg.settings.disclaimer,
            withheld=withheld,
            withheld_reasons=withheld_reason_codes(compliance) if withheld else [],
        )
        out: dict[str, Any] = {
            "report": rep,
            "report_markdown": render_markdown(rep),
            "narrative": narrative,
            "citations": rep.citations,
            "verification": verification,
            "compliance": compliance,
            "audit_log": audit_log[len(state.get("audit_log") or []) :],
        }
        # W19: the option chains were for the screeners, which have run. Every later reader (risk,
        # holdings, news, the UI) uses the quote, IV and dividend fields, so the thread keeps the
        # snapshots without their chains: about 2 MB less in every checkpoint of the thread.
        snapshots = state.get("market_data") or {}
        if any(s.chains for s in snapshots.values()):
            out["market_data"] = {
                t: s.model_copy(update={"chains": []}) for t, s in snapshots.items()
            }
        if withheld:
            # W12/W39: the thread state drops what the gate refused, as the report does, so a
            # later goal or holdings turn (or /v1/threads) never reads the sized positions
            out["portfolio"] = None
            out["goal_plan"] = None
        return out

    return report_node
