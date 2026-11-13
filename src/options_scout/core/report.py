"""Markdown rendering of report pieces. Pure formatting: no decisions, no math beyond display."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from options_scout.core.models import (
    AllocationPlan,
    BottleneckSignal,
    Citation,
    ComplianceReport,
    GoalPlan,
    MarketRegime,
    NewsBrief,
    NewsFlag,
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
    return "n/a" if x is None else f"${x:,.0f}"


def pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def iv_rank_cell(c: OptionCandidate) -> str:
    """The rank when it comes from stored IV history; until then implied over realised vol,
    which is context and not scored (W4)."""
    if c.iv_rank_source == "history" and c.iv_rank is not None:
        return pct(c.iv_rank, 0)
    if c.iv_hv_ratio is not None:
        return f"IV/HV {c.iv_hv_ratio:.2f}×"
    return "n/a"


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
        + (f"\n\nVIX source: {r.vix_source}" if r.vix_source else "")
    )


# ------------------------------------------------- W24: what the margin path actually is
PORTFOLIO_MARGIN_NOTE = (
    "Sized with Reg T rules; your broker's risk-based (portfolio margin) requirement will differ."
)


def on_margin(account_type: str) -> bool:
    return account_type != "cash"


def put_label(account_type: str) -> str:
    """A short put in a cash account is cash-secured; on margin it is sized on the Reg T
    requirement, which is a naked put (W24)."""
    return "short put on margin (naked)" if on_margin(account_type) else "cash-secured put"


def put_bucket_label(account_type: str) -> str:
    return "Short puts on margin (naked)" if on_margin(account_type) else "CSP collateral"


def reserve_label(account_type: str) -> str:
    """Unused buying power is cash only in a cash account."""
    return "Unused buying power" if on_margin(account_type) else "Cash reserve"


def margin_label(account_type: str) -> str:
    if account_type == "portfolio_margin":
        return "Margin (Reg T rules; broker's requirement differs)"
    return "Reg T margin used"


def render_allocation(a: AllocationPlan, account_type: str = "cash") -> str:
    table = _table(
        ["Bucket", "Share", "Dollars"],
        [
            [put_bucket_label(account_type), pct(a.csp_pct, 0), money(a.csp_dollars)],
            ["LEAPS / PMCC", pct(a.leaps_pct, 0), money(a.leaps_dollars)],
            [
                "Held back (unallocated buying power)"
                if on_margin(account_type)
                else "Cash reserve",
                pct(a.cash_pct, 0),
                money(a.cash_dollars),
            ],
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
                t.ticker or "n/a",
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


def _signed(components: dict[str, float], key: str, digits: int = 2) -> str:
    v = components.get(key)
    return "n/a" if v is None else f"{v:+.{digits}f}"


def render_bottlenecks(signals: Sequence[BottleneckSignal], limit: int = 15) -> str:
    """The bottleneck board (section 4A, Phase 11): layer table, company table, evidence links
    and the thesis monitor. Reports state; never says exit, sell or take profits."""
    layers = [s for s in signals if s.ticker is None]
    if not layers:
        return "_No bottleneck board (engine disabled or no snapshot)._"
    layer_rows = [
        [
            f"{row.theme_id}/{row.layer_id}",
            row.layer_name,
            f"{row.score:.0f}",
            _signed(row.components, "tightness_z", 1),
            _signed(row.components, "price_trend"),
            _signed(row.components, "price_deceleration"),
            _signed(row.components, "supply_response_z", 1),
            f"{row.components.get('cross_source_norm', 0.0):.2f}",
            "weakening" if row.thesis_weakening else "holding",
        ]
        for row in sorted(layers, key=lambda s: -s.score)
    ]
    layer_table = _table(
        [
            "Layer",
            "Name",
            "Score",
            "Tightness z",
            "Price trend",
            "Deceleration",
            "Supply z",
            "Cross-source",
            "Thesis",
        ],
        layer_rows,
    )
    best: dict[str, BottleneckSignal] = {}  # one row per ticker: its best layer (4A.7)
    for s in signals:
        if (
            s.ticker
            and s.role == "supplier"
            and (s.ticker not in best or s.score > best[s.ticker].score)
        ):
            best[s.ticker] = s
    companies = sorted(best.values(), key=lambda s: -s.score)
    company_rows = [
        [
            s.ticker or "",
            f"{s.theme_id}/{s.layer_id}",
            f"{s.score:.0f}",
            f"{s.components.get('exposure', 0.0):.2f}",
            f"{s.components.get('priced_in', 0.0):.2f}",
            "n/a" if s.catalyst_days is None else str(s.catalyst_days),
            "yes" if s.curated else "no (not on the good-to-own list)",
            ", ".join(s.flags),
        ]
        for s in companies[:limit]
    ]
    company_table = _table(
        [
            "Ticker",
            "Layer",
            "Company score",
            "Exposure",
            "Priced in",
            "Catalyst days",
            "Curated",
            "Flags",
        ],
        company_rows,
    )
    monitor: list[str] = []
    for row in sorted(layers, key=lambda s: (s.theme_id, s.layer_id)):
        state = "**thesis weakening**" if row.thesis_weakening else "thesis holding"
        monitor.append(f"- **{row.theme_id}/{row.layer_id}** ({state}): {row.thesis}")
        for f in row.falsifiers:
            obs = "n/a" if f.observed is None else f"{f.observed:.2f}"
            monitor.append(
                f"  - `{f.signal} {f.op} {f.value:g}` for {f.snapshots} snapshot(s): {f.state} "
                f"(observed {obs})"
            )
        for e in row.evidence[:3]:
            who = f" {e.filer_ticker}" if e.filer_ticker else ""
            link = f" ([{e.source}]({e.url}))" if e.url else f" ({e.source})"
            label = f" · {e.label}" if e.label else ""
            monitor.append(f"  - {e.kind}{who}, {e.date.isoformat()}: “{e.excerpt}”{link}{label}")
    return (
        "_Secondary signal: re-orders, never adds. Company score = layer score × exposure; a "
        "ticker without a row takes the neutral 50 in the ranking. Scores and flags describe the "
        "state of a supply constraint; they are not forecasts._\n\n"
        + layer_table
        + "\n\n"
        + company_table
        + "\n\n**Thesis monitor and evidence:**\n"
        + "\n".join(monitor)
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
                        q.name or "n/a",
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


def earnings_cell(c: OptionCandidate) -> str:
    """Earnings column: yes, no or unknown (W5: a missing date is never shown as "no")."""
    if c.earnings_before_expiry:
        return "yes"
    if "earnings_unknown" in c.flags:
        return "unknown"
    return "no (estimated)" if "earnings_estimated" in c.flags else "no"


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
            iv_rank_cell(c),
            earnings_cell(c),
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
                "IV rank or IV/HV",
                "Earnings",
                "Flags",
            ],
            rows,
        )
        + "\n\nIV/HV: no IV rank yet (fewer than 30 stored IV snapshots); showing implied over "
        "realised volatility. Options usually trade above realised volatility, so it is context "
        "and does not affect the score."
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
                pct(c.carry_per_year_pct),
                f"{c.breakeven:.2f}",
                f"{c.open_interest:,}/{pct(c.spread_pct, 0)}",
                (
                    f"{p.short_call.strike:g}C {p.short_call.expiry.isoformat()} "
                    f"Δ{p.short_call.delta:.2f} mid {p.short_call.mid:.2f} "
                    f"(net Δ {p.net_delta:.2f}, safety +{p.safety_margin:.2f})"
                    if p
                    else "n/a"
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
            "Carry/yr",
            "Breakeven",
            "OI / spread",
            "PMCC short call",
            "Flags",
        ],
        rows,
    )


def render_portfolio(
    port: SizedPortfolio,
    ranked: Sequence[RankedCandidate] | None = None,
    warnings: Sequence[str] = (),
    account_type: str = "cash",
) -> str:
    """The sized positions, led by the sizer's warnings (W6: one-stock portfolio, ranking not
    followed, account too small), then totals and the skipped candidates with the account size
    each would fit from."""
    lead = "\n>\n".join(f"> ⚠️ {w}" for w in warnings) + "\n\n" if warnings else ""
    if not port.positions:
        body = (
            "_Nothing sized: this account is too small for the top-ranked candidates._"
            if port.account_too_small
            else "_No positions could be sized under the constraints._"
        )
    else:
        score = {r.candidate.id: r for r in ranked or []}
        rows = [
            [
                p.candidate_id,
                put_label(account_type) if p.strategy == "csp" else p.strategy,
                str(p.contracts),
                f"{p.strike:g}",
                p.expiry.isoformat(),
                money(p.capital_used),
                money(p.margin_used) if p.margin_used else "n/a",
                money(p.realistic_loss),
                f"{p.dollar_delta:,.0f}",
                f"{p.premium:,.0f}",
                f"{score[p.candidate_id].final_score:.2f}" if p.candidate_id in score else "n/a",
                p.pmcc_short_call_id or "n/a",
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
            [margin_label(account_type), money(t.margin_used)],
            ["LEAPS net debit", money(t.leaps_cost)],
            ["Loss at -30% (all positions)", money(t.realistic_loss)],
            ["Net dollar delta", f"{t.dollar_delta:,.0f}"],
            ["Net premium (income − debits)", f"{t.premium_income:,.0f}"],
            [reserve_label(account_type), money(t.cash_reserve)],
            [
                "Cash needed if every put is assigned"
                + (" (+ LEAPS debits)" if t.leaps_cost > 0 else ""),
                money(t.assignment_cash),
            ],
        ],
    )
    if account_type == "portfolio_margin":
        totals += f"\n\n_{PORTFOLIO_MARGIN_NOTE}_"
    skipped = ""
    if port.skipped:
        shown = port.skipped[:8]
        skipped = (
            "\n\n<details><summary>Skipped candidates ("
            + str(len(port.skipped))
            + ")</summary>\n\n"
            + "\n".join(f"- {s}{_fits_from(s, port)}" for s in shown)
            + ("\n- …" if len(port.skipped) > len(shown) else "")
            + "\n\n</details>"
        )
    return lead + body + "\n\n" + totals + skipped


def _fits_from(line: str, port: SizedPortfolio) -> str:
    """ " · fits from $683,427" for a size-limited skip (W6), else nothing."""
    cid = line.split(":", 1)[0]
    d = next((d for d in port.skipped_detail if d.candidate_id == cid), None)
    if d is None:
        return ""
    if d.min_account_value is None:
        return " · no account size fits (no budget for this strategy)"
    return f" · fits from {money(d.min_account_value)}"


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
    stress_title = (
        "**Stress test (instant move, each leg repriced with BSM before and after; the IV shock "
        "is the figure for a 30-day option and shrinks as √(30 / DTE) for longer-dated legs):**"
    )
    return f"{status}\n\n{checks}\n\n{stress_title}\n\n{stress}\n\n{warn}"


def render_news(briefs: Sequence[NewsBrief], flags: Sequence[NewsFlag]) -> str:
    """The News Desk's per-ticker briefs and the calendar flags on candidates (Phase 12)."""
    if not briefs and not flags:
        return "_No headlines were fetched for this run._"
    lines: list[str] = []
    for b in briefs:
        if not b.items:
            lines.append(f"- **{b.ticker}**: no headlines in the lookback window")
            continue
        head = b.items[0]
        lines.append(
            f"- **{b.ticker}** ({len(b.items)} headline(s)): “{head.item.title}” — "
            f"{head.item.source}, {head.item.published_at:%Y-%m-%d}, {head.category}, "
            f"{head.relevance} relevance"
            + (f", sentiment {head.sentiment:+.2f}" if head.sentiment is not None else "")
            + (", stale" if head.stale else "")
        )
    if flags:
        lines.append("")
        lines.append(
            _table(
                ["Candidate", "Flag", "Event date", "Detail"],
                [
                    [
                        f.candidate_id,
                        f.flag,
                        f.event_date.isoformat() if f.event_date else "unknown",
                        f.detail,
                    ]
                    for f in flags
                ],
            )
        )
    lines.append("")
    lines.append("_Headlines never change the ranking; they flag what to read before trading._")
    return "\n".join(lines)


def render_goal(plan: GoalPlan | None) -> str:
    """The Goal Planning agent's computed plan (Phase 12): verdict, levers, projection, FIRE."""
    if plan is None:
        return "_No goal on this run._"
    g, v, y = plan.goal, plan.feasibility, plan.yield_estimate
    status = {"fits": "fits", "stretch": "stretch", "does_not_fit": "does not fit"}[v.status]
    lines = [
        f"**{g.kind} goal: {status}.** Required return "
        f"{pct(v.required_return) if v.required_return is not None else 'n/a'}, expected "
        f"yield {pct(v.available_return)}, profile cap {pct(v.profile_cap, 0)} "
        f"(gross yield {pct(y.gross_yield)} with every premium kept, cash at "
        f"{pct(y.cash_rate, 2)}; assumes {pct(y.expected_drift, 0)} drift and realised vol at "
        f"{y.realised_to_implied:.2f} × implied).",
        "",
        _table(
            ["Lever", "Value", "Detail"],
            [
                [
                    lever.name.replace("_", " "),
                    "n/a" if lever.value is None else f"{lever.value:,.1f}",
                    lever.detail,
                ]
                for lever in v.levers
            ],
        ),
        "",
        _table(
            [
                "Path",
                "Real return",
                f"Balance after {plan.projection[0].points[-1].year:g} years (today's $)",
            ],
            [[p.label, pct(p.annual_return), money(p.points[-1].balance)] for p in plan.projection],
        )
        if plan.projection
        else "",
    ]
    if plan.fire is not None:
        f = plan.fire
        lines += [
            "",
            f"**{f.variant} FIRE:** expenses {money(f.expense_target)} a year at a "
            f"{pct(f.withdrawal_rate)} withdrawal rate give a FIRE number of "
            f"{money(f.fire_number)}; "
            f"years to FI at {pct(f.real_return)} real "
            f"({pct(f.assumed_return)} nominal less {pct(f.inflation)} inflation): "
            f"{'not within the horizon cap' if f.years_to_fi is None else f'{f.years_to_fi:.1f}'}; "
            f"coast balance {money(f.coast_balance)}; income coverage "
            f"{pct(f.income_coverage, 0) if f.income_coverage is not None else 'n/a'}.",
        ]
        lines += [f"- {n}" for n in f.notes]
    lines += ["", *[f"- {a}" for a in plan.assumptions]]
    return "\n".join(lines)


def render_sources(citations: Sequence[Citation]) -> str:
    """Footnote list of the knowledge-base sources the explanation cites (``[Sn]`` tags)."""
    if not citations:
        return "_No knowledge-base sources were cited in this explanation._"
    lines = []
    for c in citations:
        where = f" ({c.url})" if c.url else ""
        lines.append(f"- **[{c.tag}]** {c.title} — {c.kind}{where}  \n  “{c.quote}”")
    return "\n".join(lines)


def render_compliance(
    report: ComplianceReport | None, audit_log: Sequence[ComplianceReport]
) -> str:
    """The eight checks (13.1) with their outcome, and the run's audit trail."""
    if report is None:
        return "_No compliance report._"
    lines = [
        f"{'PASS' if report.passed else 'FAIL'} · audit `{report.audit_id}` · "
        f"{report.text_kind} · attempt {report.attempts}",
        "",
    ]
    for c in report.checks:
        mark = "✓" if c.passed else ("⚠" if c.severity == "warn" else "✗")
        lines.append(f"- {mark} `{c.name}`: {c.detail}")
    if len(audit_log) > 1:
        trail = " → ".join(f"{e.audit_id} ({'pass' if e.passed else 'fail'})" for e in audit_log)
        lines += ["", f"Audit trail: {trail}"]
    return "\n".join(lines)
