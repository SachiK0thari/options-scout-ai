"""Streamlit tests for the multi-tab app (PRD step 10.6): fixture mode, no network, ``AppTest``.

Each test drives the real script: the Setup form or the Scout chat runs the LangGraph pipeline
in-process on bundled fixtures, then the nine tabs render from the checkpointed state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "ui" / "streamlit_app.py"
TABS = [
    "Scout",
    "Setup",
    "Quality Screen",
    "Candidates",
    "Portfolio & Risk",
    "Goals",
    "Learn",
    "Trends & News",
    "Under the hood",
]
DISCLAIMER_START = "Educational screening tool"
RISKY = ("CMG", "DECK", "ELF")


def _app(timeout: int = 300) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=timeout)
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _run_form(
    at: AppTest, *, strategy: str, buying_power: float = 60_000.0, **widgets: Any
) -> AppTest:
    at.number_input(key="bp").set_value(buying_power)
    at.radio(key="strategy").set_value(strategy)
    for key, value in widgets.items():
        getattr(at, key.split(":")[0])(key=key.split(":")[1]).set_value(value)
    at.button(key="run").click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert at.session_state["thread_id"]
    return at


def _h3(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown if m.value.startswith("### ")]


def _badges(at: AppTest) -> list[str]:
    return [e.label for e in at.expander if e.label.startswith("Compliance")]


def _chat(at: AppTest, text: str) -> AppTest:
    at.chat_input[0].set_value(text).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


# ------------------------------------------------------------------------------- no report
def test_nine_tabs_render_with_no_report() -> None:
    at = _app(120)
    assert [t.label for t in at.tabs] == TABS
    assert len(at.chat_input) == 1
    # every tab tells the user what to do; nothing crashes without a report
    infos = " ".join(i.value for i in at.info)
    assert "Results will appear here" in infos
    assert "Run a screen" in infos
    assert at.number_input(key="bp").label.startswith("Buying power")
    assert at.radio(key="strategy").options == ["Cash-secured puts", "LEAPS calls", "Both"]
    assert "Bundled sample data (offline)" in at.radio(key="ds_choice").options
    assert "Tradier (paste your API key)" in at.radio(key="ds_choice").options
    # Learn opens on the learning path, offline, before any run
    assert at.radio(key="learn_page").value == "Learning path"
    assert any(c.value.startswith("Path progress: 0/") for c in at.caption)


def test_disclaimer_on_every_tab() -> None:
    at = _app(120)
    for tab in at.tabs:
        assert any(DISCLAIMER_START in w.value for w in tab.warning), tab.label
    # and once more above the tabs
    assert sum(DISCLAIMER_START in w.value for w in at.warning) >= len(TABS) + 1


def test_tradier_without_a_key_shows_an_error_and_does_not_run() -> None:
    at = _app(120)
    at.radio(key="ds_choice").set_value("Tradier (paste your API key)").run()
    assert not at.exception
    assert at.text_input(key="ds_key_tradier").label == "Tradier API key"
    at.button(key="run").click().run()
    assert any("Paste a Tradier API key" in e.value for e in at.error)
    assert "thread_id" not in at.session_state


# ------------------------------------------------------------------------------ with a report
def test_csp_only_run_shows_quality_screen_and_puts_but_no_leaps() -> None:
    at = _run_form(_app(), strategy="Cash-secured puts")
    headers = _h3(at)
    assert any("Cash-secured put candidates" in h for h in headers)
    assert not any("LEAPS call candidates" in h for h in headers)
    assert any("verifier PASS" in c.value for c in at.caption)
    assert any(m.label == "Stocks passing quality gate" and m.value == "7 / 7" for m in at.metric)
    assert any(m.label == "CSP candidates" for m in at.metric)
    assert any(m.label == "LEAPS candidates" and m.value == "n/a" for m in at.metric)
    # risky fixture names never appear in a quality / candidate / position table
    for df in at.dataframe:
        frame = df.value
        if "On good-to-own list" in frame.columns:
            continue  # the trend board legitimately lists non-curated brands, flagged as such
        for col in ("Ticker", "Candidate"):
            if col in frame.columns:
                cells = " ".join(map(str, frame[col].tolist()))
                assert not any(t in cells for t in RISKY), (col, cells)


def test_leaps_only_run() -> None:
    at = _run_form(_app(), strategy="LEAPS calls")
    headers = _h3(at)
    assert any("LEAPS call candidates" in h for h in headers)
    assert not any("Cash-secured put candidates" in h for h in headers)


def test_both_strategies_fill_every_tab() -> None:
    at = _run_form(
        _app(),
        strategy="Both",
        buying_power=100_000.0,
        **{"selectbox:acct": "margin", "text_input:watch": "ELF"},
    )
    headers = _h3(at)
    assert any("Cash-secured put candidates" in h for h in headers)
    assert any("LEAPS call candidates" in h for h in headers)
    # Quality Screen: ELF was considered (user-added) and excluded with a reason
    excluded = next(e for e in at.expander if e.label.startswith("Excluded by the quality gate"))
    assert any("ELF" in m.value for m in excluded.markdown)
    # Portfolio & Risk: positions, limit checks, margin caption
    labels = [m.label for m in at.metric]
    assert "Positions sized" in labels and "Capital used" in labels and "Reg T margin" in labels
    assert any("Margin account" in c.value for c in at.caption)
    checks = next(df for df in at.dataframe if "Check" in df.value.columns)
    assert len(checks.value) >= 5
    # Candidates: strike ladder selector; Trends: component selector; Under the hood: trace
    assert any(s.label == "Strike ladder for" for s in at.selectbox)
    assert any(s.label == "Score components for" for s in at.selectbox)
    assert any(m.label == "Specialists run" and m.value == "9" for m in at.metric)  # + News Desk
    nodes = next(df for df in at.dataframe if "node" in df.value.columns)
    assert "compliance_node" in nodes.value["node"].tolist()
    assert any(e.label.startswith("Evidence posts") for e in at.expander)
    assert any(b.label == "Download JSON" for b in at.download_button)


# ------------------------------------------------------------------------------------ chat
def test_chat_turn_renders_a_compliance_badge() -> None:
    at = _chat(_app(), "What is assignment?")
    names = [m.name for m in at.chat_message]
    assert names[-2:] == ["user", "assistant"]
    assert len(_badges(at)) == 1 and _badges(at)[0].startswith("Compliance ✓")
    answer = at.chat_message[-1].markdown[0].value
    assert "[S1]" in answer
    assert any(e.label.startswith("Sources (") for e in at.expander)
    assert any("intent: `concept`" in c.value for c in at.caption)


def test_chat_describe_confirm_what_if_and_off_topic() -> None:
    at = _chat(
        _app(),
        "I have $100,000 of buying power in a margin account. Show me CSPs and LEAPS. I like NKE.",
    )
    # the Orchestrator paused: the review renders as an editable profile with a Confirm button
    assert at.session_state.get("interrupted") is True
    assert at.selectbox(key="rv_risk").value == "conservative"
    assert at.number_input(key="rv_bp").value == 100_000.0
    assert len(_badges(at)) == 1  # the review prompt itself carried a compliance report
    at.selectbox(key="rv_risk").set_value("balanced")
    at.button(key="FormSubmitter:review-Confirm and run").click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert "interrupted" not in at.session_state
    thread = at.session_state["thread_id"]
    summary = at.chat_message[-1].markdown[0].value
    assert summary.startswith("**Screen complete**")
    assert any("Cash-secured put candidates" in h for h in _h3(at))
    # what-if: a new thread, a diff, and a compliance report that passed first time
    _chat(at, "What if I had $30,000 instead?")
    assert at.session_state["thread_id"] == f"{thread}-2"
    reply = at.chat_message[-1].markdown[0].value
    assert reply.startswith("**What-if.**") and "100,000 → 30,000" in reply
    assert "could not produce an explanation" not in reply
    chat = at.session_state["chat_session"]
    last = chat.history(f"{thread}-2")[-1]
    assert last.compliance is not None and last.compliance.passed
    # off-topic: the fixed redirect, still badged
    _chat(at, "Who won the game last night?")
    assert "options education" in at.chat_message[-1].markdown[0].value
    assert all(b.startswith("Compliance ✓") for b in _badges(at))
    assert len(_badges(at)) == 4


# ------------------------------------------------------------------------------------ learn
def test_learn_concept_page_shows_a_citation_and_the_education_label() -> None:
    at = _app(120)
    at.radio(key="learn_page").set_value("Concepts").run()
    at.radio(key="concept").set_value("cash-secured-put").run()
    assert not at.exception
    assert any("Cash-secured put" in h for h in _h3(at))
    cites = [c.value for c in at.caption if c.value.startswith("Citation:")]
    assert len(cites) >= 1 and "theocc.com" in cites[0]
    assert any("Education, not advice" in c.value for c in at.caption)
    assert any("Source [S1]" in m.value for m in at.markdown)


@pytest.mark.parametrize(
    ("page", "metric"),
    [
        ("Payoff diagram", "Breakeven"),
        ("Reg T walkthrough", "Reg T minimum (margin account)"),
    ],
)
def test_learn_interactive_pages_work_without_a_report(page: str, metric: str) -> None:
    at = _app(120)
    at.radio(key="learn_page").set_value(page).run()
    assert not at.exception, [e.message for e in at.exception]
    assert any(m.label == metric for m in at.metric)
    assert any("Education, not advice" in c.value for c in at.caption)


def test_learn_pages_bind_to_a_screened_candidate() -> None:
    at = _run_form(_app(), strategy="Both")
    at.radio(key="learn_page").set_value("Greeks of a candidate").run()
    assert not at.exception
    assert at.selectbox(key="greek_pick").value.startswith(("CSP-", "LEAPS-"))
    assert [m.label for m in at.metric if m.label in ("Delta", "Gamma", "Theta", "Vega")] == [
        "Delta",
        "Gamma",
        "Theta",
        "Vega",
    ]
    at.radio(key="learn_page").set_value("Reg T walkthrough").run()
    assert at.selectbox(key="regt_pick").value.startswith("CSP-")
    assert any("The screener recorded margin" in c.value for c in at.caption)
    at.radio(key="learn_page").set_value("Hype and short puts").run()
    assert any("hype" in h.lower() for h in _h3(at))


# ------------------------------------------------------------------------------- goals (12.3)
def test_goals_tab_plans_a_goal_from_the_chat() -> None:
    at = _app(120)
    goals_tab = next(t for t in at.tabs if t.label == "Goals")
    assert any("No goal yet" in i.value for i in goals_tab.info)
    assert at.radio(key="goal_kind").options == ["Monthly income", "Grow to a balance", "FIRE"]
    at = _chat(at, "I have 60k, can I make $400 a month from this account?")
    goals_tab = next(t for t in at.tabs if t.label == "Goals")
    metrics = {m.label: m.value for m in goals_tab.metric}
    assert metrics["Verdict"] in ("fits", "stretch", "does not fit")
    assert metrics["Required return"] == "8.0%"
    assert any("Levers" in m.value for m in goals_tab.markdown)
    assert any(b.startswith("Compliance ✓") for b in _badges(at))


# ---------------------------------------------------------------------------- holdings (12.4)
def test_portfolio_tab_analyses_holdings_from_the_form() -> None:
    at = _app(120)
    portfolio_tab = next(t for t in at.tabs if t.label == "Portfolio & Risk")
    assert any("No holdings on this thread yet" in c.value for c in portfolio_tab.caption)
    at.text_area(key="holdings_text").set_value("200 AAPL at 150, MSFT 100 @ 300, 40 SPY").run()
    # the form button is the second form on the page; drive the chat path the form uses
    at = _chat(at, "My holdings: 200 AAPL at 150, MSFT 100 @ 300, 40 SPY")
    portfolio_tab = next(t for t in at.tabs if t.label == "Portfolio & Risk")
    metrics = {m.label: m.value for m in portfolio_tab.metric}
    assert "Holdings value" in metrics and metrics["Diversification"].endswith("/ 100")
    assert any(b.startswith("Compliance ✓") for b in _badges(at))


# ------------------------------------------------------------------------- learning (12.7)
def _stage_open(at: AppTest) -> list[bool]:
    """Which of the three learning-path stages is expanded, in order."""
    return [e.proto.expanded for e in at.expander if e.label[:3] in ("1 ·", "2 ·", "3 ·")]


def test_learning_path_tracks_progress_and_opens_a_page() -> None:
    at = _app(120)
    assert at.selectbox(key="level").value == "intermediate"
    # no profile yet: the path starts at stage 1
    assert any("Reading level: **beginner**" in c.value for c in at.caption)
    assert _stage_open(at) == [True, False, False]
    total = next(c.value for c in at.caption if c.value.startswith("Path progress:")).split("/")[1]
    # basics, core concepts (25 with bottleneck-arbitrage, step 11.5), advanced, tax
    assert int(total.split()[0]) == 28 + 25 + 12 + 14
    at.checkbox(key="read-what-is-a-stock").check().run()
    assert any(c.value.startswith("Path progress: 1/") for c in at.caption)
    assert any(e.label.startswith("1 · Basics · 1/28 read") for e in at.expander)
    # "Read" opens the document on the Concepts page, in its own collection
    at.button(key="open-assignment-cost-basis").click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert at.radio(key="learn_page").value == "Concepts"
    assert at.radio(key="glossary_kind").value == "tax"
    assert any(c.value.startswith("Citation:") and "knowledge/tax/" in c.value for c in at.caption)
    assert "all" in at.radio(key="glossary_level").options
    # the tick survives leaving the path and coming back
    at.button(key="back-to-path").click().run()
    assert at.radio(key="learn_page").value == "Learning path"
    assert at.checkbox(key="read-what-is-a-stock").value is True
    assert any(c.value.startswith("Path progress: 1/") for c in at.caption)


@pytest.mark.parametrize(
    ("level", "stages", "shown", "hidden"),
    [
        ("beginner", [True, False, False], [], ["Delta", "Open interest", "Vega"]),
        ("intermediate", [False, True, False], ["Delta", "Open interest"], ["Gamma", "Vega"]),
        ("advanced", [False, False, True], ["Delta", "Gamma", "Vega", "Spread", "Implied vol"], []),
    ],
)
def test_each_knowledge_level_shapes_the_tables_the_path_and_the_strip(
    level: str, stages: list[bool], shown: list[str], hidden: list[str]
) -> None:
    at = _run_form(_app(), strategy="Cash-secured puts", **{"selectbox:level": level})
    # Candidates: the level's columns, every header with a glossary tooltip
    assert any(c.value.startswith(f"{level.capitalize()} view:") for c in at.caption)
    table = next(d.value for d in at.dataframe if "Cash to secure" in d.value.columns)
    assert "Chance it expires worthless" in table.columns
    assert all(c in table.columns for c in shown) and not any(c in table.columns for c in hidden)
    terms = [e for e in at.expander if e.label == "What do these columns mean?"]
    assert terms and any("**Cash to secure**" in m.value for m in terms[0].markdown)
    # Learn: the stage for this level is the open one
    assert any(f"Reading level: **{level}** (your profile)" in c.value for c in at.caption)
    assert _stage_open(at) == stages
    # the market overview strip, on both tabs that carry it, with the data age
    for name in ("Quality Screen", "Candidates"):
        tab = next(t for t in at.tabs if t.label == name)
        metrics = {m.label: m for m in tab.metric}
        assert {"SPY", "QQQ", "VIX", "13-week T-bill", "Data"} <= set(metrics), name
        assert metrics["SPY"].value.startswith("$") and "vs prev close" in metrics["SPY"].delta
        assert metrics["Data"].value == "fixture"
        assert metrics["Data"].delta.startswith("fixture, recorded 20")
        assert any("data age: fixture, recorded 20" in c.value for c in tab.caption)


def test_glossary_button_opens_the_document_on_the_learn_tab() -> None:
    at = _run_form(_app(), strategy="Cash-secured puts")
    at.button(key="csp_terms-Delta").click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert at.radio(key="learn_page").value == "Concepts"
    assert at.radio(key="concept").value == "delta"
    assert any("Delta" in h for h in _h3(at))
    assert any("is open on the **Learn** tab" in c.value for c in at.caption)


def test_chat_states_a_level_and_the_review_form_can_change_it() -> None:
    # no risk appetite stated, so the Orchestrator pauses for review
    at = _chat(
        _app(), "I have never traded options. I have $40,000 in a cash account. Show me CSPs."
    )
    assert at.session_state.get("interrupted") is True
    assert at.selectbox(key="rv_level").value == "beginner"
    assert any("Reading level: **beginner** (your request)" in c.value for c in at.caption)
    at.selectbox(key="rv_level").set_value("advanced")
    at.button(key="FormSubmitter:review-Confirm and run").click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert any("Reading level: **advanced** (your profile)" in c.value for c in at.caption)
    assert any(c.value.startswith("Advanced view:") for c in at.caption)


# ------------------------------------------------------------------- bottlenecks (11.6)
BOARDS = ["Consumer trends", "Bottlenecks", "News desk"]
BOARD_ONLY = ("GEV", "VST", "ETN", "MU")  # suppliers on the board that are not good-to-own


def _board(at: AppTest) -> AppTest:
    at.radio(key="trends_board").set_value("Bottlenecks").run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _company_table(at: AppTest) -> Any:
    return next(d.value for d in at.dataframe if "Company score" in d.value.columns)


def test_bottleneck_board_renders_without_a_report() -> None:
    at = _board(_app(120))
    assert at.radio(key="trends_board").options == BOARDS
    assert any(c.value.startswith("Board from") for c in at.caption)
    assert any("re-orders" in c.value and "never adds" in c.value for c in at.caption)
    # theme → layer tree: one table per theme, eight layers in all, each with its thesis state
    layer_tables = [d.value for d in at.dataframe if "Thesis" in d.value.columns]
    assert len(layer_tables) == 2 and sum(len(t) for t in layer_tables) == 8
    assert {"holding", "weakening"} >= {s for t in layer_tables for s in t["Thesis"]}
    # companies per layer: materiality, the curated flag, plain-language flags
    companies = _company_table(at)
    assert {"Materiality", "On good-to-own list", "Flags"} <= set(companies.columns)
    assert set(BOARD_ONLY) <= set(companies["Ticker"])
    by = companies.set_index("Ticker")
    assert (
        by.loc["GEV", "On good-to-own list"] == "no"
        and by.loc["HON", "On good-to-own list"] == "✅"
    )
    assert by.loc["GEV", "Materiality"] == "high" and by.loc["HON", "Materiality"] == "medium"
    assert "strong constraint" in by.loc["GEV", "Flags"]
    # the three charts, captioned, behind the layer selector
    assert at.selectbox(key="bn_layer").value.startswith(("ai_datacenter/", "electrification/"))
    for text in (
        "Daily tightening and easing mentions",
        "rebased to 100",
        "Each dot is one supplier",
    ):
        assert any(text in c.value for c in at.caption), text
    # the thesis monitor: one expander per layer with falsifiers and evidence links
    monitors = [e for e in at.expander if "· thesis " in e.label]
    assert len(monitors) == 8 and any("thesis weakening" in e.label for e in monitors)
    falsifiers = [d for e in monitors for d in e.dataframe if "Falsifier" in d.value.columns]
    assert len(falsifiers) == 8 and all(
        set(d.value["State"])
        <= {"holding"} | {s for s in d.value["State"] if s.startswith("tripped since")}
        for d in falsifiers
    )
    links = [m.value for e in monitors for m in e.markdown]
    assert any("https://www.sec.gov/Archives/" in m for m in links)
    assert any("https://fred.stlouisfed.org/series/" in m for m in links)
    assert not any(word in m.lower() for m in links for word in (" exit", "take profits", " sell "))


def test_bottleneck_board_with_a_report_never_leaks_into_candidate_tables() -> None:
    at = _board(_run_form(_app(), strategy="Both"))
    assert any(c.value.startswith("Board from this screen") for c in at.caption)
    companies = _company_table(at)
    board_only = set(companies.loc[companies["On good-to-own list"] == "no", "Ticker"])
    assert board_only >= set(BOARD_ONLY)
    for df in at.dataframe:
        frame = df.value
        if "On good-to-own list" in frame.columns:
            continue  # the two boards legitimately list names that cannot be screened here
        for col in ("Ticker", "Candidate"):
            if col in frame.columns:
                assert not board_only & set(map(str, frame[col].tolist())), (col, frame[col])
    # Candidates: the plain-language column at every level, the four ranking weights named
    table = next(d.value for d in at.dataframe if "Cash to secure" in d.value.columns)
    assert "Supply constraint" in table.columns
    assert not any(
        f.startswith("bottleneck") for cell in table["Flags"] for f in str(cell).split(", ")
    )
    assert any("bottleneck 5%" in c.value for c in at.caption)
    # Under the hood: the engine's status and one row per configured source
    from options_scout.config import BOTTLENECK_SOURCE_NAMES

    status = next(
        d.value for d in at.dataframe if list(d.value.columns) == ["Source", "Enabled", "Status"]
    )
    assert status.iloc[0]["Source"] == "bottleneck engine"
    assert status.iloc[0]["Status"] == "snapshot" or status.iloc[0]["Status"].startswith("ran (")
    assert set(status["Source"][1:]) == set(BOTTLENECK_SOURCE_NAMES)


def test_supply_constraint_flags_render_in_plain_language() -> None:
    from ui import glossary
    from ui.tabs import candidates as tab
    from ui.tabs.under_the_hood import bottleneck_source_rows

    from options_scout.config import BOTTLENECK_SOURCE_NAMES

    assert tab.supply_constraint_text([]) == ""
    assert tab.supply_constraint_text(["dte_outside_preferred", "bottleneck_support"]) == (
        "🔧 sells into a tight supply layer"
    )
    text = tab.supply_constraint_text(
        ["catalyst_inside_dte", "bottleneck_easing", "bottleneck_support"]
    )
    assert text.split("; ") == [
        "🔧 sells into a tight supply layer",
        "🟡 constraint easing: new supply or slower prices",
        "📅 earnings or data release before expiry",
    ]
    assert "bottleneck" not in text and "catalyst_inside_dte" not in text
    tip = glossary.help_for("Supply constraint")
    assert tip and "Never a filter" in tip and "Learn → Concepts → Bottleneck arbitrage" in tip
    rows = bottleneck_source_rows(
        {"bottleneck": "ran (300 snippets, 8 layers, 30 companies)", "bottleneck:edgar": "ok"}
    )
    assert rows[0] == {
        "Source": "bottleneck engine",
        "Enabled": "yes",
        "Status": "ran (300 snippets, 8 layers, 30 companies)",
    }
    by = {r["Source"]: r for r in rows[1:]}
    assert set(by) == set(BOTTLENECK_SOURCE_NAMES) and by["edgar"]["Status"] == "ok"
    assert by["transcripts"] == {"Source": "transcripts", "Enabled": "no", "Status": "disabled"}
    reused = bottleneck_source_rows({"bottleneck": "snapshot"})
    assert all("snapshot" in r["Status"] for r in reused if r["Enabled"] == "yes")


def test_bottleneck_charts_draw_the_series_and_the_markers() -> None:
    from datetime import UTC, date, datetime, timedelta

    from ui import charts

    from options_scout.core.models import BottleneckSignal, SeriesPoint

    as_of = datetime(2026, 10, 27, 23, 59, tzinfo=UTC)
    days = [as_of.date() - timedelta(days=k) for k in range(60, -1, -1)]
    layer = BottleneckSignal(
        theme_id="ai_datacenter",
        layer_id="power",
        layer_name="Power generation and grid equipment",
        ticker=None,
        role=None,
        curated=False,
        investable=False,
        layer_score=79.0,
        score=79.0,
        components={"tightness_z": 4.0, "price_trend": 0.89, "price_deceleration": 0.0},
        thesis="Power demand is outrunning grid and turbine supply.",
        mentions={
            "tightening": [SeriesPoint(day=d, value=1.0 + i % 3) for i, d in enumerate(days)],
            "easing": [SeriesPoint(day=d, value=0.5) for d in days[::7]],
        },
        series={
            "fred:WPU0543": [
                SeriesPoint(day=date(2026, m, 1), value=100.0 + m) for m in range(1, 11)
            ]
        },
        as_of=as_of,
    )
    fig = charts.bottleneck_mentions(layer, 7)
    assert [t.name for t in fig.data] == ["tightening", "easing (new supply, lower prices)"]
    assert all(v <= 0 for v in fig.data[1].y) and "tightness z +4.0" in fig.layout.title.text
    assert any("last 7 days" in a.text for a in fig.layout.annotations)
    fig = charts.bottleneck_price_series(
        layer, {"fred:WPU0543": "PPI: industrial electric power"}, 90
    )
    assert fig.data[0].name == "PPI: industrial electric power"
    # rebased to 100 at the first observation inside the 180-day history (2026-05-01)
    assert abs(fig.data[0].y[4] - 100.0) < 1e-9 and fig.data[0].y[0] < 100.0
    assert any(
        "deceleration 0.00" in a.text and "trend +0.89" in a.text for a in fig.layout.annotations
    )
    companies = [
        layer.model_copy(
            update={
                "ticker": "HON",
                "role": "supplier",
                "curated": True,
                "score": 37.0,
                "components": {"exposure": 0.47, "priced_in": 0.1},
            }
        ),
        layer.model_copy(
            update={
                "ticker": "GEV",
                "role": "supplier",
                "score": 79.0,
                "components": {"exposure": 1.0, "priced_in": 0.0},
            }
        ),
    ]
    fig = charts.bottleneck_score_scatter(companies)
    assert [t.name for t in fig.data] == ["on the good-to-own list", "not investable here"]
    assert list(fig.data[0].text) == ["HON"] and list(fig.data[1].text) == ["GEV"]
    # a layer row without series (an older snapshot) still draws an empty, captioned chart
    bare = layer.model_copy(update={"mentions": {}, "series": {}, "components": {}})
    assert len(charts.bottleneck_mentions(bare, 7).data) == 2
    assert any(
        "no price data" in a.text
        for a in charts.bottleneck_price_series(bare, {}, 90).layout.annotations
    )
