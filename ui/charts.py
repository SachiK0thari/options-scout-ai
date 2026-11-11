"""Every chart in the app, one function each, returning a Plotly figure styled by ``ui.theme``.

Charts never compute finance: they take report objects or the output of ``ui.compute``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta

import plotly.graph_objects as go

from options_scout.core.models import (
    BottleneckSignal,
    GoalPlan,
    HoldingsAnalysis,
    OptionCandidate,
    PostAssignment,
    QualityCheck,
    StressResult,
    TrendSignal,
)
from ui import theme

AGENT_LABELS = {
    "orchestrator_agent": "Orchestrator",
    "market_intelligence_agent": "2 · Market Intelligence",
    "market_data_agent": "1 · Market Data",
    "strategy_agent": "3 · Strategy",
    "portfolio_agent": "4 · Portfolio",
    "risk_agent": "5 · Risk",
    "goal_planning_agent": "7 · Goal Planning",
    "news_desk_agent": "8 · News Desk",
    "tax_agent": "9 · Tax & Accounts",
    "education_agent": "6 · Education",
    "compliance_agent": "C · Compliance",
}


# ------------------------------------------------------------------------------ quality
def quality_bar(checks: Sequence[QualityCheck]) -> go.Figure:
    rows = sorted(checks, key=lambda q: (q.passed, q.score))
    fig = go.Figure()
    for passed, label, color in ((True, "passed", theme.GOOD), (False, "excluded", theme.CRITICAL)):
        sub = [q for q in rows if q.passed == passed]
        if not sub:
            continue
        fig.add_bar(
            name=label,
            orientation="h",
            y=[q.ticker for q in sub],
            x=[round(q.score * 100) for q in sub],
            marker={"color": color, "line": {"width": 0}},
            text=[f"{label} · {round(q.score * 100)}" for q in sub],
            textposition="outside",
            cliponaxis=False,
            customdata=[("; ".join(q.reasons) or q.why_good_to_own or "") for q in sub],
            hovertemplate="%{y}: quality %{x}<br>%{customdata}<extra></extra>",
        )
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(range=[0, 115])
    return theme.style(
        fig,
        "Quality score by ticker",
        "Quality score (0–100)",
        "",
        height=max(260, 34 * len(rows) + 90),
    )


# --------------------------------------------------------------------------- candidates
def delta_return_scatter(cands: Sequence[OptionCandidate]) -> go.Figure:
    colors = theme.color_map([c.ticker for c in cands])
    max_oi = max((c.open_interest for c in cands), default=1) or 1
    fig = go.Figure()
    for ticker, color in colors.items():
        sub = [c for c in cands if c.ticker == ticker]
        fig.add_scatter(
            name=ticker,
            mode="markers+text",
            x=[abs(c.delta) for c in sub],
            y=[(c.annualized_return or 0.0) * 100 for c in sub],
            text=[ticker] * len(sub),
            textposition="top center",
            marker={
                "color": color,
                "size": [10 + 22 * (c.open_interest / max_oi) for c in sub],
                "line": {"color": "#ffffff", "width": 2},
            },
            customdata=[
                [c.id, c.open_interest, c.prob_otm * 100, c.mid, c.strike, str(c.expiry)]
                for c in sub
            ],
            hovertemplate=(
                "%{customdata[0]}<br>strike %{customdata[4]} · expiry %{customdata[5]}"
                "<br>|delta| %{x:.2f} · annualized %{y:.1f}%<br>open interest %{customdata[1]:,}"
                " · prob. OTM %{customdata[2]:.0f}% · mid $%{customdata[3]:.2f}<extra></extra>"
            ),
        )
    return theme.style(
        fig,
        "Cash-secured puts: delta vs annualized return",
        "|Delta| (chance of assignment, roughly)",
        "Annualized return on collateral (%)",
    )


def strike_ladder(cands: Sequence[OptionCandidate], spot: float) -> go.Figure:
    sub = sorted(cands, key=lambda c: c.strike)
    fig = go.Figure()
    fig.add_scatter(
        name="premium (mid)",
        mode="lines+markers",
        x=[c.strike for c in sub],
        y=[c.mid for c in sub],
        line={"color": theme.ACCENT, "width": 2},
        marker={"size": 9, "color": theme.ACCENT, "line": {"color": "#ffffff", "width": 2}},
        customdata=[[c.delta, c.annualized_return or 0.0, str(c.expiry), c.dte] for c in sub],
        hovertemplate=(
            "strike %{x} · mid $%{y:.2f}<br>delta %{customdata[0]:.2f} · annualized "
            "%{customdata[1]:.1%}<br>expiry %{customdata[2]} (%{customdata[3]} days)<extra></extra>"
        ),
    )
    fig.add_vline(
        x=spot,
        line={"color": theme.MUTED, "width": 1},
        annotation={"text": f"spot ${spot:,.2f}", "font": {"color": theme.MUTED}},
        annotation_position="top left",
    )
    return theme.style(
        fig, "Premium by strike", "Strike ($)", "Premium per share ($, mid)", legend=False
    )


# ------------------------------------------------------------------------------ portfolio
def allocation_donut(parts: Mapping[str, float]) -> go.Figure:
    names = [k for k, v in parts.items() if v > 0]
    colors = theme.color_map(names)
    fig = go.Figure(
        go.Pie(
            labels=names,
            values=[parts[k] for k in names],
            hole=0.58,
            sort=False,
            marker={"colors": [colors[n] for n in names], "line": {"color": "#ffffff", "width": 2}},
            textinfo="label+percent",
            hovertemplate="%{label}: $%{value:,.0f} (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    return theme.style(fig, "How buying power is split", "", "", height=320, legend=False)


def stress_bars(stress: Sequence[StressResult]) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=[f"{s.shock:+.0%}" for s in stress],
            y=[s.pnl for s in stress],
            marker={
                "color": [theme.NEGATIVE if s.pnl < 0 else theme.POSITIVE for s in stress],
                "line": {"width": 0},
            },
            text=[f"${s.pnl:,.0f}" for s in stress],
            textposition="outside",
            cliponaxis=False,
            customdata=[s.pnl_pct_account * 100 for s in stress],
            hovertemplate="market %{x}: P&L $%{y:,.0f} (%{customdata:.1f}% of account)<extra></extra>",
        )
    )
    fig.update_xaxes(type="category")
    return theme.style(
        fig,
        "Portfolio stress test (IV shock on down moves, scaled by tenor)",
        "Instant market move",
        "P&L ($)",
        legend=False,
    )


def stress_by_position_bars(
    per_position: Mapping[str, Mapping[float, float]], shocks: Sequence[float]
) -> go.Figure:
    fig = go.Figure()
    ids = list(per_position)
    for i, shock in enumerate(shocks):
        fig.add_bar(
            name=f"{shock:+.0%}",
            x=ids,
            y=[per_position[cid].get(shock, 0.0) for cid in ids],
            marker={"color": theme.SEQUENTIAL[min(i + 1, len(theme.SEQUENTIAL) - 1)]},
            hovertemplate="%{x}<br>market " + f"{shock:+.0%}" + ": P&L $%{y:,.0f}<extra></extra>",
        )
    fig.update_layout(barmode="group")
    return theme.style(fig, "Stress P&L per position", "Position", "P&L ($)", height=380)


def portfolio_payoff(points: Sequence[tuple[float, float]]) -> go.Figure:
    xs = [m * 100 for m, _ in points]
    ys = [p for _, p in points]
    fig = go.Figure()
    fig.add_scatter(
        x=xs,
        y=ys,
        mode="lines",
        name="P&L at expiry",
        line={"color": theme.ACCENT, "width": 2},
        hovertemplate="market %{x:+.0f}%: P&L $%{y:,.0f}<extra></extra>",
    )
    fig.add_hline(y=0, line={"color": theme.AXIS, "width": 1})
    return theme.style(
        fig,
        "Portfolio payoff at expiry vs a uniform market move",
        "Move in every underlying (%)",
        "P&L ($)",
        legend=False,
    )


def loss_meter(value_pct: float, limit_pct: float, title: str) -> go.Figure:
    """Bullet meter: a single ratio against its limit, same hue as the sequential ramp."""
    top = max(limit_pct * 1.5, value_pct * 1.15, 0.01)
    fig = go.Figure(
        go.Indicator(
            mode="number+gauge",
            value=value_pct * 100,
            number={"suffix": "%", "font": {"size": 28}},
            gauge={
                "shape": "bullet",
                "axis": {"range": [0, top * 100], "ticksuffix": "%"},
                "bar": {"color": theme.NEGATIVE if value_pct > limit_pct else theme.ACCENT},
                "bgcolor": "rgba(0,0,0,0)",
                "borderwidth": 0,
                "steps": [{"range": [0, limit_pct * 100], "color": "#e1e0d9"}],
                "threshold": {
                    "line": {"color": theme.CRITICAL, "width": 3},
                    "thickness": 0.9,
                    "value": limit_pct * 100,
                },
            },
            domain={"x": [0.0, 1], "y": [0.2, 0.8]},
        )
    )
    fig.update_layout(
        title={"text": title, "x": 0.0, "xanchor": "left"},
        height=170,
        margin={"l": 8, "r": 24, "t": 48, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ----------------------------------------------------------------------------- payoff (Learn)
def payoff_diagram(
    points: Sequence[tuple[float, float]],
    breakevens: Sequence[float],
    spot: float,
    title: str,
) -> go.Figure:
    xs = [s for s, _ in points]
    ys = [p for _, p in points]
    fig = go.Figure()
    fig.add_scatter(
        x=xs,
        y=[max(y, 0.0) for y in ys],
        mode="lines",
        line={"width": 0},
        fill="tozeroy",
        fillcolor="rgba(42,120,214,0.12)",
        hoverinfo="skip",
        showlegend=False,
    )
    fig.add_scatter(
        x=xs,
        y=[min(y, 0.0) for y in ys],
        mode="lines",
        line={"width": 0},
        fill="tozeroy",
        fillcolor="rgba(208,59,59,0.12)",
        hoverinfo="skip",
        showlegend=False,
    )
    fig.add_scatter(
        x=xs,
        y=ys,
        mode="lines",
        name="P&L at expiry",
        line={"color": theme.ACCENT, "width": 2},
        hovertemplate="stock at $%{x:,.2f}: P&L $%{y:,.0f}<extra></extra>",
    )
    fig.add_hline(y=0, line={"color": theme.AXIS, "width": 1})
    fig.add_vline(
        x=spot,
        line={"color": theme.MUTED, "width": 1},
        annotation={"text": f"spot ${spot:,.2f}", "font": {"color": theme.MUTED}},
        annotation_position="top left",
    )
    if breakevens:
        fig.add_scatter(
            x=list(breakevens),
            y=[0.0] * len(breakevens),
            mode="markers+text",
            name="breakeven",
            text=[f"breakeven ${b:,.2f}" for b in breakevens],
            textposition="bottom right",
            marker={"color": theme.ACCENT, "size": 10, "line": {"color": "#ffffff", "width": 2}},
            hovertemplate="breakeven $%{x:,.2f}<extra></extra>",
        )
    return theme.style(
        fig, title, "Stock price at expiry ($)", "P&L per position ($)", legend=False
    )


# -------------------------------------------------------------------------------- trends
def trend_velocity(trends: Sequence[TrendSignal], limit: int = 8) -> go.Figure:
    top = list(trends)[:limit]
    fig = go.Figure()
    fig.add_bar(
        name="baseline (weekly mean, prior 8 weeks)",
        x=[t.entity for t in top],
        y=[t.components.get("mentions_baseline_weekly_mean", 0.0) for t in top],
        marker={"color": theme.MUTED},
        hovertemplate="%{x}<br>baseline %{y:.1f} mentions / week<extra></extra>",
    )
    fig.add_bar(
        name="last 7 days",
        x=[t.entity for t in top],
        y=[t.components.get("mentions_recent", 0.0) for t in top],
        marker={"color": theme.ACCENT},
        customdata=[t.components.get("velocity_z", 0.0) for t in top],
        hovertemplate="%{x}<br>recent %{y:.0f} mentions · velocity z %{customdata:.2f}<extra></extra>",
    )
    fig.update_layout(barmode="group")
    return theme.style(
        fig, "Mention velocity: last week vs baseline", "Entity", "Mentions (weighted count)"
    )


def per_source_z(trends: Sequence[TrendSignal], limit: int = 6) -> go.Figure:
    top = list(trends)[:limit]
    sources = ["reddit", "x", "wikipedia", "google_trends", "news"]
    colors = theme.color_map(sources)
    fig = go.Figure()
    for src in sources:
        key = f"{src}_z"
        if not any(key in t.components for t in top):
            continue
        fig.add_bar(
            name=src.replace("_", " "),
            x=[t.entity for t in top],
            y=[t.components.get(key, 0.0) for t in top],
            marker={"color": colors[src]},
            hovertemplate="%{x} · " + src + ": z %{y:.2f}<extra></extra>",
        )
    fig.update_layout(barmode="group")
    return theme.style(fig, "Velocity z-score per source", "Entity", "z-score (own series)")


def zscore_components(signal: TrendSignal) -> go.Figure:
    keys = [
        ("velocity_z", "velocity z"),
        ("acceleration_norm", "acceleration"),
        ("sentiment", "sentiment"),
        ("purchase_intent_rate", "purchase intent"),
        ("cross_source_norm", "cross-source confirmation"),
        ("coverage_gap", "coverage gap"),
        ("materiality", "materiality"),
        ("novelty_penalty", "novelty penalty (−)"),
        ("stock_hype_penalty", "stock-hype penalty (−)"),
    ]
    labels = [lab for k, lab in keys if k in signal.components]
    values = [
        -signal.components[k] if k.endswith("penalty") else signal.components[k]
        for k, _ in keys
        if k in signal.components
    ]
    fig = go.Figure(
        go.Bar(
            orientation="h",
            y=labels,
            x=values,
            marker={"color": [theme.NEGATIVE if v < 0 else theme.POSITIVE for v in values]},
            text=[f"{v:+.2f}" for v in values],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{x:+.2f}<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed")
    return theme.style(
        fig,
        f"Score components for {signal.entity}",
        "Contribution before weighting (penalties shown negative)",
        "",
        height=380,
        legend=False,
    )


def sentiment_intent_scatter(
    trends: Sequence[TrendSignal], curated: set[str], label_top: int = 8
) -> go.Figure:
    labelled = {t.entity for t in sorted(trends, key=lambda t: -t.score)[:label_top]}
    fig = go.Figure()
    groups = (
        ("on the good-to-own list", theme.ACCENT, [t for t in trends if t.ticker in curated]),
        ("not investable here", theme.MUTED, [t for t in trends if t.ticker not in curated]),
    )
    for name, color, sub in groups:
        if not sub:
            continue
        fig.add_scatter(
            name=name,
            mode="markers+text",
            x=[t.components.get("sentiment", 0.0) for t in sub],
            y=[t.components.get("purchase_intent_rate", 0.0) * 100 for t in sub],
            text=[t.entity if t.entity in labelled else "" for t in sub],
            hovertext=[t.entity for t in sub],
            textposition="top center",
            marker={
                "color": color,
                "size": [8 + t.score / 5 for t in sub],
                "line": {"color": "#ffffff", "width": 2},
            },
            customdata=[[t.ticker or "private", t.score] for t in sub],
            hovertemplate=(
                "%{hovertext} (%{customdata[0]})<br>sentiment %{x:.2f} · purchase intent %{y:.0f}%"
                "<br>trend score %{customdata[1]:.0f}<extra></extra>"
            ),
        )
    fig.update_xaxes(range=[-1.05, 1.05])
    return theme.style(
        fig,
        "Sentiment vs purchase intent (size = trend score)",
        "Mean sentiment (−1 … +1)",
        "Mentions with purchase intent (%)",
    )


# ---------------------------------------------------------------------------- bottlenecks
def bottleneck_mentions(layer: BottleneckSignal, recent_days: int) -> go.Figure:
    """Tightening (up) and easing (down) mentions per day for one layer, with the recent window
    the tightness z-score reads shaded (Phase 11, section 4A.7)."""
    tight = layer.mentions.get("tightening", [])
    ease = layer.mentions.get("easing", [])
    fig = go.Figure()
    fig.add_bar(
        name="tightening",
        x=[p.day for p in tight],
        y=[p.value for p in tight],
        marker={"color": theme.POSITIVE, "line": {"width": 0}},
        hovertemplate="%{x}<br>tightening mentions %{y:g}<extra></extra>",
    )
    fig.add_bar(
        name="easing (new supply, lower prices)",
        x=[p.day for p in ease],
        y=[-p.value for p in ease],
        marker={"color": theme.NEGATIVE, "line": {"width": 0}},
        customdata=[p.value for p in ease],
        hovertemplate="%{x}<br>easing mentions %{customdata:g}<extra></extra>",
    )
    end = layer.as_of.date()
    start = end - timedelta(days=recent_days)
    # plotly cannot place a shape annotation on a date axis, so the label is its own annotation
    fig.add_vrect(x0=start, x1=end, fillcolor="rgba(42,120,214,0.08)", line={"width": 0})
    fig.add_annotation(
        x=start.isoformat(),
        y=1.0,
        yref="paper",
        text=f"last {recent_days} days",
        showarrow=False,
        xanchor="left",
        yanchor="top",
        font={"color": theme.MUTED},
    )
    fig.add_hline(y=0, line={"color": theme.AXIS, "width": 1})
    fig.update_layout(barmode="relative")
    z = layer.components.get("tightness_z")
    z_text = "" if z is None else f" · tightness z {z:+.1f}"
    return theme.style(
        fig,
        f"Tightening vs easing mentions: {layer.layer_name}{z_text}",
        "Day",
        "Weighted mentions (easing shown below zero)",
    )


def bottleneck_price_series(
    layer: BottleneckSignal, labels: Mapping[str, str], window_days: int
) -> go.Figure:
    """Each configured price series of a layer rebased to 100 at the start of the previous slope
    window, with the boundary between the two windows the deceleration penalty compares marked."""
    end = layer.as_of.date()
    boundary = end - timedelta(days=window_days)
    first_day = end - timedelta(days=2 * window_days)
    keys = list(layer.series)
    colors = theme.color_map(keys)
    fig = go.Figure()
    for key in keys:
        pts = sorted(layer.series[key], key=lambda p: p.day)
        if not pts:
            continue
        base_pt = next((p for p in pts if p.day >= first_day), pts[0])
        base = base_pt.value or 1.0
        fig.add_scatter(
            name=labels.get(key, key),
            mode="lines+markers",
            x=[p.day for p in pts],
            y=[100.0 * p.value / base for p in pts],
            line={"color": colors[key], "width": 2},
            marker={"size": 6, "color": colors[key]},
            customdata=[p.value for p in pts],
            hovertemplate=(
                "%{x}<br>rebased %{y:.1f} · value %{customdata:g}<extra>" + key + "</extra>"
            ),
        )
    all_days = [p.day for pts in layer.series.values() for p in pts]
    if all_days:
        fig.update_xaxes(range=[min(all_days) - timedelta(days=15), end + timedelta(days=30)])
    decel = layer.components.get("price_deceleration")
    trend = layer.components.get("price_trend")
    note = "no price data" if trend is None else f"trend {trend:+.2f}"
    if decel is not None:
        note += f" · deceleration {decel:.2f}"
    fig.add_vline(x=boundary.isoformat(), line={"color": theme.MUTED, "width": 1, "dash": "dash"})
    fig.add_annotation(
        x=boundary.isoformat(),
        y=1.0,
        yref="paper",
        text=f"previous window | recent window ({note})",
        showarrow=False,
        xanchor="left",
        yanchor="top",
        font={"color": theme.MUTED},
    )
    return theme.style(
        fig,
        f"Price series: {layer.layer_name}",
        "Observation date",
        f"Index (100 = start of the {2 * window_days}-day history)",
    )


def bottleneck_score_scatter(
    companies: Sequence[BottleneckSignal], label_top: int = 6
) -> go.Figure:
    """Company score against the priced-in penalty, one dot per supplier (size = exposure);
    curated names are highlighted and always labelled, the rest cannot be screened here
    (section 4A.1) and only the ``label_top`` highest-scoring of them carry a label."""
    top = {s.ticker for s in sorted(companies, key=lambda s: -s.score)[:label_top]}
    fig = go.Figure()
    groups = (
        ("on the good-to-own list", theme.ACCENT, [s for s in companies if s.curated]),
        ("not investable here", theme.MUTED, [s for s in companies if not s.curated]),
    )
    for name, color, sub in groups:
        if not sub:
            continue
        fig.add_scatter(
            name=name,
            mode="markers+text",
            x=[s.components.get("priced_in", 0.0) for s in sub],
            y=[s.score for s in sub],
            text=[s.ticker if s.curated or s.ticker in top else "" for s in sub],
            hovertext=[s.ticker or "" for s in sub],
            textposition="top center",
            marker={
                "color": color,
                "size": [8 + 16 * s.components.get("exposure", 0.0) for s in sub],
                "line": {"color": "#ffffff", "width": 2},
            },
            customdata=[
                [f"{s.theme_id}/{s.layer_id}", s.layer_score, s.components.get("exposure", 0.0)]
                for s in sub
            ],
            hovertemplate=(
                "%{hovertext} · %{customdata[0]}<br>company score %{y:.0f} · layer score "
                "%{customdata[1]:.0f}<br>exposure %{customdata[2]:.2f} · priced in %{x:.2f}"
                "<extra></extra>"
            ),
        )
    fig.update_xaxes(range=[-0.05, 1.05])
    fig.update_yaxes(range=[0, 105])
    return theme.style(
        fig,
        "Company score vs priced-in penalty (size = exposure)",
        "Priced in (0 = nothing in the price, 1 = fully priced)",
        "Company score (0–100)",
    )


# ------------------------------------------------------------------------ under the hood
def agent_latency(latency_ms: Mapping[str, float], order: Sequence[str]) -> go.Figure:
    names = [a for a in order if a in latency_ms] + [a for a in latency_ms if a not in order]
    fig = go.Figure(
        go.Bar(
            orientation="h",
            y=[AGENT_LABELS.get(a, a) for a in names],
            x=[latency_ms[a] for a in names],
            marker={"color": theme.ACCENT},
            text=[f"{latency_ms[a]:,.0f} ms" for a in names],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{x:,.0f} ms<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed")
    return theme.style(
        fig,
        "Latency per specialist agent",
        "Milliseconds (summed over retries)",
        "",
        height=max(260, 34 * len(names) + 90),
        legend=False,
    )


# ------------------------------------------------------------------------------- goals
PATH_LABELS = {
    "stress": "stress path",
    "base": "base (expected yield, capped)",
    "best": "best (gross yield, capped)",
    "assumed": "diversified-portfolio assumption",
}


def goal_projection(plan: GoalPlan) -> go.Figure:
    """Balance by year on the plan's paths, with target lines and the coast marker (Phase 12)."""
    fig = go.Figure()
    colors = {
        "stress": theme.NEGATIVE,
        "base": theme.ACCENT,
        "best": theme.GOOD,
        "assumed": theme.MUTED,
    }
    for path in plan.projection:
        fig.add_scatter(
            name=PATH_LABELS.get(path.label, path.label),
            x=[p.year for p in path.points],
            y=[p.balance for p in path.points],
            mode="lines",
            line={
                "color": colors.get(path.label, theme.MUTED),
                "width": 2,
                "dash": "dot" if path.label == "assumed" else "solid",
            },
            hovertemplate="year %{x:g}: $%{y:,.0f}<extra>" + path.label + "</extra>",
        )
    targets: dict[str, float] = {}
    if plan.fire is not None:
        targets.update({f"{k} FIRE number": v for k, v in plan.fire.targets.items()})
        if plan.fire.coast_balance is not None:
            fig.add_scatter(
                name="coast balance today",
                x=[0.0],
                y=[plan.fire.coast_balance],
                mode="markers",
                marker={"size": 11, "color": theme.WARNING, "symbol": "diamond"},
                hovertemplate="coast balance: $%{y:,.0f}<extra></extra>",
            )
    elif plan.goal.target_balance is not None:
        targets["target balance"] = plan.goal.target_balance
    for label, value in targets.items():
        fig.add_hline(
            y=value,
            line={"dash": "dash", "color": theme.AXIS, "width": 1},
            annotation_text=f"{label}: ${value:,.0f}",
            annotation_position="top left",
        )
    years = plan.projection[0].points[-1].year if plan.projection else 0
    return theme.style(
        fig, "Projected balance by year", f"Years (0–{years:g})", "Balance (today's $)"
    )


# ---------------------------------------------------------------------------- holdings
def sector_weights_bar(analysis: HoldingsAnalysis) -> go.Figure:
    """Sector weights of what the user already owns (Phase 12)."""
    rows = sorted(analysis.by_sector.items(), key=lambda kv: kv[1])
    fig = go.Figure(
        go.Bar(
            orientation="h",
            y=[k for k, _ in rows],
            x=[round(v * 100, 1) for _, v in rows],
            marker={"color": theme.ACCENT, "line": {"width": 0}},
            text=[f"{v:.0%}" for _, v in rows],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
        )
    )
    fig.update_xaxes(range=[0, 115])
    return theme.style(
        fig, "Holdings by sector", "Weight (%)", "", height=max(220, 34 * len(rows) + 90)
    )


def concentration_after_assignment_bar(analysis: HoldingsAnalysis, cap: float) -> go.Figure:
    """Each ticker's weight before and after assignment, against the profile cap, on the same
    base as the risk check (holdings plus buying power). One bar pair per ticker: for a sized
    portfolio the row already counts every put on the ticker, as the check does; before sizing
    the puts are alternatives and the bar shows the one that would concentrate most."""
    worst: dict[str, PostAssignment] = {}
    for r in analysis.post_assignment:
        if r.ticker not in worst or r.weight_after > worst[r.ticker].weight_after:
            worst[r.ticker] = r
    rows = list(worst.values())
    fig = go.Figure()
    fig.add_bar(
        name="today",
        x=[r.ticker for r in rows],
        y=[round(r.weight_before * 100, 1) for r in rows],
        marker={"color": theme.MUTED},
        hovertemplate="%{x} today: %{y:.1f}%<extra></extra>",
    )
    fig.add_bar(
        name="if assigned",
        x=[r.ticker for r in rows],
        y=[round(r.weight_after * 100, 1) for r in rows],
        marker={"color": [theme.NEGATIVE if r.weight_after > cap else theme.ACCENT for r in rows]},
        customdata=[
            f"all sized {r.ticker} puts" if r.includes_other_puts else r.candidate_id for r in rows
        ],
        hovertemplate="%{customdata}: %{y:.1f}% after assignment<extra></extra>",
    )
    fig.add_hline(
        y=cap * 100,
        line={"dash": "dash", "color": theme.CRITICAL, "width": 1},
        annotation_text=f"profile cap {cap:.0%}",
        annotation_position="top left",
    )
    fig.update_layout(barmode="group")
    return theme.style(
        fig, "Ticker weight before and after assignment", "", "Share of holdings + buying power (%)"
    )
