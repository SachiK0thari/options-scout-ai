"""Shared session state for the tabs: resources, the active thread, the chat session, run helpers.

Everything the tabs read comes through :class:`View`; everything that mutates the session goes
through the functions below, so no tab touches ``st.session_state`` keys directly.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import streamlit as st

from options_scout.agent.chat import ChatResult, ChatSession
from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    AGENT_ORDER,
    NODE_ORDER,
    build_graph,
    initial_state,
    pending_interrupt,
    sqlite_checkpointer,
    stream_resume,
    stream_run,
    thread_config,
)
from options_scout.config import AppConfig, get_config, load_env
from options_scout.core.models import ChatTurn, ScreeningReport
from options_scout.data.market import FixtureSource, MarketData
from options_scout.rag.corpus import load_corpus
from options_scout.rag.models import Document

load_env()
CFG: AppConfig = get_config()
DISCLAIMER: str = CFG.settings.disclaimer
DELAYED = "Market data is **delayed**, for education only."

SOURCE_SAMPLE = "Bundled sample data (offline)"
SOURCE_MARKETDATA = "MarketData.app (paste your API token)"
SOURCE_TRADIER = "Tradier (paste your API key)"
STRATEGY_CHOICES: dict[str, set[str]] = {
    "Cash-secured puts": {"csp"},
    "LEAPS calls": {"leaps"},
    "Both": {"csp", "leaps"},
}

TABS: tuple[str, ...] = (
    "Scout",
    "Setup",
    "Quality Screen",
    "Candidates",
    "Portfolio & Risk",
    "Goals",
    "Learn",
    "Trends & News",
    "Under the hood",
)


@st.cache_resource(show_spinner=False)
def _resources() -> tuple[Any, Deps, Any]:
    deps = Deps.from_config(CFG)
    ckpt = sqlite_checkpointer(
        CFG.paths.checkpoint_db, CFG.settings.agent.checkpoint_retention_days
    )
    return build_graph(deps, ckpt), deps, ckpt


@st.cache_resource(show_spinner=False)
def concepts() -> list[Document]:
    """The authored knowledge base, for the Learn tab's glossary (sorted by title)."""
    docs = load_corpus(CFG.rag.knowledge_dir, ("concepts",))
    return sorted(docs, key=lambda d: d.title.lower())


@st.cache_resource(show_spinner=False)
def documents(kind: str) -> list[Document]:
    """One collection of the knowledge base (``basics``, ``tax`` …), sorted by title (Phase 12)."""
    docs = load_corpus(CFG.rag.knowledge_dir, (kind,))
    return sorted(docs, key=lambda d: d.title.lower())


GRAPH, DEPS, CKPT = _resources()


# ------------------------------------------------------------------------------ chat session
def chat() -> ChatSession:
    """One ``ChatSession`` per browser session (it keeps the not-yet-written assistant turns)."""
    if "chat_session" not in st.session_state:
        st.session_state["chat_session"] = ChatSession(DEPS, CKPT, graph=GRAPH)
    session: ChatSession = st.session_state["chat_session"]
    return session


def select_market(md: MarketData) -> Any:
    """Point the session at a market-data source; returns the graph to run on. Keys live only in
    the ``MarketData`` object for this browser session and are never written anywhere."""
    graph = GRAPH if md is DEPS.md else build_graph(DEPS.with_market(md), CKPT)
    session = chat()
    session.graph = graph
    session.deps = DEPS if md is DEPS.md else DEPS.with_market(md)
    st.session_state["source_name"] = md.source.name
    return graph


def market_for(choice: str, api_key: str, sandbox: bool) -> MarketData:
    """Build the market-data facade the user asked for. Keys live only in this request."""
    if choice == SOURCE_SAMPLE:
        if isinstance(DEPS.md.source, FixtureSource):
            return DEPS.md
        return MarketData.from_config(CFG, mode="fixture")
    if choice == SOURCE_MARKETDATA:
        # an empty field falls back to MARKETDATA_TOKEN in the environment; neither -> clear error
        return MarketData.from_config(
            CFG, mode="live", provider="marketdata", api_key=api_key.strip() or None
        )
    cfg = CFG.model_copy(
        update={
            "settings": CFG.settings.model_copy(
                update={
                    "market_data": CFG.settings.market_data.model_copy(
                        update={
                            "tradier": CFG.settings.market_data.tradier.model_copy(
                                update={"sandbox": sandbox}
                            )
                        }
                    )
                }
            )
        }
    )
    return MarketData.from_config(cfg, mode="live", provider="tradier", api_key=api_key)


def has_fixtures() -> bool:
    return isinstance(DEPS.md.source, FixtureSource) or (CFG.paths.fixtures_dir / "market").exists()


# ------------------------------------------------------------------------------ threads
def new_thread_id() -> str:
    # unguessable (W37: a timestamp id was found in 151 guesses); no "-<digits>" suffix, because
    # the chat session derives "<thread>-2" from it
    return f"ui{uuid.uuid4().hex}"


def thread_id() -> str | None:
    tid: str | None = st.session_state.get("thread_id")
    return tid


def set_thread(tid: str, *, interrupted: bool) -> None:
    st.session_state["thread_id"] = tid
    if interrupted:
        st.session_state["interrupted"] = True
    else:
        st.session_state.pop("interrupted", None)


def learn_thread_id() -> str:
    if "learn_thread" not in st.session_state:
        st.session_state["learn_thread"] = f"learn{uuid.uuid4().hex}"
    tid: str = st.session_state["learn_thread"]
    return tid


# ------------------------------------------------------------------------------ running
ProgressFn = Callable[[str, dict[str, Any]], None]


def node_progress(progress: Any) -> ProgressFn:
    """An ``on_update`` callback that drives a ``st.progress`` bar through ``NODE_ORDER``."""

    def on_update(node: str, _payload: dict[str, Any]) -> None:
        if node in NODE_ORDER:
            idx = NODE_ORDER.index(node) + 1
            progress.progress(min(idx / len(NODE_ORDER), 1.0), text=f"{node} ✓")
        elif node in AGENT_ORDER:
            progress.progress(progress_value(node), text=f"{node.replace('_', ' ')} finished")

    return on_update


def progress_value(agent: str) -> float:
    return (AGENT_ORDER.index(agent) + 1) / len(AGENT_ORDER)


def run_screen(graph: Any, profile: dict[str, Any], tid: str, on_update: ProgressFn) -> None:
    """Run the full graph from a form profile (Setup tab); consumes the stream synchronously."""
    interrupted = False
    for update in stream_run(graph, initial_state("", profile), tid):
        for node, payload in update.items():
            if node == "__interrupt__":
                interrupted = True
                continue
            on_update(node, payload if isinstance(payload, dict) else {})
    set_thread(tid, interrupted=interrupted)


def resume_screen(graph: Any, tid: str, answer: dict[str, Any], on_update: ProgressFn) -> None:
    interrupted = False
    for update in stream_resume(graph, tid, answer):
        for node, payload in update.items():
            if node == "__interrupt__":
                interrupted = True
                continue
            on_update(node, payload if isinstance(payload, dict) else {})
    set_thread(tid, interrupted=interrupted)


def send_message(text: str, on_update: ProgressFn | None = None) -> ChatResult:
    """One chat turn on the active thread (a new one when the conversation is empty)."""
    tid = thread_id() or new_thread_id()
    result = chat().send(tid, text, on_update=on_update)
    set_thread(result.thread_id, interrupted=result.status == "interrupted")
    return result


def resume_message(answer: dict[str, Any], on_update: ProgressFn | None = None) -> ChatResult:
    tid = thread_id()
    assert tid is not None
    result = chat().resume(tid, answer, on_update=on_update)
    set_thread(result.thread_id, interrupted=result.status == "interrupted")
    return result


# ------------------------------------------------------------------------------ the view
@dataclass
class View:
    """Read-only snapshot of the session that every tab renders from."""

    cfg: AppConfig
    deps: Deps
    thread_id: str | None
    state: dict[str, Any]
    report: ScreeningReport | None
    history: list[ChatTurn]
    interrupt: dict[str, Any] | None

    @property
    def markdown(self) -> str:
        md: str = self.state.get("report_markdown") or ""
        return md

    @property
    def show_csp(self) -> bool:
        return self.report is not None and "csp" in self.report.profile.strategies

    @property
    def show_leaps(self) -> bool:
        return self.report is not None and bool({"leaps", "pmcc"} & self.report.profile.strategies)

    @property
    def source_name(self) -> str:
        name: str = st.session_state.get("source_name") or DEPS.md.source.name
        return name


def current() -> View:
    tid = thread_id()
    state: dict[str, Any] = {}
    interrupt: dict[str, Any] | None = None
    history: list[ChatTurn] = []
    graph = chat().graph
    if tid:
        snap = graph.get_state(thread_config(tid))
        state = dict(getattr(snap, "values", {}) or {})
        history = chat().history(tid)
        if st.session_state.get("interrupted"):
            interrupt = pending_interrupt(graph, tid)
            if interrupt is None:
                st.session_state.pop("interrupted", None)
    return View(
        cfg=CFG,
        deps=chat().deps,
        thread_id=tid,
        state=state,
        report=state.get("report"),
        history=history,
        interrupt=interrupt,
    )


# ------------------------------------------------------------------------------ formatting
def banner() -> None:
    st.warning(f"⚠️ {DISCLAIMER}  {DELAYED}")


def education_label() -> None:
    st.caption(
        "📘 **Education, not advice.** Definitions come from the cited knowledge base; "
        "numbers come from the deterministic screeners."
    )


def money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:,.0f}"


def md(text: str) -> str:
    """Escape dollar signs for Markdown/captions, where ``$…$`` would be rendered as LaTeX."""
    return text.replace("$", r"\$")


def pct(x: float | None, d: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def compliance_badge(report: Any, key: str) -> None:
    """The small Compliance ✓ badge with an expander listing the checks that ran (13.1)."""
    if report is None:
        st.caption("Compliance: no report attached")
        return
    mark = "✓" if report.passed else "✗"
    with st.expander(
        f"Compliance {mark} · {len(report.checks)} checks · audit {report.audit_id}", expanded=False
    ):
        for c in report.checks:
            m = "✓" if c.passed else ("⚠" if c.severity == "warn" else "✗")
            st.markdown(f"{m} `{c.name}`: {c.detail}")
        v = report.verification
        st.caption(
            f"{v.numbers_checked} numbers checked, {len(v.ungrounded_numbers)} ungrounded · "
            f"{v.citations_checked} citation tag(s) checked · attempt {report.attempts}"
        )


def citations_expander(citations: list[Any], key: str) -> None:
    if not citations:
        return
    with st.expander(f"Sources ({len(citations)})"):
        for c in citations:
            tag = f"**[{c.tag}]** " if c.tag else ""
            st.markdown(f"{tag}[{c.title}]({c.url}) — {c.kind}  \n> {c.quote}")
