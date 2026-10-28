"""Markdown rendering of report pieces. Pure formatting: no decisions, no math beyond display."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from options_scout.core.models import (
    AllocationPlan,
    MarketRegime,
    OptionCandidate,
    PMCCCandidate,
    QualityCheck,
    RankedCandidate,
    RiskReport,
    SizedPortfolio,
    TrendSignal,
    UserProfile,
)


def money(x: float | None) -> str:
    return "—" if x is None else f"${x:,.0f}"


def pct(x: float | None, digits: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def render_profile(p: UserProfile) -> str:
    return (
        f"**Buying power** {money(p.buying_power)} · **Account value** {money(p.account_value)} · "
        f"**Account** {p.account_type} · **Risk** {p.risk_profile} · "
        f"**Strategies** {', '.join(sorted(p.strategies))} · **Max positions** {p.max_positions}"
        + (f" · **Watchlist** {', '.join(p.watchlist)}" if p.watchlist else "")
        + (f" · **Excluded** {', '.join(p.exclude)}" if p.exclude else "")
    )


def render_regime(r: MarketRegime) -> str:
    return (
        f"VIX {r.vix:.2f} ({r.vix_percentile:.0f}th percentile, {r.label.replace('_', ' ')}), "
        f"risk-free rate {pct(r.risk_free_rate, 2)} ({r.source} data)."
    )


def render_allocation(a: AllocationPlan) -> str:
    table = _table(
        ["Bucket", "Share", "Dollars"],
        [
            ["CSP collateral", pct(a.csp_pct, 0), money(a.csp_dollars)],
            ["LEAPS / PMCC", pct(a.leaps_pct, 0), money(a.leaps_dollars)],
            ["Cash reserve", pct(a.cash_pct, 0), money(a.cash_dollars)],
        ],
    )
    return table + "\n\n" + "\n".join(f"- {line}" for line in a.rationale)


def render_trends(trends: Sequence[TrendSignal], limit: int = 10) -> str:
    if not trends:
        return "_No trend signals (social engine disabled or no data)._"
    rows = []
    for t in trends[:limit]:
        flags = ", ".join(t.flags) if t.flags else ""
        rows.append(
            [
                t.entity,
                t.entity_type,
                t.ticker or "—",
                "yes" if t.investable else "no",
                f"{t.score:.0f}",
                f"{t.components.get('velocity_z', 0):+.1f}",
                f"{t.components.get('coverage_gap', 0):+.1f}",
                str(len(t.evidence)),
                flags,
            ]
        )
    return _table(
        [
            "Entity",
            "Type",
            "Ticker",
            "Investable",
            "Score",
            "Velocity z",
            "Coverage gap",
            "Evidence",
            "Flags",
        ],
        rows,
    )


def render_quality(checks: Sequence[QualityCheck]) -> str:
    if not checks:
        return "_No tickers were evaluated._"
    kept = sorted((q for q in checks if q.passed), key=lambda q: -q.score)
    dropped = [q for q in checks if not q.passed]
    parts: list[str] = []
    if kept:
        parts.append(
            _table(
                [
                    "Ticker",
                    "Name",
                    "Sector",
                    "Quality",
                    "30d vol",
                    "Below 90d high",
                    "Why it's on the list",
                ],
                [
                    [
                        q.ticker,
                        q.name or "—",
                        q.sector,
                        f"{q.score * 100:.0f}",
                        pct(q.metrics.get("hv30"), 0),
                        pct(q.metrics.get("drawdown_90d"), 0),
                        q.why_good_to_own or ("_user-added, not on the curated list_"),
                    ]
                    for q in kept
                ],
            )
        )
    else:
        parts.append("_No ticker passed the quality gate._")
    if dropped:
        parts.append(
            "**Excluded by the quality gate:**\n"
            + "\n".join(f"- {q.ticker}: {'; '.join(q.reasons)}" for q in dropped)
        )
    return "\n\n".join(parts)


def render_csp(cands: Sequence[OptionCandidate], limit: int = 15) -> str:
    if not cands:
        return "_No CSP candidates met the criteria._"
    rows = [
        [
            c.id,
            f"{c.strike:g}",
            c.expiry.isoformat(),
            str(c.dte),
            f"{c.delta:.2f}",
            f"{c.mid:.2f}",
            money(c.collateral),
            money(c.margin_req),
            pct(c.annualized_return),
            pct(c.prob_otm, 0),
            f"{c.open_interest:,}/{pct(c.spread_pct, 0)}",
            pct(c.iv_rank, 0) + ("*" if c.iv_rank_source == "hv_proxy" else ""),
            "yes" if c.earnings_before_expiry else "no",
            ", ".join(f for f in c.flags if f not in {"iv_rank_is_hv_proxy"}),
        ]
        for c in cands[:limit]
    ]
    return (
        _table(
            [
                "ID",
                "Strike",
                "Expiry",
                "DTE",
                "Delta",
                "Mid",
                "Collateral",
                "Reg T margin",
                "Ann. return",
                "P(OTM)",
                "OI / spread",
                "IV rank",
                "Earnings",
                "Flags",
            ],
            rows,
        )
        + "\n\n\\* IV rank from HV proxy (fewer than 30 stored IV snapshots)."
    )


def render_leaps(
    cands: Sequence[OptionCandidate], pairs: Sequence[PMCCCandidate], limit: int = 12
) -> str:
    if not cands:
        return "_No LEAPS candidates met the criteria._"
    pair_by_leaps = {p.leaps.id: p for p in pairs}
    rows = []
    for c in cands[:limit]:
        p = pair_by_leaps.get(c.id)
        rows.append(
            [
                c.id,
                f"{c.strike:g}",
                c.expiry.isoformat(),
                str(c.dte),
                f"{c.delta:.2f}",
                f"{c.mid:.2f}",
                pct(c.extrinsic_per_year_pct),
                f"{c.breakeven:.2f}",
                f"{c.open_interest:,}/{pct(c.spread_pct, 0)}",
                (
                    f"{p.short_call.strike:g}C {p.short_call.expiry.isoformat()} "
                    f"Δ{p.short_call.delta:.2f} mid {p.short_call.mid:.2f} "
                    f"(net Δ {p.net_delta:.2f}, safety +{p.safety_margin:.2f})"
                    if p
                    else "—"
                ),
                ", ".join(f for f in c.flags if f not in {"iv_rank_is_hv_proxy"}),
            ]
        )
    return _table(
        [
            "ID",
            "Strike",
            "Expiry",
            "DTE",
            "Delta",
            "Mid",
            "Extrinsic/yr",
            "Breakeven",
            "OI / spread",
            "PMCC short call",
            "Flags",
        ],
        rows,
    )


def render_portfolio(port: SizedPortfolio, ranked: Sequence[RankedCandidate] | None = None) -> str:
    if not port.positions:
        body = "_No positions could be sized under the constraints._"
    else:
        score = {r.candidate.id: r for r in ranked or []}
        rows = [
            [
                p.candidate_id,
                p.strategy,
                str(p.contracts),
                f"{p.strike:g}",
                p.expiry.isoformat(),
                money(p.capital_used),
                money(p.margin_used) if p.margin_used else "—",
                money(p.realistic_loss),
                f"{p.dollar_delta:,.0f}",
                f"{p.premium:,.0f}",
                f"{score[p.candidate_id].final_score:.2f}" if p.candidate_id in score else "—",
                p.pmcc_short_call_id or "—",
            ]
            for p in port.positions
        ]
        body = _table(
            [
                "Candidate",
                "Strategy",
                "Contracts",
                "Strike",
                "Expiry",
                "Capital",
                "Margin",
                "Loss @ -30%",
                "$ delta",
                "Premium",
                "Score",
                "PMCC short call",
            ],
            rows,
        )
    t = port.totals
    totals = _table(
        ["Metric", "Value"],
        [
            ["Short-put notional", money(t.short_put_notional)],
            [
                "Capital used",
                f"{money(t.capital_used)} ({pct(t.buying_power_used_pct, 0)} of buying power)",
            ],
            ["Reg T margin used", money(t.margin_used)],
            ["LEAPS net debit", money(t.leaps_cost)],
            ["Loss at -30% (all positions)", money(t.realistic_loss)],
            ["Net dollar delta", f"{t.dollar_delta:,.0f}"],
            ["Net premium (income − debits)", f"{t.premium_income:,.0f}"],
            ["Cash reserve", money(t.cash_reserve)],
        ],
    )
    skipped = ""
    if port.skipped:
        shown = port.skipped[:8]
        skipped = (
            "\n\n<details><summary>Skipped candidates ("
            + str(len(port.skipped))
            + ")</summary>\n\n"
            + "\n".join(f"- {s}" for s in shown)
            + ("\n- …" if len(port.skipped) > len(shown) else "")
            + "\n\n</details>"
        )
    return body + "\n\n" + totals + skipped


def render_risk(r: RiskReport) -> str:
    checks = _table(
        ["Constraint", "Value", "Limit", "Status"],
        [
            [c.name, f"{c.value:.3f}", f"{c.limit:.3f}", "PASS" if c.passed else "FAIL"]
            for c in r.checks
        ],
    )
    stress = _table(
        ["Market move", "IV shock", "P&L", "% of account"],
        [
            [pct(s.shock, 0), f"+{pct(s.iv_shock, 0)}", f"{s.pnl:,.0f}", pct(s.pnl_pct_account)]
            for s in r.stress
        ],
    )
    warn = "\n".join(f"- ⚠️ {w}" for w in r.warnings) if r.warnings else "_No warnings._"
    status = "**All constraints pass.**" if r.passed else "**Constraint failures present.**"
    stress_title = "**Stress test (instant move, repriced with BSM):**"
    return f"{status}\n\n{checks}\n\n{stress_title}\n\n{stress}\n\n{warn}"
