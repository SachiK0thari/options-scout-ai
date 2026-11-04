"""OptionsScout as an MCP server (PRD section 10.1, step 10.7).

Six tools and one resource family, served over stdio with the ``mcp`` SDK (2.x, where the class
formerly called ``FastMCP`` is ``MCPServer``):

* ``quality_check``   → :mod:`options_scout.core.quality` on a live/fixture snapshot per ticker;
* ``screen_options``  → the full parent graph (fixture or live per env), compliance-checked report;
* ``price_option``    → :mod:`options_scout.core.pricing` (BSM price, Greeks, probability OTM);
* ``compute_margin``  → :mod:`options_scout.core.margin` (cash-secured collateral, Reg T minimum);
* ``payoff_curve``    → :mod:`options_scout.core.payoff` (spot grid, P&L, breakevens);
* ``explain_term``    → Education agent then Compliance, exactly like the chat and the API.

``knowledge://concepts`` lists the knowledge-base concept documents and
``knowledge://concepts/{doc_id}`` serves one of them (source and URL included).

Invariants kept from the rest of the app (PRD 13.1): no LLM-written text leaves a tool without a
``ComplianceReport``; the LLM never does math; market-data keys are never accepted from the client
(the server reads them from the environment it was started with). Logs go to stderr so stdout
stays a clean JSON-RPC channel.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from pydantic import Field, PositiveFloat

from options_scout import __version__
from options_scout.agent.chat import screen_summary
from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    answer_question,
    build_graph,
    initial_state,
    pending_interrupt,
    stream_run,
    thread_config,
)
from options_scout.config import get_config, load_env
from options_scout.core import margin, payoff, pricing
from options_scout.core.models import (
    AccountType,
    Citation,
    ComplianceReport,
    Model,
    Narrative,
    OptionKind,
    QualityCheck,
    RiskProfile,
    ScreeningReport,
    UserProfile,
)
from options_scout.core.quality import check_quality
from options_scout.observability import configure_logging, get_logger
from options_scout.rag.corpus import load_corpus
from options_scout.rag.models import Document

SERVER_NAME = "options-scout"
CONCEPTS_URI = "knowledge://concepts"
CONCEPT_URI_TEMPLATE = "knowledge://concepts/{doc_id}"
TOOL_NAMES: tuple[str, ...] = (
    "quality_check",
    "screen_options",
    "price_option",
    "compute_margin",
    "payoff_curve",
    "explain_term",
)
INSTRUCTIONS = (
    "OptionsScout is an educational options screener, not an adviser and not a broker. Its tools "
    "price options, compute collateral and payoff curves, apply the deterministic good-to-own "
    "quality gate, run the full cash-secured-put / LEAPS screen on fixture or delayed market "
    "data, and answer concept questions from a cited knowledge base. Every narrative passes a "
    "Compliance check before it is returned; present it as education, never as a recommendation. "
    "Market-data API keys are read from the server's environment and are never accepted as tool "
    "arguments."
)

T = TypeVar("T")
Strategy3 = Literal["csp", "leaps", "both"]
LegKind = Literal["call", "put", "stock"]
LegSide = Literal["long", "short"]


# ---------------------------------------------------------------------------- result models
class QualityCheckResult(Model):
    """Per-ticker gate outcome plus the gate values that produced it."""

    checks: list[QualityCheck]
    errors: list[str] = Field(default_factory=list)  # tickers the data source could not serve
    gates: dict[str, float | bool]
    as_of: str


class OptionPrice(Model):
    """Black-Scholes-Merton price and Greeks (theta per calendar day, vega per vol point)."""

    kind: OptionKind
    spot: float
    strike: float
    dte: float
    years_to_expiry: float
    iv: float
    rate: float
    dividend_yield: float
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    prob_otm: float
    intrinsic: float
    extrinsic: float


class MarginBreakdown(Model):
    """What a short put ties up: cash-secured collateral vs the Reg T exchange minimum."""

    account: AccountType
    spot: float
    strike: float
    premium: float
    contracts: int
    notional: float  # strike × 100 × contracts
    collateral_cash_secured: float  # (K − premium) × 100 × contracts
    reg_t_minimum: float  # (premium + max(0.20·S − OTM, 0.10·K)) × 100 × contracts
    requirement: float  # what this account type must hold: collateral (cash) or Reg T (margin)
    premium_received: float
    return_on_requirement: float
    annualized_return_on_collateral: float | None = None
    breakeven: float
    notes: list[str] = Field(default_factory=list)


class LegSpec(Model):
    """One option or stock leg: 100 shares per contract; ``strike`` is the entry price for stock."""

    kind: LegKind
    side: LegSide
    strike: PositiveFloat
    premium: float = Field(default=0.0, ge=0)  # per share; 0 for stock
    quantity: int = Field(default=1, ge=1)


class PayoffCurveResult(Model):
    """Dollar P&L at expiration over a spot grid, with breakevens and extremes."""

    spots: list[float]
    pnl: list[float]
    breakevens: list[float]
    max_loss: float  # as a positive number
    max_gain: float | None  # None when unbounded above
    loss_at_zero: float
    notes: list[str] = Field(default_factory=list)


class Explanation(Model):
    """A cited, compliance-checked answer from the Education agent."""

    term: str
    answer_markdown: str
    narrative: Narrative
    citations: list[Citation]
    compliance: ComplianceReport
    errors: list[str] = Field(default_factory=list)


class ScreenResult(Model):
    """One complete screening run: summary, the full report and its Markdown rendering."""

    thread_id: str
    summary: str
    report: ScreeningReport
    report_markdown: str


# ---------------------------------------------------------------------------- runtime
@dataclass
class Runtime:
    """Dependencies shared by every call of one server process, built on first use so that
    importing the module (or listing tools) never touches market data or the LLM layer."""

    deps_override: Deps | None = None
    _deps: Deps | None = None
    _graph: Any = None
    _documents: dict[str, Document] | None = None

    @property
    def deps(self) -> Deps:
        if self._deps is None:
            self._deps = self.deps_override or Deps.from_config(get_config())
        return self._deps

    @property
    def graph(self) -> Any:
        if self._graph is None:
            self._graph = build_graph(self.deps)
        return self._graph

    def documents(self) -> dict[str, Document]:
        if self._documents is None:
            docs = load_corpus(self.deps.cfg.rag.knowledge_dir, ("concepts",))
            self._documents = {d.id: d for d in docs}
        return self._documents


async def _in_thread(fn: Callable[[], T]) -> T:
    """Run blocking work (graph runs, market data) off the event loop so pings keep flowing."""
    return await anyio.to_thread.run_sync(fn)


# ---------------------------------------------------------------------------- tool bodies
def quality_check_sync(rt: Runtime, tickers: list[str]) -> QualityCheckResult:
    deps = rt.deps
    checks: list[QualityCheck] = []
    errors: list[str] = []
    seen: set[str] = set()
    for raw in tickers:
        ticker = raw.strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        try:
            snap = deps.md.build_snapshot(ticker)
            closes = deps.md.get_close_history(ticker, 90)
        except Exception as exc:
            errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
            continue
        curated = deps.cfg.quality.get(ticker)
        if curated is not None and snap.spot.sector in {"Unknown", ""}:
            snap = snap.model_copy(
                update={"spot": snap.spot.model_copy(update={"sector": curated.sector})}
            )
        checks.append(check_quality(snap, closes, deps.cfg.quality, curated))
    return QualityCheckResult(
        checks=checks,
        errors=errors,
        gates=deps.cfg.quality.gates.model_dump(),
        as_of=deps.md.now().isoformat(),
    )


def make_profile(
    *,
    buying_power: float,
    strategy: Strategy3,
    account: AccountType,
    risk: RiskProfile,
    tickers: list[str] | None,
    exclude: list[str] | None,
    max_positions: int,
) -> UserProfile:
    strategies = {"csp": {"csp"}, "leaps": {"leaps"}, "both": {"csp", "leaps"}}[strategy]
    return UserProfile(
        buying_power=buying_power,
        account_value=buying_power,
        account_type=account,
        risk_profile=risk,
        strategies=strategies,
        watchlist=tickers or [],
        exclude=exclude or [],
        max_positions=max_positions,
    )


def screen_options_sync(rt: Runtime, profile: UserProfile) -> ScreenResult:
    thread_id = f"mcp-{uuid.uuid4().hex[:12]}"
    graph = rt.graph
    state = initial_state("", profile.model_dump(mode="json"))
    for _ in stream_run(graph, state, thread_id):
        pass
    values: dict[str, Any] = dict(graph.get_state(thread_config(thread_id)).values)
    interrupt = pending_interrupt(graph, thread_id)
    if interrupt is not None:
        missing = ", ".join(str(f) for f in interrupt.get("needs_clarification", [])) or "profile"
        raise ToolError(f"the screen paused for clarification of: {missing}")
    rep = values.get("report")
    if not isinstance(rep, ScreeningReport):
        errors = "; ".join(values.get("errors") or []) or "no report produced"
        raise ToolError(f"screen did not complete: {errors}")
    if rep.compliance is None or not rep.audit_log:  # PRD 13.1
        raise RuntimeError("report has no compliance audit entry; refusing to return it")
    drop = round(rt.deps.cfg.risk.realistic_loss_drop * 100)
    return ScreenResult(
        thread_id=thread_id,
        summary=screen_summary(rep, drop),
        report=rep,
        report_markdown=str(values.get("report_markdown") or ""),
    )


def price_option_sync(
    *,
    spot: float,
    strike: float,
    dte: float,
    iv: float,
    rate: float,
    kind: OptionKind,
    dividend_yield: float,
) -> OptionPrice:
    years = max(dte, 0.0) / 365.0
    g = pricing.bsm_greeks(spot, strike, years, rate, dividend_yield, iv, kind)
    p_otm = pricing.prob_otm(spot, strike, years, rate, dividend_yield, iv, kind)
    intrinsic = pricing.intrinsic(spot, strike, kind)
    return OptionPrice(
        kind=kind,
        spot=spot,
        strike=strike,
        dte=dte,
        years_to_expiry=years,
        iv=iv,
        rate=rate,
        dividend_yield=dividend_yield,
        price=g.price,
        delta=g.delta,
        gamma=g.gamma,
        theta=g.theta,
        vega=g.vega,
        prob_otm=p_otm,
        intrinsic=intrinsic,
        extrinsic=max(g.price - intrinsic, 0.0),
    )


def compute_margin_sync(
    *,
    strike: float,
    premium: float,
    spot: float,
    account: AccountType,
    contracts: int,
    dte: int | None,
) -> MarginBreakdown:
    if premium >= strike:
        raise ToolError("premium must be below the strike")
    collateral = margin.csp_collateral(strike, premium) * contracts
    reg_t = margin.reg_t_put_margin(spot, strike, premium) * contracts
    premium_received = premium * margin.CONTRACT_MULTIPLIER * contracts
    notes = [
        "Cash-secured collateral is (strike − premium) × 100 per contract.",
        "Reg T is the exchange minimum for a naked put; brokers may and do require more, and "
        "requirements rise in volatile markets.",
    ]
    if account == "cash":
        requirement = collateral
        notes.append("A cash account must hold the full cash-secured collateral.")
    else:
        requirement = reg_t
        if account == "portfolio_margin":
            notes.append(
                "Portfolio margin is set by the broker's risk model; the Reg T minimum shown is a "
                "floor, not that figure."
            )
    annualized = margin.csp_annualized_return(strike, premium, dte) if dte else None
    return MarginBreakdown(
        account=account,
        spot=spot,
        strike=strike,
        premium=premium,
        contracts=contracts,
        notional=margin.short_put_notional(strike, contracts),
        collateral_cash_secured=collateral,
        reg_t_minimum=reg_t,
        requirement=requirement,
        premium_received=premium_received,
        return_on_requirement=margin.return_on_margin(premium * contracts, requirement),
        annualized_return_on_collateral=annualized,
        breakeven=strike - premium,
        notes=notes,
    )


def payoff_curve_sync(legs: list[LegSpec], spot: float | None, points: int) -> PayoffCurveResult:
    if not legs:
        raise ToolError("at least one leg is required")
    core_legs = [
        payoff.Leg(leg.kind, leg.side, leg.strike, leg.premium, leg.quantity) for leg in legs
    ]
    hi = max([*(leg.strike for leg in core_legs), spot or 0.0]) * 2.0
    spots = payoff.grid(0.0, hi, points)
    curve = payoff.payoff_curve(core_legs, spots)
    summary = payoff.summarize(core_legs, spots)
    notes = ["P&L at expiration in dollars for the whole position, premium included."]
    if {leg.kind for leg in core_legs} == {"call"} and len(core_legs) == 2:
        notes.append(
            "Two call legs with different expiries (a PMCC) are valued at the short call's expiry "
            "with the long call at intrinsic value, which is conservative."
        )
    return PayoffCurveResult(
        spots=[round(s, 4) for s, _ in curve],
        pnl=[round(p, 2) for _, p in curve],
        breakevens=summary.breakevens,
        max_loss=summary.max_loss,
        max_gain=summary.max_gain,
        loss_at_zero=summary.loss_at_zero,
        notes=notes,
    )


def explain_term_sync(rt: Runtime, term: str) -> Explanation:
    term = term.strip()
    if not term:
        raise ToolError("term must not be empty")
    values = answer_question(rt.deps, term, f"mcp-{uuid.uuid4().hex[:12]}")
    answer: Narrative = values["answer"]
    compliance: ComplianceReport = values["compliance"]
    return Explanation(
        term=term,
        answer_markdown=answer.markdown,
        narrative=answer,
        citations=list(values.get("citations") or []),
        compliance=compliance,
        errors=list(values.get("errors") or []),
    )


def find_concept(docs: dict[str, Document], doc_id: str) -> Document | None:
    """Ids are hyphenated (``cash-secured-put``); accept the file-name spelling too."""
    key = doc_id.strip().lower()
    return docs.get(key) or docs.get(key.replace("_", "-"))


def render_concept(doc: Document) -> str:
    return (
        f"# {doc.title}\n\n"
        f"_Source: {doc.source} ({doc.url}); as of {doc.as_of.isoformat()}. "
        f"Education, not advice._\n\n{doc.body}"
    )


# ---------------------------------------------------------------------------- server
def create_server(deps: Deps | None = None) -> MCPServer[None]:
    """Build the MCP server. ``deps`` lets tests inject isolated dependencies; the stdio entry
    point leaves it ``None`` and the server reads its configuration from the environment."""
    rt = Runtime(deps_override=deps)
    server: MCPServer[None] = MCPServer(
        SERVER_NAME,
        title="OptionsScout AI",
        instructions=INSTRUCTIONS,
        version=__version__,
    )

    @server.tool()
    async def quality_check(tickers: list[str]) -> QualityCheckResult:
        """Run the deterministic good-to-own quality gate on each ticker (price, volume, realised
        and implied volatility, 90-day drawdown, curated-list membership) using the server's
        configured market data. Returns pass/fail with plain-English reasons and a 0–1 quality
        score per ticker; a ticker the data source cannot serve is listed under ``errors``."""
        return await _in_thread(lambda: quality_check_sync(rt, tickers))

    @server.tool()
    async def screen_options(
        buying_power: PositiveFloat,
        strategy: Strategy3 = "both",
        account: AccountType = "cash",
        risk: RiskProfile = "conservative",
        tickers: list[str] | None = None,
        exclude: list[str] | None = None,
        max_positions: int = Field(default=6, ge=1, le=20),
    ) -> ScreenResult:
        """Run the full OptionsScout screen: quality gate on the curated good-to-own list plus
        ``tickers``, cash-secured put and/or LEAPS call candidates, sizing to ``buying_power``
        under the risk limits, stress test, and a cited narrative that has passed Compliance.
        Uses fixture or live market data per the server's environment; takes several seconds.
        Educational output, not advice."""
        profile = make_profile(
            buying_power=buying_power,
            strategy=strategy,
            account=account,
            risk=risk,
            tickers=tickers,
            exclude=exclude,
            max_positions=max_positions,
        )
        return await _in_thread(lambda: screen_options_sync(rt, profile))

    @server.tool()
    def price_option(
        spot: PositiveFloat,
        strike: PositiveFloat,
        dte: float = Field(ge=0, description="days to expiry (fractional days allowed)"),
        iv: float = Field(gt=0, le=5, description="implied volatility as a fraction, e.g. 0.25"),
        rate: float = Field(default=0.04, ge=-0.05, le=0.5, description="annual risk-free rate"),
        kind: OptionKind = "put",
        dividend_yield: float = Field(default=0.0, ge=0, le=0.5),
    ) -> OptionPrice:
        """Black-Scholes-Merton price, delta, gamma, theta (per calendar day), vega (per vol
        point) and risk-neutral probability of expiring out of the money for one option."""
        return price_option_sync(
            spot=spot,
            strike=strike,
            dte=dte,
            iv=iv,
            rate=rate,
            kind=kind,
            dividend_yield=dividend_yield,
        )

    @server.tool()
    def compute_margin(
        strike: PositiveFloat,
        premium: float = Field(ge=0),
        spot: PositiveFloat = Field(),
        account: AccountType = "cash",
        contracts: int = Field(default=1, ge=1),
        dte: int | None = Field(default=None, ge=1, description="for the annualised return"),
    ) -> MarginBreakdown:
        """Collateral for a short put: cash-secured amount, Reg T exchange-minimum requirement,
        what the given account type must hold, premium received, return on that requirement and
        (with ``dte``) the annualised return on collateral."""
        return compute_margin_sync(
            strike=strike,
            premium=premium,
            spot=spot,
            account=account,
            contracts=contracts,
            dte=dte,
        )

    @server.tool()
    def payoff_curve(
        legs: list[LegSpec],
        spot: float | None = Field(default=None, gt=0),
        points: int = Field(default=101, ge=11, le=1001),
    ) -> PayoffCurveResult:
        """Payoff at expiration for a list of option/stock legs over a spot grid from 0 to twice
        the highest strike (or spot): spots, P&L, breakevens, max loss, max gain, loss at zero."""
        return payoff_curve_sync(legs, spot, points)

    @server.tool()
    async def explain_term(term: str) -> Explanation:
        """Explain an options concept (e.g. "cash-secured put", "theta", "Reg T margin") with an
        answer retrieved from the cited knowledge base, written by the Education agent and
        checked by Compliance. The ``compliance`` field is the audit record; ``citations`` map
        every [Sn] tag to its source."""
        return await _in_thread(lambda: explain_term_sync(rt, term))

    @server.resource(
        CONCEPTS_URI,
        name="concepts",
        title="Knowledge-base concepts",
        description="Index of the cited concept documents (id, title, source, url, as_of).",
        mime_type="application/json",
    )
    def list_concepts() -> str:
        docs = rt.documents()
        return json.dumps(
            [
                {
                    "id": d.id,
                    "uri": CONCEPT_URI_TEMPLATE.format(doc_id=d.id),
                    "title": d.title,
                    "source": d.source,
                    "url": d.url,
                    "as_of": d.as_of.isoformat(),
                }
                for d in docs.values()
            ],
            indent=2,
        )

    @server.resource(
        CONCEPT_URI_TEMPLATE,
        name="concept",
        title="Knowledge-base concept",
        description="One concept document from knowledge/concepts, with its source citation.",
        mime_type="text/markdown",
    )
    def read_concept(doc_id: str) -> str:
        doc = find_concept(rt.documents(), doc_id)
        if doc is None:
            raise ResourceNotFoundError(
                f"unknown concept {doc_id!r}; read {CONCEPTS_URI} for the list"
            )
        return render_concept(doc)

    return server


def main() -> None:
    """``python -m options_scout.mcp.server``: serve over stdio (``make mcp``)."""
    load_env()
    configure_logging()
    get_logger(component="mcp").info("mcp_server_start", transport="stdio", version=__version__)
    create_server().run("stdio")


if __name__ == "__main__":
    main()
