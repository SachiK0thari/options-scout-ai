"""FastAPI app (section 9). Runs execute in a background thread; clients poll or stream SSE."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from options_scout import __version__
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
    Health,
    MarketDataAuth,
    QualityUniverseEntry,
    QualityUniverseResponse,
    RecommendRequest,
    ResumeRequest,
    RunStatus,
    ScreenRequest,
    ScreenResponse,
)
from options_scout.config import get_config
from options_scout.core.models import ScreeningReport, UserProfile
from options_scout.data.market import MarketData, MarketDataError
from options_scout.observability import configure_logging, get_logger

configure_logging()
log = get_logger(component="api")
app = FastAPI(
    title="OptionsScout AI",
    version=__version__,
    description="Educational options screener. Not investment advice. No order placement.",
)

_RATE_LIMIT_PER_MIN = int(os.environ.get("OPTIONS_SCOUT_RATE_LIMIT_PER_MIN", "30"))
_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


class RunRegistry:
    """In-process run bookkeeping; the graph state itself lives in the SQLite checkpointer."""

    def __init__(self) -> None:
        self.cfg = get_config()
        self.deps = Deps.from_config(self.cfg)
        self.ckpt = sqlite_checkpointer(self.cfg.paths.checkpoint_db)
        self.graph = build_graph(self.deps, self.ckpt)
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.status: dict[str, str] = {}
        self.threads: dict[str, threading.Thread] = {}

    def _consume(self, thread_id: str, it: Any) -> None:
        try:
            for update in it:
                for node, payload in update.items():
                    if node == "__interrupt__":
                        self.status[thread_id] = "interrupted"
                        self.events[thread_id].append(
                            {"event": "interrupt", "node": node, "ts": time.time()}
                        )
                        continue
                    self.events[thread_id].append(
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
            self.events[thread_id].append({"event": "error", "detail": str(exc), "ts": time.time()})
        finally:
            self.events[thread_id].append(
                {"event": "end", "status": self.status[thread_id], "ts": time.time()}
            )

    def graph_for(self, auth: MarketDataAuth | None) -> Any:
        """The shared graph, or one bound to the caller's market-data provider / API key."""
        if auth is None:
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

    def start(
        self,
        *,
        request_text: str = "",
        profile: UserProfile | None = None,
        thread_id: str | None = None,
        market_data: MarketDataAuth | None = None,
    ) -> str:
        thread_id = thread_id or uuid.uuid4().hex[:16]
        if thread_id in self.threads and self.threads[thread_id].is_alive():
            raise HTTPException(409, "thread is already running")
        graph = self.graph_for(market_data)
        state = initial_state(request_text, profile.model_dump(mode="json") if profile else None)
        self.events[thread_id] = []
        self.status[thread_id] = "running"
        t = threading.Thread(
            target=self._consume,
            args=(thread_id, stream_run(graph, state, thread_id)),
            daemon=True,
        )
        self.threads[thread_id] = t
        t.start()
        return thread_id

    def resume(self, thread_id: str, answer: dict[str, Any]) -> None:
        if self.status.get(thread_id) != "interrupted":
            raise HTTPException(409, "thread is not waiting for human review")
        self.status[thread_id] = "running"
        t = threading.Thread(
            target=self._consume,
            args=(thread_id, stream_resume(self.graph, thread_id, answer)),
            daemon=True,
        )
        self.threads[thread_id] = t
        t.start()

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


def _auth(request: Request) -> None:
    key = os.environ.get("OPTIONS_SCOUT_API_KEY")
    if key and request.headers.get("x-api-key") != key:
        raise HTTPException(401, "invalid or missing X-API-Key")
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    with _lock:
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= _RATE_LIMIT_PER_MIN:
            raise HTTPException(429, "rate limit exceeded")
        q.append(now)


@app.get("/healthz", response_model=Health)
def healthz() -> Health:
    reg = registry()
    sources = {"market_data": reg.deps.md.source.name, **reg.deps.md.status}
    sources["llm"] = reg.deps.llm.provider.name
    return Health(
        status="ok",
        data_mode=reg.cfg.settings.data_mode,
        llm_mode=reg.deps.llm.mode,
        sources=sources,
        version=__version__,
    )


@app.post("/v1/screen", response_model=ScreenResponse, dependencies=[Depends(_auth)])
def screen(req: ScreenRequest) -> ScreenResponse:
    if not req.request_text and req.profile is None:
        raise HTTPException(422, "provide request_text or profile")
    reg = registry()
    thread_id = reg.start(
        request_text=req.request_text or "",
        profile=req.profile,
        thread_id=req.thread_id,
        market_data=req.market_data,
    )
    return ScreenResponse(thread_id=thread_id, status="running")


@app.post("/v1/recommend", response_model=ScreenResponse, dependencies=[Depends(_auth)])
def recommend(req: RecommendRequest) -> ScreenResponse:
    """Simple front door: buying power + strategy (+ optional market-data key) → run."""
    reg = registry()
    thread_id = reg.start(profile=req.to_profile(), market_data=req.market_data)
    return ScreenResponse(thread_id=thread_id, status="running")


@app.get("/v1/quality-universe", response_model=QualityUniverseResponse)
def quality_universe() -> QualityUniverseResponse:
    q = registry().cfg.quality
    return QualityUniverseResponse(
        gates=q.gates.model_dump(),
        tickers=[QualityUniverseEntry(**t.model_dump()) for t in q.tickers],
    )


@app.get("/v1/runs/{thread_id}", response_model=RunStatus, dependencies=[Depends(_auth)])
def run_status(thread_id: str) -> RunStatus:
    reg = registry()
    status = reg.status.get(thread_id, "unknown")
    if status == "unknown":
        raise HTTPException(404, "unknown thread")
    values = reg.state(thread_id)
    visited = list(values.get("nodes_visited", []))
    partial: dict[str, Any] = {}
    for key in ("profile", "regime", "allocation", "portfolio", "risk", "verification"):
        v = values.get(key)
        if v is not None:
            partial[key] = v.model_dump(mode="json") if hasattr(v, "model_dump") else v
    if values.get("trends"):
        partial["trends"] = [t.model_dump(mode="json") for t in values["trends"][:10]]
    return RunStatus(
        thread_id=thread_id,
        status=status,
        current_node=visited[-1] if visited else None,
        nodes_visited=visited,
        interrupt=pending_interrupt(reg.graph, thread_id) if status == "interrupted" else None,
        errors=list(values.get("errors", [])),
        partial=partial,
    )


@app.get("/v1/runs/{thread_id}/stream", dependencies=[Depends(_auth)])
async def run_stream(thread_id: str) -> EventSourceResponse:
    reg = registry()
    if thread_id not in reg.events:
        raise HTTPException(404, "unknown thread")

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
    "/v1/runs/{thread_id}/resume", response_model=ScreenResponse, dependencies=[Depends(_auth)]
)
def resume(thread_id: str, req: ResumeRequest) -> ScreenResponse:
    reg = registry()
    if thread_id not in reg.status:
        raise HTTPException(404, "unknown thread")
    reg.resume(thread_id, req.answer)
    return ScreenResponse(thread_id=thread_id, status="running")


@app.get("/v1/runs/{thread_id}/report", dependencies=[Depends(_auth)])
def report(thread_id: str, format: str = "json") -> Any:
    reg = registry()
    if reg.status.get(thread_id) != "completed":
        raise HTTPException(409, f"run status is {reg.status.get(thread_id, 'unknown')}")
    values = reg.state(thread_id)
    rep = values.get("report")
    if not isinstance(rep, ScreeningReport):
        raise HTTPException(404, "report not available")
    if format == "md":
        return PlainTextResponse(values.get("report_markdown") or "", media_type="text/markdown")
    return rep.model_dump(mode="json")


@app.get("/v1/trends", dependencies=[Depends(_auth)])
def trends() -> list[dict[str, Any]]:
    reg = registry()
    latest = reg.deps.trend_store.latest(10**6)
    if latest is None and reg.deps.scout is not None:
        run = reg.deps.scout.run()
        reg.deps.trend_store.save(run)
        latest = run.signals
    return [t.model_dump(mode="json") for t in (latest or [])]
