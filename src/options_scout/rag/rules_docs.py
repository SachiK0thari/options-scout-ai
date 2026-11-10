"""Generate ``knowledge/rules/*.md`` from PRD.md sections 3.1–3.10 and ``config/*.yaml``.

Each rule document carries the PRD section verbatim (the specification) followed by the values
currently in force, read from the typed config, so an Education answer to "why was X excluded"
can cite the exact threshold. Sections 3.1–3.7 are the screening rules; 3.8–3.10 are the goal
feasibility, news flag and holdings concentration rules of Phase 12. ``make index`` regenerates the files; ``tests/unit/test_rag.py``
fails when the committed copies are stale. ``as_of`` is kept from the committed file while the
body is unchanged, so regeneration is idempotent day to day.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from options_scout.config import MAX_SIGNAL_WEIGHT, AppConfig
from options_scout.rag.corpus import parse_document, render_document
from options_scout.rag.models import Document

PRD_FILE = "PRD.md"
_SECTION = re.compile(r"^### (3\.\d+) (.+?)\s*$", re.MULTILINE)
_NEXT_HEADING = re.compile(r"^#{2,3} ", re.MULTILINE)

# section number → (file stem, config files the values come from)
RULE_FILES: dict[str, tuple[str, tuple[str, ...]]] = {
    "3.1": ("allocation", ("config/risk_profiles.yaml",)),
    "3.2": ("constraints", ("config/risk_profiles.yaml",)),
    "3.3": ("csp_screener", ("config/screener_rules.yaml",)),
    "3.4": ("leaps_screener", ("config/screener_rules.yaml",)),
    "3.5": ("pmcc_rules", ("config/screener_rules.yaml",)),
    "3.6": ("formulas", ("config/settings.yaml",)),
    "3.7": ("quality_gate", ("config/quality_universe.yaml", "config/settings.yaml")),
    "3.8": ("goal_feasibility", ("config/goals.yaml",)),
    "3.9": ("news_flags", ("config/news.yaml",)),
    "3.10": ("holdings_concentration", ("config/risk_profiles.yaml", "config/holdings.yaml")),
}


def github_anchor(heading: str) -> str:
    slug = re.sub(r"[^\w\- ]", "", heading.lower().replace(".", ""))
    return re.sub(r"\s+", "-", slug.strip())


def prd_sections(prd_text: str) -> dict[str, tuple[str, str]]:
    """``{"3.1": (title, body)}`` for every ``### 3.x`` heading in PRD.md."""
    out: dict[str, tuple[str, str]] = {}
    matches = list(_SECTION.finditer(prd_text))
    for i, m in enumerate(matches):
        start = m.end()
        nxt = _NEXT_HEADING.search(prd_text, start)
        end = nxt.start() if nxt else len(prd_text)
        body = prd_text[start:end].strip().rstrip("-").strip()
        out[m.group(1)] = (m.group(2).strip(), body)
        if i + 1 < len(matches) and matches[i + 1].start() < end:  # defensive, never expected
            out[m.group(1)] = (m.group(2).strip(), prd_text[start : matches[i + 1].start()].strip())
    return out


def _pct(x: float) -> str:
    return f"{x * 100:g}%"


def _table(headers: Iterable[str], rows: Iterable[Iterable[object]]) -> str:
    hs = list(headers)
    lines = ["| " + " | ".join(hs) + " |", "|" + "---|" * len(hs)]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _values_3_1(cfg: AppConfig) -> str:
    alloc = cfg.risk.allocation
    tilt = cfg.risk.regime_tilt
    table = _table(
        ["Profile", "CSP collateral", "LEAPS / PMCC", "Cash reserve"],
        [(p, _pct(a.csp), _pct(a.leaps), _pct(a.cash)) for p, a in alloc.items()],
    )
    return (
        f"{table}\n\n"
        f"Regime tilt: when the VIX 1-year percentile is at or above {tilt.high_iv_percentile:g} "
        f"the plan moves {_pct(tilt.shift)} of the account from LEAPS to CSP; at or below "
        f"{tilt.low_iv_percentile:g} it moves {_pct(tilt.shift)} from CSP to LEAPS. The cash "
        "reserve is never reduced by the tilt. A strategy bucket the user did not request is held "
        "as cash."
    )


def _values_3_2(cfg: AppConfig) -> str:
    cons = cfg.risk.constraints
    rows = [
        (
            "Max total short-put notional / account value",
            *(f"{c.max_short_put_notional_x:g}x" for c in cons.values()),
        ),
        ("Max margin usage of buying power", *(_pct(c.max_margin_usage) for c in cons.values())),
        (
            "Max realistic loss per position (% of account)",
            *(_pct(c.max_loss_per_position) for c in cons.values()),
        ),
        (
            "Max exposure per ticker (realistic loss)",
            *(_pct(c.max_exposure_per_ticker) for c in cons.values()),
        ),
        ("Max per sector (realistic loss)", *(_pct(c.max_per_sector) for c in cons.values())),
        (
            "Max total dollar delta / account value",
            *(f"{c.max_dollar_delta_x:g}x" for c in cons.values()),
        ),
    ]
    table = _table(["Constraint", *cons.keys()], rows)
    return (
        f"{table}\n\n"
        f"Realistic loss for a cash-secured put is the loss if the stock falls "
        f"{_pct(cfg.risk.realistic_loss_drop)} by expiry; for a LEAPS call it is the full premium "
        "paid. Margin constraints do not apply to cash accounts. A position that would break any "
        "constraint is skipped and the reason is recorded on the portfolio."
    )


def _values_3_3(cfg: AppConfig) -> str:
    r = cfg.rules.csp
    rows = [
        (
            "Days to expiry",
            f"{r.dte_min}–{r.dte_max} (fallback {r.dte_fallback_min}–{r.dte_fallback_max} when the strict window has no liquid candidate, flagged `dte_outside_preferred`)",
        ),
        ("Put delta (absolute)", f"{r.delta_min:g}–{r.delta_max:g}"),
        ("Open interest", f"≥ {r.min_open_interest:,}"),
        ("Bid-ask spread", f"≤ {_pct(r.max_spread_pct)} of mid"),
        ("Bid", f"> ${r.min_bid:.2f}"),
        (
            "Earnings before expiry",
            "excluded" if r.exclude_earnings_before_expiry else "flagged only",
        ),
        ("Underlying price", f"≥ ${r.min_underlying_price:g}"),
        ("Average volume", f"≥ {r.min_avg_volume:,} shares/day"),
        ("IV rank", f"prefer ≥ {_pct(r.preferred_iv_rank_min)} (soft score, not a filter)"),
    ]
    return _table(["Rule", "Value in force"], rows)


def _values_3_4(cfg: AppConfig) -> str:
    r = cfg.rules.leaps
    rows = [
        ("Days to expiry", f"≥ {r.dte_min}; prefer ≥ {r.dte_preferred}"),
        ("Call delta", f"{r.delta_min:g}–{r.delta_max:g}"),
        ("Extrinsic value per year", f"≤ {_pct(r.max_extrinsic_per_year_pct)} of the stock price"),
        ("Open interest", f"≥ {r.min_open_interest:,}"),
        ("Bid-ask spread", f"≤ {_pct(r.max_spread_pct)} of mid"),
        ("IV rank", f"prefer ≤ {_pct(r.preferred_iv_rank_max)} (soft score)"),
        (
            "Roll warning",
            f'flag "roll or close" when days to expiry fall below {r.roll_warning_dte}',
        ),
    ]
    return _table(["Rule", "Value in force"], rows)


def _values_3_5(cfg: AppConfig) -> str:
    r = cfg.rules.pmcc
    rows = [
        (
            "Short call days to expiry",
            f"{r.dte_min}–{r.dte_max} (fallback {r.dte_fallback_min}–{r.dte_fallback_max})",
        ),
        ("Short call delta", f"{r.delta_min:g}–{r.delta_max:g}"),
        ("Expiry", "before the LEAPS expiry"),
        ("Safety rule", "short strike ≥ LEAPS strike + net debit paid for the LEAPS (always on)"),
        ("Net delta", "LEAPS delta − short call delta"),
    ]
    return _table(["Rule", "Value in force"], rows)


def _values_3_6(cfg: AppConfig) -> str:
    s = cfg.settings
    shocks = ", ".join(_pct(x) for x in s.risk.stress_shocks)
    return (
        f"Stress test shocks applied to every sized portfolio: {shocks} on the underlying with "
        f"implied volatility raised by {_pct(s.risk.stress_iv_shock)} on down moves. The vol "
        f"shock applies in full to legs of {s.risk.stress_iv_shock_ref_dte} days or fewer to "
        f"expiry and shrinks as the square root of {s.risk.stress_iv_shock_ref_dte} / DTE for "
        f"longer-dated legs, since long-dated vol moves less in a selloff. Each leg is priced "
        f"before and after with the same model, so the P&L is model-after minus model-before.\n\n"
        f"The compliance check matches every number in a narrative against the computed payload "
        f"with a relative tolerance of {s.agent.verifier_number_tolerance:g}."
    )


def _values_3_7(cfg: AppConfig) -> str:
    q = cfg.quality
    g = q.gates
    w = q.score.weights
    rw = cfg.settings.ranking.weights
    gates = _table(
        ["Gate", "Value in force"],
        [
            ("Price", f"≥ ${g.min_price:g}"),
            ("Average volume", f"≥ {int(g.min_avg_volume):,} shares/day"),
            ("30-day realised volatility (HV30)", f"≤ {_pct(g.max_hv30)}"),
            ("ATM implied volatility", f"≤ {_pct(g.max_atm_iv)}"),
            ("Distance below the 90-day closing high", f"≤ {_pct(g.max_drawdown_90d)}"),
            ("Price history", f"≥ {g.min_history_days} closes"),
            ("require_curated", str(g.require_curated).lower()),
            ("Universe cap", f"{q.universe.max_tickers} tickers per run"),
        ],
    )
    score = (
        f"Quality score = {w.stability:g}·stability + {w.trend:g}·trend + {w.curated:g}·curated, "
        f"with stability = 1 − HV30/{_pct(g.max_hv30)} and trend = 1 − drawdown/"
        f"{_pct(g.max_drawdown_90d)}, both clipped to [0, 1]."
    )
    ranking = (
        f"Final ranking = {rw.option_quality:g}·option quality + {rw.stock_quality:g}·quality "
        f"score + {rw.social:g}·consumer-trend score/100 + {rw.bottleneck:g}·bottleneck score/100 "
        f"(the two signals together are capped at {MAX_SIGNAL_WEIGHT:g})."
    )
    curated = _table(
        ["Ticker", "Name", "Sector", "Why it is on the list"],
        [(t.ticker, t.name, t.sector, t.why) for t in q.tickers],
    )
    return (
        f"### Numeric gate\n\n{gates}\n\nMissing data fails a gate; it never passes it. Every failed "
        f"gate is recorded with its reason and the ticker never reaches the option screeners.\n\n"
        f"### Score and ranking\n\n{score}\n\n{ranking}\n\n### Curated good-to-own list "
        f"({len(q.tickers)} names, in priority order)\n\n{curated}\n\nThe list is a filter, not a "
        "recommendation: a user-added ticker is flagged *user-added* and must pass the same gate."
    )


def _values_3_8(cfg: AppConfig) -> str:
    g = cfg.goals
    profiles = list(g.max_assumed_return)
    per_profile = _table(
        ["Assumption", *profiles],
        [
            (
                "Return cap a goal may assume (above it the verdict is `does_not_fit`)",
                *(_pct(g.max_assumed_return[p]) for p in profiles),
            ),
            (
                "Diversified-portfolio return assumed for the conventional and FIRE projections",
                *(_pct(g.assumed_return[p]) for p in profiles),
            ),
            (
                "Share of years in which the −30% stress scenario is assumed to hit",
                *(_pct(g.assignment_frequency[p]) for p in profiles),
            ),
        ],
    )
    table = g.savings_rate_table
    rates = ", ".join(_pct(r) for r in table.rates)
    return (
        f"{per_profile}\n\n"
        f"Stretch band: a required return up to {g.stretch_band * 100:g} percentage points above "
        "the stress-adjusted yield, and still within the profile's cap, is a `stretch`.\n\n"
        f"Withdrawal rate: {_pct(g.withdrawal_rate)} unless the user states one (FIRE number = "
        f"expense target / withdrawal rate). Fat FIRE expense target when none is entered: "
        f"{g.fat_multiple:g} × current expenses. A target is reported as not reached beyond "
        f"{g.max_horizon_years} years.\n\n"
        f"Savings-rate illustration on the Goals tab: savings rates of {rates} at a real return "
        f"of {_pct(table.real_return)}."
    )


def _values_3_9(cfg: AppConfig) -> str:
    n = cfg.news
    sources = [
        ("Alpha Vantage NEWS_SENTIMENT", n.sources.alphavantage.enabled),
        ("RSS (live fallback)", n.sources.rss.enabled),
    ]
    rows = [
        ("Recency half-life", f"{n.half_life_days:g} days (weight = 0.5 ^ (age / half-life))"),
        ("Stale marker", f"older than {n.stale_days} days"),
        ("Lookback window", f"headlines from the last {n.lookback_days} days"),
        ("Headlines kept per ticker", f"{n.max_items_per_ticker}"),
        (
            "Ex-dividend capture window",
            f"within {n.capture_window_days} days before a short call's expiry",
        ),
        ("Live response cache", f"{n.cache_ttl_minutes} minutes"),
        *((name, "enabled" if on else "disabled") for name, on in sources),
    ]
    return _table(["Parameter", "Value in force"], rows)


def _values_3_10(cfg: AppConfig) -> str:
    cons = cfg.risk.constraints
    h = cfg.holdings
    cap = _table(
        ["Constraint", *cons.keys()],
        [
            (
                "Max ticker concentration after assignment",
                *(_pct(c.max_ticker_concentration_after_assignment) for c in cons.values()),
            )
        ],
    )
    ratios = _table(
        ["ETF", "Annual expense ratio"],
        [(t, f"{pct:g}%") for t, pct in sorted(h.expense_ratios_pct.items())],
    )
    return (
        f"{cap}\n\n"
        "The cap is measured against holdings value plus buying power and applies only when "
        "holdings were entered.\n\n"
        f"Covered-call lot: {h.covered_call_lot} shares. Beta: daily closes over "
        f"{h.beta_lookback_days} days against {h.beta_index}.\n\n"
        f"### Expense ratios used for the weighted expense ratio\n\n{ratios}\n\n"
        "A stock has no expense ratio; an ETF outside this table is reported without one."
    )


_VALUES = {
    "3.1": _values_3_1,
    "3.2": _values_3_2,
    "3.3": _values_3_3,
    "3.4": _values_3_4,
    "3.5": _values_3_5,
    "3.6": _values_3_6,
    "3.7": _values_3_7,
    "3.8": _values_3_8,
    "3.9": _values_3_9,
    "3.10": _values_3_10,
}


def _existing_as_of(path: Path, body: str) -> date | None:
    if not path.exists():
        return None
    try:
        old = parse_document(path.read_text(encoding="utf-8"), path=str(path))
    except ValueError:
        return None
    return old.as_of if old.body.strip() == body.strip() else None


def render_rules_docs(cfg: AppConfig, today: date | None = None) -> dict[str, str]:
    """``{"allocation.md": text, ...}`` for the current PRD and config."""
    today = today or date.today()
    prd = (cfg.root / PRD_FILE).read_text(encoding="utf-8")
    sections = prd_sections(prd)
    out_dir = cfg.rag.knowledge_dir / "rules"
    out: dict[str, str] = {}
    for number, (stem, config_files) in RULE_FILES.items():
        if number not in sections:
            raise ValueError(f"PRD.md has no section {number}")
        title, spec = sections[number]
        heading = f"{number} {title}"
        body = (
            f"# Rule {heading}\n\n"
            f"This document is generated from PRD.md section {number} and "
            f"{', '.join(f'`{c}`' for c in config_files)} by `scripts/build_rules_docs.py`; "
            "the values below are the ones in force for every screen this app runs.\n\n"
            f"## Specification (PRD.md section {number})\n\n{spec}\n\n"
            f"## Values in force ({', '.join(config_files)})\n\n{_VALUES[number](cfg)}\n"
        )
        filename = f"{stem}.md"
        as_of = _existing_as_of(out_dir / filename, body) or today
        doc = Document(
            id=f"rules-{number.replace('.', '-')}-{stem.replace('_', '-')}",
            title=f"Rule {number}: {title}",
            source=f"PRD.md section {number} and {', '.join(config_files)}",
            url=f"PRD.md#{github_anchor(heading)}",
            kind="rules",
            as_of=as_of,
            body=body,
            path=f"knowledge/rules/{filename}",
        )
        out[filename] = render_document(doc)
    return out


def write_rules_docs(cfg: AppConfig) -> list[Path]:
    out_dir = cfg.rag.knowledge_dir / "rules"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, text in render_rules_docs(cfg).items():
        path = out_dir / filename
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def stale_rules_docs(cfg: AppConfig) -> list[str]:
    """File names whose committed text differs from a fresh render (empty = up to date)."""
    out_dir = cfg.rag.knowledge_dir / "rules"
    stale: list[str] = []
    for filename, text in render_rules_docs(cfg).items():
        path = out_dir / filename
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            stale.append(filename)
    return stale
