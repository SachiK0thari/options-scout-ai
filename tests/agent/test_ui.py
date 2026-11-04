"""Streamlit tests for the multi-tab app (PRD step 10.6): fixture mode, no network, ``AppTest``.

Each test drives the real script: the Setup form or the Scout chat runs the LangGraph pipeline
in-process on bundled fixtures, then the eight tabs render from the checkpointed state.
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
    "Learn",
    "Trends",
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
def test_eight_tabs_render_with_no_report() -> None:
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
    # the Learn glossary works offline, before any run
    assert any(c.value.startswith("Citation:") for c in at.caption)


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
    assert any(m.label == "Specialists run" and m.value == "8" for m in at.metric)
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
