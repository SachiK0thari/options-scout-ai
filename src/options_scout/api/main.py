"""FastAPI app (section 9). Runs execute in a background thread; clients poll or stream SSE."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from options_scout import __version__
from options_scout.agent.chat import ChatSession
from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    build_graph,
    initial_state,
    pending_interrupt,
    sqlite_checkpointer,
    stream_resume,
    stream_run,
    thread_config,
)
from options_scout.api.schemas import (
    ChatRequest,
    Health,
    MarketDataAuth,
    QualityUniverseEntry,
    QualityUniverseResponse,
    RecommendRequest,
    ResumeRequest,
    RunStatus,
    ScreenRequest,
    ScreenResponse,
    ThreadStatus,
)
from options_scout.config import get_config, load_env
from options_scout.core.compliance import WITHHELD_NOTICE
from options_scout.core.models import ScreeningReport, UserProfile
from options_scout.data.market import MarketData, MarketDataError
from options_scout.env import (
    DEFAULT_RATE_LIMIT_PER_MIN,
    EnvConfigError,
    check_startup,
    env_settings,
)
from options_scout.observability import configure_logging, get_logger
from options_scout.rag.retriever import KnowledgeBaseEmptyError, ensure_knowledge_base

configure_logging()
log = get_logger(component="api")
load_env()


def _anonymous_allowed() -> bool:
    return os.environ.get("OPTIONS_SCOUT_ALLOW_ANONYMOUS", "").strip() == "1"


def check_deployment() -> None:
    """W37: the API refuses to start open. A key is required unless anonymous access is asked for
    explicitly with ``OPTIONS_SCOUT_ALLOW_ANONYMOUS=1`` (local development only)."""
    if not os.environ.get("OPTIONS_SCOUT_API_KEY") and not _anonymous_allowed():
        raise RuntimeError(
            "OPTIONS_SCOUT_API_KEY is not set. Set it (clients send it as X-API-Key), or set "
            "OPTIONS_SCOUT_ALLOW_ANONYMOUS=1 for a local, unpublished development server."
        )


def _initial_rate_limit() -> int:
    """The per-IP limit read at import. A bad value never crashes the import (W42): it falls back
    to the default here, and :func:`startup_checks` then refuses to start with the reason."""
    try:
        return env_settings().rate_limit_per_min
    except EnvConfigError:
        return DEFAULT_RATE_LIMIT_PER_MIN


def knowledge_chunks(reg: RunRegistry) -> int:
    """Chunks in the knowledge base; 0 when it is empty (W42). Counted once per registry: the
    corpus is fixed for the life of the process, and the count needs its own connection."""
    if reg.knowledge_chunks is None:
        try:
            reg.knowledge_chunks = ensure_knowledge_base(reg.cfg)
        except KnowledgeBaseEmptyError:
            reg.knowledge_chunks = 0
    return reg.knowledge_chunks


def startup_checks() -> None:
    """Everything that must hold before the API serves (W42): every ``OPTIONS_SCOUT_*`` value and
    the YAML config parse, an API key is set (W37), and the knowledge base has documents."""
    global _RATE_LIMIT_PER_MIN
    settings = check_startup()
    _RATE_LIMIT_PER_MIN = settings.rate_limit_per_min
    check_deployment()
    reg = registry()
    reg.knowledge_chunks = ensure_knowledge_base(reg.cfg)  # raises KnowledgeBaseEmptyError
    if not reg.deps.md.available:
        log.warning("market_data_unavailable", reason=reg.deps.md.unavailable_reason)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    startup_checks()
    yield
    if _registry is not None:
        _registry.executor.shutdown(wait=False, cancel_futures=True)


_DOCS = _anonymous_allowed() or os.environ.get("OPTIONS_SCOUT_API_DOCS", "").strip() == "1"
app = FastAPI(
    title="OptionsScout AI",
    version=__version__,
    description="Educational options screener. Not investment advice. No order placement.",
    lifespan=_lifespan,
    # the schema and the docs pages are not behind the key, so they are off unless asked for
    docs_url="/docs" if _DOCS else None,
    redoc_url="/redoc" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
)

THREAD_TOKEN_HEADER = "X-Thread-Token"
_RATE_LIMIT_PER_MIN = _initial_rate_limit()
_SWEEP_SECONDS = 60.0
_last_sweep = 0.0
_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def api_checkpoint_path(checkpoint_db: Path) -> Path:
    """The API's own checkpoint file beside the UI's (``checkpoints.sqlite`` →
    ``checkpoints-api.sqlite``), so neither front end can open the other's threads (W37)."""
    return checkpoint_db.with_name(f"{checkpoint_db.stem}-api{checkpoint_db.suffix}")


class ThreadTokens:
    """Who may use a thread: the SHA-256 of a random token issued when the thread is created.

    The token itself is returned once and never stored. Every route that takes a ``thread_id``
    checks it with ``hmac.compare_digest``; a missing or wrong token gets the same 404 as an
    unknown thread, so a guessed id reveals nothing. A thread the chat session hands off to
    (``<thread>-2``) is granted its parent's token."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS thread_tokens (thread_id TEXT PRIMARY KEY, "
                "token_sha256 TEXT NOT NULL, created_at REAL NOT NULL)"
            )
            # W39: which market source a run started on, so a resume never silently switches
            # source. Never the key itself: ``server`` or ``caller:<provider>[:<env>]``.
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS thread_sources "
                "(thread_id TEXT PRIMARY KEY, source TEXT NOT NULL)"
            )

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def issue(self, thread_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self._store(thread_id, self._digest(token))
        return token

    def grant(self, child: str, parent: str) -> None:
        """``child`` answers to the same token as ``parent`` (chat handoffs)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT token_sha256 FROM thread_tokens WHERE thread_id = ?", (parent,)
            ).fetchone()
        if row is not None:
            self._store(child, row[0])

    def _store(self, thread_id: str, digest: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO thread_tokens VALUES (?, ?, ?)",
                (thread_id, digest, time.time()),
            )

    def known(self, thread_id: str) -> bool:
        """Whether this server issued a token for ``thread_id`` (or granted it one)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM thread_tokens WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return row is not None

    def record_source(self, thread_id: str, source: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO thread_sources VALUES (?, ?)", (thread_id, source)
            )

    def source(self, thread_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT source FROM thread_sources WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return str(row[0]) if row is not None else None

    def verify(self, thread_id: str, token: str | None) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT token_sha256 FROM thread_tokens WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        expected = row[0] if row is not None else self._digest(secrets.token_urlsafe(32))
        ok = hmac.compare_digest(expected, self._digest(token or ""))
        return ok and row is not None and bool(token)


SERVER_SOURCE = "server"
_EVENTS_TTL_SECONDS = 600.0  # a finished run's event list is dropped this long after it ends
_GRAPH_TTL_SECONDS = 3600.0  # a caller-keyed graph kept for a resume is dropped after this


def source_label(auth: MarketDataAuth | None) -> str:
    """What a run's market data came from, without the key: ``server`` or
    ``caller:marketdata`` / ``caller:tradier:sandbox`` / ``caller:tradier:production``."""
    if auth is None:
        return SERVER_SOURCE
    if auth.provider == "tradier":
        return f"caller:tradier:{'sandbox' if auth.sandbox else 'production'}"
    return f"caller:{auth.provider}"


class RunRegistry:
    """Run bookkeeping. The graph state lives in the SQLite checkpointer and a run's status is
    derived from it (W39), so it survives a restart. In memory are only what a live run needs:
    its future on the bounded pool, its event list for the SSE routes, and, for a run on the
    caller's own market-data key, the graph bound to that key (the key is never persisted)."""

    def __init__(self) -> None:
        self.cfg = get_config()
        self.deps = Deps.from_config(self.cfg)
        self.checkpoint_path = api_checkpoint_path(self.cfg.paths.checkpoint_db)
        self.ckpt = sqlite_checkpointer(
            self.checkpoint_path, self.cfg.settings.agent.checkpoint_retention_days
        )
        self.tokens = ThreadTokens(self.checkpoint_path)
        self.graph = build_graph(self.deps, self.ckpt)
        self.session = ChatSession(self.deps, self.ckpt, graph=self.graph)
        agent = self.cfg.settings.agent
        self.max_workers = agent.api_max_workers
        self.max_queued = agent.api_max_queued
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="run")
        self._lock = threading.Lock()  # guards every dict below and each check-then-start
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.status: dict[str, str] = {}  # this process's last word on a run (running / failed)
        self.futures: dict[str, Future[None]] = {}
        self.graphs: dict[str, Any] = {}  # caller-keyed graphs, kept while a resume may need one
        self.finished_at: dict[str, float] = {}
        self.knowledge_chunks: int | None = None  # W42: set by the start-up check or /healthz

    # ------------------------------------------------------------------ the pool
    def _busy(self, thread_id: str) -> bool:
        fut = self.futures.get(thread_id)
        return fut is not None and not fut.done()

    def in_flight(self) -> int:
        with self._lock:
            return sum(1 for f in self.futures.values() if not f.done())

    def _submit(self, thread_id: str, job: Callable[[], None]) -> None:
        """Queue ``job`` for ``thread_id`` (caller holds ``_lock``); 429 when the pool and its
        queue are full, before anything about the run is recorded."""
        self._evict()
        if sum(1 for f in self.futures.values() if not f.done()) >= (
            self.max_workers + self.max_queued
        ):
            raise HTTPException(
                429,
                "the server is running as many screens as it can; try again shortly",
                headers={"Retry-After": "10"},
            )
        self.status[thread_id] = "running"
        self.finished_at.pop(thread_id, None)
        self.futures[thread_id] = self.executor.submit(job)

    def _finished(self, thread_id: str) -> None:
        with self._lock:
            self.finished_at[thread_id] = time.time()
            if self.status.get(thread_id) != "interrupted":
                self.graphs.pop(thread_id, None)  # no resume can follow

    def _evict(self) -> None:
        """Forget finished runs' events after a while (caller holds ``_lock``); their status
        still comes from the checkpointer."""
        now = time.time()
        for tid, ended in list(self.finished_at.items()):
            if self._busy(tid):
                continue
            age = now - ended
            if age > _GRAPH_TTL_SECONDS:
                self.graphs.pop(tid, None)
            if age > _EVENTS_TTL_SECONDS:
                for d in (self.events, self.status, self.futures):
                    d.pop(tid, None)
                if tid not in self.graphs:
                    self.finished_at.pop(tid, None)

    # ------------------------------------------------------------------ status
    def run_state(self, thread_id: str) -> str:
        """``running``, ``interrupted``, ``completed``, ``failed`` or ``unknown``, from the live
        future first and otherwise from the persisted thread state."""
        with self._lock:
            if self._busy(thread_id):
                return "running"
            live = self.status.get(thread_id)
        if live == "failed":
            return "failed"
        snap = self.graph.get_state(thread_config(thread_id))
        if not (getattr(snap, "values", None) or {}):
            # W19: runs checkpoint on exit, so a thread this server created whose process died
            # mid-run has a token but no saved state: it failed, it is not unknown
            return "failed" if self.tokens.known(thread_id) else "unknown"
        if any(getattr(t, "interrupts", ()) for t in getattr(snap, "tasks", ())):
            return "interrupted"
        if getattr(snap, "next", ()):
            return "failed"  # stopped part-way: an error, or the process ended mid-run
        return "completed"

    def _consume(self, thread_id: str, it: Any) -> None:
        events = self.events[thread_id]
        try:
            for update in it:
                for node, payload in update.items():
                    if node == "__interrupt__":
                        self.status[thread_id] = "interrupted"
                        events.append({"event": "interrupt", "node": node, "ts": time.time()})
                        continue
                    events.append(
                        {
                            "event": "node",
                            "node": node,
                            "ts": time.time(),
                            "keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
                        }
                    )
            if self.status.get(thread_id) != "interrupted":
                self.status[thread_id] = "completed"
        except Exception as exc:
            log.error("run_failed", thread_id=thread_id, error=str(exc))
            self.status[thread_id] = "failed"
            events.append({"event": "error", "detail": str(exc), "ts": time.time()})
        finally:
            events.append({"event": "end", "status": self.status[thread_id], "ts": time.time()})
            self._finished(thread_id)

    # ------------------------------------------------------------------ graphs
    def graph_for(self, auth: MarketDataAuth | None) -> Any:
        """The shared graph, or one bound to the caller's market-data provider / API key."""
        if auth is None:
            if not self.deps.md.available:  # W42: say so up front, not as a failed run
                raise HTTPException(422, self.deps.md.unavailable_reason)
            return self.graph
        key = auth.api_key.get_secret_value() if auth.api_key else None
        cfg = self.cfg
        if auth.provider == "tradier":
            md_settings = cfg.settings.market_data
            cfg = cfg.model_copy(
                update={
                    "settings": cfg.settings.model_copy(
                        update={
                            "market_data": md_settings.model_copy(
                                update={
                                    "tradier": md_settings.tradier.model_copy(
                                        update={"sandbox": auth.sandbox}
                                    )
                                }
                            )
                        }
                    )
                }
            )
        try:
            md = MarketData.from_config(cfg, mode="live", provider=auth.provider, api_key=key)
        except MarketDataError as exc:
            raise HTTPException(422, str(exc)) from exc
        return build_graph(self.deps.with_market(md), self.ckpt)

    def _resume_graph(self, thread_id: str, auth: MarketDataAuth | None) -> Any:
        """The graph a resume must use: the one the run started on, never another source."""
        started = self.tokens.source(thread_id) or SERVER_SOURCE
        if started == SERVER_SOURCE:
            if auth is not None:
                raise HTTPException(
                    422, "this run started on the server's market data; resume without market_data"
                )
            return self.graph
        if auth is not None:
            given = source_label(auth)
            if given != started:
                raise HTTPException(
                    422,
                    f"this run started on {started}; resume with the same market_data "
                    f"(got {given})",
                )
            graph = self.graph_for(auth)
            self.graphs[thread_id] = graph
            return graph
        graph = self.graphs.get(thread_id)
        if graph is None:
            raise HTTPException(
                409,
                f"this run started on your own market-data key ({started}), which the server "
                "does not keep after a restart or a long wait. Resume with the same market_data "
                "to continue.",
            )
        return graph

    # ------------------------------------------------------------------ runs
    def start(
        self,
        *,
        request_text: str = "",
        profile: UserProfile | None = None,
        market_data: MarketDataAuth | None = None,
        holdings: list[Any] | None = None,
    ) -> tuple[str, str]:
        """Start a screen on a new, server-generated thread; returns ``(thread_id, token)``."""
        thread_id = uuid.uuid4().hex
        graph = self.graph_for(market_data)
        state = initial_state(request_text, profile.model_dump(mode="json") if profile else None)
        if holdings:
            state["holdings"] = list(holdings)  # Phase 12: the seventh constraint applies
        with self._lock:
            self.events[thread_id] = []
            try:
                self._submit(
                    thread_id,
                    lambda: self._consume(thread_id, stream_run(graph, state, thread_id)),
                )
            except HTTPException:
                del self.events[thread_id]
                raise
            if market_data is not None:
                self.graphs[thread_id] = graph
            self.tokens.record_source(thread_id, source_label(market_data))
            token = self.tokens.issue(thread_id)
        return thread_id, token

    def resume(
        self, thread_id: str, answer: dict[str, Any], market_data: MarketDataAuth | None = None
    ) -> None:
        state = self.run_state(thread_id)
        with self._lock:
            if self._busy(thread_id):
                raise HTTPException(409, "thread is already running")
            if state != "interrupted":
                raise HTTPException(409, "thread is not waiting for human review")
            graph = self._resume_graph(thread_id, market_data)
            previous = self.events.get(thread_id)
            self.events[thread_id] = []  # a new stream for the resumed leg
            try:
                self._submit(
                    thread_id,
                    lambda: self._consume(thread_id, stream_resume(graph, thread_id, answer)),
                )
            except HTTPException:
                if previous is not None:
                    self.events[thread_id] = previous
                raise

    def chat(self, thread_id: str, message: str) -> int:
        """Run one conversation turn on the pool; events land on ``thread_id``'s list. Returns
        the index of this turn's first event."""

        def on_update(node: str, payload: dict[str, Any]) -> None:
            if node == "__interrupt__":
                self.events[thread_id].append(
                    {"event": "interrupt", "node": node, "ts": time.time()}
                )
                return
            self.events[thread_id].append(
                {"event": "node", "node": node, "ts": time.time(), "keys": sorted(payload.keys())}
            )

        def work() -> None:
            try:
                result = self.session.send(thread_id, message, on_update=on_update)
                if result.new_thread_id:
                    self.tokens.grant(result.new_thread_id, thread_id)  # same owner
                    self.tokens.record_source(result.new_thread_id, SERVER_SOURCE)
                    with self._lock:
                        self.status[result.new_thread_id] = result.status
                        self.events.setdefault(result.new_thread_id, []).append(
                            {"event": "end", "status": result.status, "ts": time.time()}
                        )
                        self.finished_at[result.new_thread_id] = time.time()
                    self.events[thread_id].append(
                        {
                            "event": "handoff",
                            "new_thread_id": result.new_thread_id,
                            "ts": time.time(),
                        }
                    )
                self.status[thread_id] = (
                    "interrupted"
                    if result.status == "interrupted" and not result.new_thread_id
                    else "completed"
                )
                self.events[thread_id].append(
                    {
                        "event": "turn",
                        "ts": time.time(),
                        "turn": result.turn.model_dump(mode="json"),
                        "thread_id": result.thread_id,
                        "status": result.status,
                        "interrupt": result.interrupt,
                    }
                )
            except Exception as exc:
                log.error("chat_failed", thread_id=thread_id, error=str(exc))
                self.status[thread_id] = "failed"
                self.events[thread_id].append(
                    {"event": "error", "detail": str(exc), "ts": time.time()}
                )
            finally:
                self.events[thread_id].append(
                    {"event": "end", "status": self.status[thread_id], "ts": time.time()}
                )
                self._finished(thread_id)

        with self._lock:
            if self._busy(thread_id):
                raise HTTPException(409, "thread is already running")
            events = self.events.setdefault(thread_id, [])
            start = len(events)
            self._submit(thread_id, work)
        return start

    def state(self, thread_id: str) -> dict[str, Any]:
        snap = self.graph.get_state(thread_config(thread_id))
        values: dict[str, Any] = dict(getattr(snap, "values", {}) or {})
        return values


_registry: RunRegistry | None = None


def registry() -> RunRegistry:
    global _registry
    if _registry is None:
        _registry = RunRegistry()
    return _registry


def client_ip(request: Request) -> str:
    """The caller's address. ``X-Forwarded-For`` is trusted only with
    ``OPTIONS_SCOUT_TRUSTED_PROXY=1`` (the API sits behind one proxy that appends the address it
    saw): then the right-most entry is used, the one a client cannot forge."""
    direct = request.client.host if request.client else "unknown"
    if os.environ.get("OPTIONS_SCOUT_TRUSTED_PROXY", "").strip() == "1":
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        hops = [h for h in hops if h]
        if hops:
            return hops[-1]
    return direct


def _sweep(now: float) -> None:
    """Drop limiter buckets idle for a minute, at most once a minute (caller holds ``_lock``)."""
    global _last_sweep
    if now - _last_sweep < _SWEEP_SECONDS:
        return
    _last_sweep = now
    for ip in [ip for ip, q in _hits.items() if not q or now - q[-1] > 60]:
        del _hits[ip]


def _limit(request: Request) -> None:
    ip = client_ip(request)
    now = time.time()
    with _lock:
        _sweep(now)
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= _RATE_LIMIT_PER_MIN:
            retry = max(1, math.ceil(60 - (now - q[0])))
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(retry)})
        q.append(now)


def _key_ok(request: Request) -> bool:
    key = os.environ.get("OPTIONS_SCOUT_API_KEY")
    if not key:
        return _anonymous_allowed()
    given = request.headers.get("x-api-key") or ""
    return hmac.compare_digest(given.encode("utf-8"), key.encode("utf-8"))


def _auth(request: Request) -> None:
    """Every request is metered first, so failed key guesses count against the limit too."""
    _limit(request)
    if not os.environ.get("OPTIONS_SCOUT_API_KEY") and not _anonymous_allowed():
        raise HTTPException(503, "server misconfigured: OPTIONS_SCOUT_API_KEY is not set")
    if not _key_ok(request):
        raise HTTPException(401, "invalid or missing X-API-Key")


def _owned(thread_id: str, request: Request) -> None:
    """404 unless the request carries this thread's token (the same answer as for no thread)."""
    if not registry().tokens.verify(thread_id, request.headers.get(THREAD_TOKEN_HEADER)):
        raise HTTPException(404, "unknown thread")


@app.get("/healthz", response_model=Health, response_model_exclude_none=True)
def healthz(request: Request, response: Response) -> Health:
    """Liveness for anyone (the container healthcheck); data mode and sources only with the key.

    W42: the knowledge-base chunk count is always reported, and an empty knowledge base is a 503
    so the container healthcheck fails. Nothing here touches the market source."""
    reg = registry()
    chunks = knowledge_chunks(reg)
    status = "ok"
    if chunks == 0 and not reg.cfg.rag.allow_empty_corpus:
        status = "knowledge base empty"
        response.status_code = 503
    if not _key_ok(request):
        return Health(status=status, version=__version__, knowledge_chunks=chunks)
    sources = {"market_data": reg.deps.md.source.name, **reg.deps.md.status}
    sources["llm"] = reg.deps.llm.provider.name
    return Health(
        status=status,
        knowledge_chunks=chunks,
        data_mode=reg.cfg.settings.data_mode,
        llm_mode=reg.deps.llm.mode,
        sources=sources,
        version=__version__,
    )


@app.post("/v1/screen", response_model=ScreenResponse, dependencies=[Depends(_auth)])
def screen(req: ScreenRequest) -> ScreenResponse:
    if not req.request_text and req.profile is None:
        raise HTTPException(422, "provide request_text or profile")
    if req.thread_id:
        raise HTTPException(422, "thread ids are generated by the server; omit thread_id")
    reg = registry()
    thread_id, token = reg.start(
        request_text=req.request_text or "",
        profile=req.profile,
        market_data=req.market_data,
        holdings=req.holdings,
    )
    return ScreenResponse(thread_id=thread_id, status="running", thread_token=token)


@app.post("/v1/recommend", response_model=ScreenResponse, dependencies=[Depends(_auth)])
def recommend(req: RecommendRequest) -> ScreenResponse:
    """Simple front door: buying power + strategy (+ optional market-data key) → run."""
    reg = registry()
    thread_id, token = reg.start(
        profile=req.to_profile(), market_data=req.market_data, holdings=req.holdings
    )
    return ScreenResponse(thread_id=thread_id, status="running", thread_token=token)


@app.get(
    "/v1/quality-universe", response_model=QualityUniverseResponse, dependencies=[Depends(_auth)]
)
def quality_universe() -> QualityUniverseResponse:
    q = registry().cfg.quality
    return QualityUniverseResponse(
        gates=q.gates.model_dump(),
        tickers=[QualityUniverseEntry(**t.model_dump()) for t in q.tickers],
    )


_OWNED = [Depends(_auth), Depends(_owned)]  # metered and keyed, then the thread's token


@app.get("/v1/runs/{thread_id}", response_model=RunStatus, dependencies=_OWNED)
def run_status(thread_id: str) -> RunStatus:
    reg = registry()
    status = reg.run_state(thread_id)
    if status == "unknown":
        raise HTTPException(404, "unknown thread")
    values = reg.state(thread_id)
    visited = list(values.get("nodes_visited", []))
    rep = values.get("report")
    withheld = status == "completed" and isinstance(rep, ScreeningReport) and rep.withheld
    if withheld:
        status = "withheld"  # W12: finished, but the gate refused the narrative and positions
    partial: dict[str, Any] = {}
    keys = ("profile", "regime", "allocation", "portfolio", "risk", "verification")
    for key in keys:
        if withheld and key == "portfolio":
            continue
        v = values.get(key)
        if v is not None:
            partial[key] = v.model_dump(mode="json") if hasattr(v, "model_dump") else v
    if values.get("trends"):
        partial["trends"] = [t.model_dump(mode="json") for t in values["trends"][:10]]
    if values.get("bottlenecks"):  # Phase 11: the layer rows while the run is in flight
        partial["bottlenecks"] = [
            s.model_dump(mode="json") for s in values["bottlenecks"] if s.ticker is None
        ]
    return RunStatus(
        thread_id=thread_id,
        status=status,
        current_node=visited[-1] if visited else None,
        nodes_visited=visited,
        interrupt=pending_interrupt(reg.graph, thread_id) if status == "interrupted" else None,
        errors=list(values.get("errors", [])),
        partial=partial,
    )


@app.get("/v1/runs/{thread_id}/stream", dependencies=_OWNED)
async def run_stream(thread_id: str) -> EventSourceResponse:
    reg = registry()
    if thread_id not in reg.events:
        status = reg.run_state(thread_id)
        if status == "unknown":
            raise HTTPException(404, "unknown thread")
        # W39: a run from before a restart (or whose events were evicted) still gets its end
        reg.events.setdefault(thread_id, [{"event": "end", "status": status, "ts": time.time()}])

    async def gen() -> AsyncIterator[dict[str, str]]:
        i = 0
        while True:
            events = reg.events.get(thread_id, [])
            while i < len(events):
                ev = events[i]
                i += 1
                yield {"event": ev["event"], "data": json.dumps(ev)}
                if ev["event"] == "end":
                    return
            await asyncio.sleep(0.2)

    return EventSourceResponse(gen())


@app.post(
    "/v1/runs/{thread_id}/resume",
    response_model=ScreenResponse,
    response_model_exclude_none=True,
    dependencies=_OWNED,
)
def resume(thread_id: str, req: ResumeRequest) -> ScreenResponse:
    reg = registry()
    if reg.run_state(thread_id) == "unknown":
        raise HTTPException(404, "unknown thread")
    reg.resume(thread_id, req.answer, req.market_data)
    return ScreenResponse(thread_id=thread_id, status="running")


def withheld_detail(rep: ScreeningReport) -> dict[str, Any]:
    """The 409 body for a withheld run: the notice, its reason codes and the failed checks."""
    failed = [c.name for c in rep.compliance.failed_checks] if rep.compliance else []
    return {
        "status": "withheld",
        "notice": WITHHELD_NOTICE,
        "reason_codes": rep.withheld_reasons or failed,
        "failed_checks": failed,
        "audit_id": rep.compliance.audit_id if rep.compliance else None,
    }


@app.get("/v1/runs/{thread_id}/report", dependencies=_OWNED)
def report(thread_id: str, format: str = "json") -> Any:
    reg = registry()
    status = reg.run_state(thread_id)
    if status != "completed":
        raise HTTPException(409, f"run status is {status}")
    values = reg.state(thread_id)
    rep = values.get("report")
    if not isinstance(rep, ScreeningReport):
        raise HTTPException(404, "report not available")
    if rep.compliance is None or not rep.audit_log:  # 13.1: no text leaves without an audit entry
        raise HTTPException(500, "report has no compliance audit entry")
    if rep.withheld or not rep.compliance.passed:  # W12: a failing report is never released
        raise HTTPException(409, withheld_detail(rep))
    if format == "md":
        return PlainTextResponse(values.get("report_markdown") or "", media_type="text/markdown")
    return rep.model_dump(mode="json")


@app.post("/v1/chat", dependencies=[Depends(_auth)])
async def chat(req: ChatRequest, request: Request) -> EventSourceResponse:
    """One conversation turn as server-sent events: on a new conversation a ``thread`` event with
    the ``thread_id`` and its ``thread_token`` (sent once; also the ``X-Thread-Token`` response
    header), ``node`` updates, an optional ``handoff`` (a new screen started on another thread,
    owned by the same token), the assistant ``turn`` (with its ComplianceReport), then ``end``.
    Continuing a conversation needs its ``thread_id`` and the token."""
    reg = registry()
    token: str | None = None
    if req.thread_id:
        _owned(req.thread_id, request)
        thread_id = req.thread_id
    else:
        thread_id = uuid.uuid4().hex
        token = reg.tokens.issue(thread_id)
    start = reg.chat(thread_id, req.message)

    async def gen() -> AsyncIterator[dict[str, str]]:
        if token is not None:
            first = {"event": "thread", "thread_id": thread_id, "thread_token": token}
            yield {"event": "thread", "data": json.dumps(first)}
        i = start
        while True:
            events = reg.events.get(thread_id, [])
            while i < len(events):
                ev = events[i]
                i += 1
                yield {"event": ev["event"], "data": json.dumps({**ev, "thread_id": thread_id})}
                if ev["event"] == "end":
                    return
            await asyncio.sleep(0.2)

    headers = {THREAD_TOKEN_HEADER: token} if token is not None else None
    return EventSourceResponse(gen(), headers=headers)


@app.get("/v1/threads/{thread_id}", response_model=ThreadStatus, dependencies=_OWNED)
def thread_status(thread_id: str) -> ThreadStatus:
    reg = registry()
    values = reg.state(thread_id)
    turns = reg.session.history(thread_id)
    status = reg.run_state(thread_id)
    if status == "unknown":
        if not turns:
            raise HTTPException(404, "unknown thread")
        status = "idle"
    return ThreadStatus(
        thread_id=thread_id,
        status=status,
        turns=turns,
        has_report=values.get("report") is not None,
        interrupt=pending_interrupt(reg.graph, thread_id) if status == "interrupted" else None,
        related_threads=reg.session.related_threads(thread_id),
        goal_plan=values.get("goal_plan"),
    )


@app.get("/v1/bottlenecks", dependencies=[Depends(_auth)])
def bottlenecks() -> list[dict[str, Any]]:
    """The latest bottleneck board (Phase 11, section 4A): layer rows first (``ticker`` null), then
    one row per supplier with its company score, flags, thesis monitor and evidence links. Served
    from the stored snapshot when one exists, else computed and journalled."""
    reg = registry()
    store = reg.deps.bottlenecks()
    latest = store.latest(10**6)
    if latest is None:
        latest = reg.deps.bottleneck().run().signals
    return [s.model_dump(mode="json") for s in latest]


@app.get("/v1/trends", dependencies=[Depends(_auth)])
def trends() -> list[dict[str, Any]]:
    reg = registry()
    latest = reg.deps.trend_store.latest(10**6)
    if latest is None and reg.deps.scout is not None:
        run = reg.deps.scout.run()
        reg.deps.trend_store.save(run)
        latest = run.signals
    return [t.model_dump(mode="json") for t in (latest or [])]
