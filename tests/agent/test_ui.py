"""Streamlit smoke tests for the one-page UI (fixture mode, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "ui" / "streamlit_app.py"


def _app(timeout: int = 300) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=timeout)
    at.run()
    assert not at.exception, at.exception
    return at


def _radio(at: AppTest, label_fragment: str):  # type: ignore[no-untyped-def]
    return next(r for r in at.radio if label_fragment in r.label)


def test_page_renders_with_form_and_disclaimer() -> None:
    at = _app(120)
    assert any("Educational screening tool" in w.value for w in at.warning)
    assert at.number_input[0].label.startswith("Buying power")
    assert [c for c in _radio(at, "looking for").options] == [
        "Cash-secured puts",
        "LEAPS calls",
        "Both",
    ]
    assert "Bundled sample data (offline)" in _radio(at, "prices").options
    assert "Tradier (paste your API key)" in _radio(at, "prices").options
    assert any("Results will appear here" in i.value for i in at.info)


def test_csp_only_run_shows_quality_screen_and_puts_but_no_leaps() -> None:
    at = _app()
    at.number_input[0].set_value(60_000.0)
    _radio(at, "looking for").set_value("Cash-secured puts")
    at.button[0].click().run()
    assert not at.exception, at.exception
    assert at.session_state["thread_id"]
    headers = [s.value for s in at.subheader]
    assert any("passed the good-to-own screen" in h for h in headers)
    assert any("Cash-secured put candidates" in h for h in headers)
    assert not any("LEAPS call candidates" in h for h in headers)
    assert any("Verifier: PASS" in c.value for c in at.caption)
    # risky fixture names never appear in any table (quality screen, candidates, positions)
    for df in at.dataframe:
        frame = df.value
        if "On good-to-own list" in frame.columns:
            continue  # the trend board legitimately lists non-curated brands, flagged as such
        for col in ("Ticker", "Candidate"):
            if col in frame.columns:
                cells = " ".join(map(str, frame[col].tolist()))
                assert not any(t in cells for t in ("CMG", "DECK", "ELF")), (col, cells)


def test_leaps_only_run() -> None:
    at = _app()
    _radio(at, "looking for").set_value("LEAPS calls")
    at.button[0].click().run()
    assert not at.exception, at.exception
    headers = [s.value for s in at.subheader]
    assert any("LEAPS call candidates" in h for h in headers)
    assert not any("Cash-secured put candidates" in h for h in headers)


def test_tradier_without_a_key_shows_an_error_and_does_not_run() -> None:
    at = _app(120)
    _radio(at, "prices").set_value("Tradier (paste your API key)").run()
    assert not at.exception, at.exception
    assert at.text_input[-1].label == "Tradier API key"
    at.button[0].click().run()
    assert any("Paste a Tradier API key" in e.value for e in at.error)
    assert "thread_id" not in at.session_state


@pytest.mark.parametrize("choice", ["Both"])
def test_both_strategies_render_everything(choice: str) -> None:
    at = _app()
    _radio(at, "looking for").set_value(choice)
    at.button[0].click().run()
    assert not at.exception, at.exception
    headers = [s.value for s in at.subheader]
    assert any("Cash-secured put candidates" in h for h in headers)
    assert any("LEAPS call candidates" in h for h in headers)
    assert any("Plain-English summary" in h for h in headers)
