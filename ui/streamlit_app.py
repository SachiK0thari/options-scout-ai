"""OptionsScout multi-tab app: chat on Scout, a form on Setup, results and education in six tabs.

Run: make ui  (or: streamlit run ui/streamlit_app.py)

The page talks to the LangGraph pipeline in-process. Everything shown is computed by deterministic
Python; the LLM only writes explanations and every one of them passes the Compliance agent first.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parents[1]
for p in (_ROOT, _ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

st.set_page_config(page_title="OptionsScout", page_icon="🔭", layout="wide")

from ui import session  # noqa: E402
from ui.tabs import (  # noqa: E402
    candidates,
    learn,
    portfolio,
    quality,
    scout,
    setup,
    trends,
    under_the_hood,
)

RENDERERS = (
    scout.render,
    setup.render,
    quality.render,
    candidates.render,
    portfolio.render,
    learn.render,
    trends.render,
    under_the_hood.render,
)

session.banner()
st.title("🔭 OptionsScout")
view = session.current()
for tab, render in zip(st.tabs(list(session.TABS)), RENDERERS, strict=True):
    with tab:
        render(view)
        st.divider()
        session.banner()
