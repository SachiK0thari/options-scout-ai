"""Command-line entry points. ``demo`` runs the deterministic pipeline on fixtures (no LLM)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from options_scout.config import AppConfig, get_config
from options_scout.core import ranking, report, risk, screeners, sizing
from options_scout.core.allocation import allocate
from options_scout.core.models import (
    OptionCandidate,
    PMCCCandidate,
    QualityCheck,
    TickerSnapshot,
    UserProfile,
)
from options_scout.core.quality import check_quality
from options_scout.core.regime import make_regime
from options_scout.data.fixtures import DEMO_TICKERS
from options_scout.data.market import MarketData


def run_deterministic_pipeline(
    cfg: AppConfig,
    profile: UserProfile,
    tickers: Sequence[str],
    social_scores: dict[str, float] | None = None,
    *,
    md: MarketData | None = None,
) -> dict[str, Any]:
    """Regime → allocation → screeners → rank → size → risk, with no LLM involved."""
    md = md or MarketData.from_config(cfg)
    today = md.today()
    vix, pct = md.get_vix_percentile()
    r = md.get_risk_free_rate()
    regime = make_regime(
        vix=vix,
        vix_percentile=pct,
        risk_free_rate=r,
        tilt=cfg.risk.regime_tilt,
        as_of=md.now(),
        source="fixture" if md.source.name == "fixture" else "live",
    )
    allocation = allocate(profile, regime, cfg.risk)
    snapshots: dict[str, TickerSnapshot] = {}
    csp: list[OptionCandidate] = []
    leaps: list[OptionCandidate] = []
    pairs: list[PMCCCandidate] = []
    errors: list[str] = []
    quality: dict[str, QualityCheck] = {}
    for t in tickers:
        if t in profile.exclude:
            continue
        try:
            snap = md.build_snapshot(t)
            closes = md.get_close_history(t, 90)
        except Exception as exc:  # degrade gracefully: skip the ticker, record why
            errors.append(f"{t}: {type(exc).__name__}: {exc}")
            continue
        quality[t] = check_quality(snap, closes, cfg.quality, cfg.quality.get(t))
        if not quality[t].passed:
            errors.append(f"{t}: excluded by quality gate — {'; '.join(quality[t].reasons)}")
            continue
        snapshots[t] = snap
        errors.extend(f"{t}: {e}" for e in snap.source_errors)
        if "csp" in profile.strategies:
            csp += screeners.screen_csp(
                snap,
                cfg.rules.csp,
                today=today,
                r=r,
                realistic_loss_drop=cfg.risk.realistic_loss_drop,
            )
        if {"leaps", "pmcc"} & profile.strategies:
            lp = screeners.screen_leaps(snap, cfg.rules.leaps, today=today, r=r)
            leaps += lp
            if "pmcc" in profile.strategies:
                pairs += screeners.pair_pmcc(lp, snap, cfg.rules.pmcc, today=today, r=r)
    ranked = ranking.rank_candidates(
        csp + leaps,
        social_scores or {},
        {t: q.score for t, q in quality.items() if q.passed},
        weights=cfg.settings.ranking.weights,
        option_weights=cfg.settings.ranking.option_quality_weights,
        rules=cfg.rules,
        pmcc_pairs=pairs,
    )
    limits = cfg.risk.constraints[profile.risk_profile]
    portfolio = sizing.size_portfolio(
        ranked, profile, allocation, limits, realistic_loss_drop=cfg.risk.realistic_loss_drop
    )
    cands = {c.id: c for c in csp + leaps}
    for p in pairs:
        cands[p.short_call.id] = p.short_call
    stress = risk.stress_test(
        portfolio,
        cands,
        snapshots,
        shocks=cfg.settings.risk.stress_shocks,
        iv_shock=cfg.settings.risk.stress_iv_shock,
        r=r,
        today=today,
        account_value=profile.account_value,
    )
    risk_report = risk.build_risk_report(portfolio, profile, limits, stress, cands)
    return {
        "regime": regime,
        "allocation": allocation,
        "quality": list(quality.values()),
        "snapshots": snapshots,
        "csp": csp,
        "leaps": leaps,
        "pairs": pairs,
        "ranked": ranked,
        "portfolio": portfolio,
        "risk": risk_report,
        "errors": errors,
    }


def render_demo(cfg: AppConfig, profile: UserProfile, out: dict[str, Any]) -> str:
    parts = [
        f"## {profile.risk_profile.title()} · {profile.account_type} account",
        report.render_profile(profile),
        "",
        "### Regime",
        report.render_regime(out["regime"]),
        "",
        "### Allocation",
        report.render_allocation(out["allocation"]),
        "",
        "### Good-to-own quality screen",
        report.render_quality(out["quality"]),
        "",
        "### CSP candidates",
        report.render_csp(out["csp"]),
        "",
        "### LEAPS / PMCC candidates",
        report.render_leaps(out["leaps"], out["pairs"]),
        "",
        "### Sized portfolio",
        report.render_portfolio(out["portfolio"], out["ranked"]),
        "",
        "### Risk",
        report.render_risk(out["risk"]),
    ]
    if out["errors"]:
        parts += ["", "### Data source notes", *[f"- {e}" for e in out["errors"]]]
    parts += ["", f"> {cfg.settings.disclaimer}", ""]
    return "\n".join(parts)


def cmd_demo_core(args: argparse.Namespace) -> int:
    """Deterministic pipeline only (Phase 3 acceptance): no agent, no social engine, no LLM."""
    cfg = get_config()
    profiles = [args.risk] if args.risk else ["conservative", "balanced", "aggressive"]
    accounts = [args.account] if args.account else ["cash", "margin"]
    tickers = [t.upper() for t in args.tickers] or list(DEMO_TICKERS)
    md = MarketData.from_config(cfg)
    print(f"# OptionsScout AI demo — {cfg.settings.data_mode} data, no LLM\n")
    print(f"_Data as of {md.now():%Y-%m-%d %H:%M UTC}. Delayed data, for education only._\n")
    failures = 0
    for risk_name in profiles:
        for acct in accounts:
            profile = UserProfile(
                buying_power=args.buying_power,
                account_value=args.account_value or args.buying_power,
                account_type=acct,
                risk_profile=risk_name,
                max_positions=args.max_positions,
            )
            out = run_deterministic_pipeline(cfg, profile, tickers, md=md)
            print(render_demo(cfg, profile, out))
            if not out["risk"].passed or not out["portfolio"].positions:
                failures += 1
    if failures:
        print(
            f"\n{failures} profile/account combination(s) produced an empty or failing portfolio."
        )
        return 1
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Full LangGraph pipeline in fixture mode (Phase 8 acceptance). ``--no-llm`` skips the LLM."""
    import os

    if args.no_llm:
        os.environ["OPTIONS_SCOUT_LLM_MODE"] = "none"
    get_config.cache_clear()
    cfg = get_config()
    from options_scout.agent.deps import Deps
    from options_scout.agent.graph import (
        build_graph,
        initial_state,
        pending_interrupt,
        stream_run,
        thread_config,
    )

    deps = Deps.from_config(cfg)
    graph = build_graph(deps)
    thread = f"demo-{os.getpid()}"
    wants = {
        "csp": "Show me cash-secured puts only.",
        "leaps": "Show me LEAPS calls only.",
        "both": "Show me CSPs and LEAPS/PMCC ideas.",
    }[args.strategy]
    text = args.request or (
        f"I have ${args.buying_power:,.0f} of buying power in a {args.account or 'margin'} "
        f"account, {args.risk or 'balanced'} risk tolerance. {wants}"
    )
    print(f"# OptionsScout AI demo — {cfg.settings.data_mode} data, LLM mode {deps.llm.mode}\n")
    print(f"> {text}\n")
    for update in stream_run(graph, initial_state(text), thread):
        for node in update:
            if node == "__interrupt__":
                intr = pending_interrupt(graph, thread)
                print("Run paused for human review:", intr and intr.get("needs_clarification"))
                return 2
            print(f"  ✓ {node}", file=sys.stderr)
    state = graph.get_state(thread_config(thread)).values
    print(state.get("report_markdown", ""))
    rep = state.get("report")
    return 0 if rep is not None and rep.verification.passed and rep.risk.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="options-scout", description="Educational options screener. Not investment advice."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    demo = sub.add_parser(
        "demo", help="full agent pipeline on fixtures; prints the markdown report"
    )
    demo.add_argument("--request", default=None, help="free-text request")
    demo.add_argument("--buying-power", type=float, default=100_000)
    demo.add_argument("--risk", choices=["conservative", "balanced", "aggressive"])
    demo.add_argument("--account", choices=["cash", "margin", "portfolio_margin"])
    demo.add_argument(
        "--strategy", choices=["csp", "leaps", "both"], default="both", help="what to screen for"
    )
    demo.add_argument("--no-llm", action="store_true", help="skip LLM steps (rule-based stand-ins)")
    demo.set_defaults(func=cmd_demo)

    core = sub.add_parser(
        "demo-core", help="deterministic screeners/sizing/risk, every profile × account"
    )
    core.add_argument("--buying-power", type=float, default=100_000)
    core.add_argument("--account-value", type=float, default=None)
    core.add_argument("--risk", choices=["conservative", "balanced", "aggressive"])
    core.add_argument("--account", choices=["cash", "margin", "portfolio_margin"])
    core.add_argument("--max-positions", type=int, default=8)
    core.add_argument("tickers", nargs="*")
    core.set_defaults(func=cmd_demo_core)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
