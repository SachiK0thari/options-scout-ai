"""Streamlit smoke test: every page renders without an exception (fixture mode)."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "ui" / "streamlit_app.py"


@pytest.mark.parametrize(
    "page",
    ["Profile", "Run", "Trend Board", "Candidates", "Portfolio & Risk", "Report", "Under the Hood"],
)
def test_pages_render(page: str) -> None:
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception
    assert any("Educational screening tool" in w.value for w in at.warning)


def test_form_run_produces_report() -> None:
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.run()
    # second button on the Profile page is the form run
    buttons = at.button
    assert len(buttons) >= 2
    buttons[1].click().run()
    assert not at.exception, at.exception
    assert at.session_state["thread_id"]
    at.sidebar.radio[0].set_value("Report").run()
    assert not at.exception, at.exception
    assert any("Verifier: PASS" in c.value for c in at.caption)
