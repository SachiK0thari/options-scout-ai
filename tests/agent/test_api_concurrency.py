"""W39: shared stores under concurrent use, resume on the original source, atomic starts, run
status from the checkpointer, and the bounded run pool. Fixture mode, no network."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from options_scout.bottleneck.engine import BottleneckStore
from options_scout.config import AppConfig
from options_scout.rag.chunking import chunk_documents
from options_scout.rag.embeddings import HashEmbedder
from options_scout.rag.models import Document
from options_scout.rag.store import KnowledgeStore
from options_scout.social.pipeline import TrendStore

KEY = "api-test-key"
TOKEN = "X-Thread-Token"
CALLER_KEY = {"provider": "marketdata", "api_key": "caller-key-not-real"}
ANSWER = {
    "buying_power": 50000,
    "account_value": 50000,
    "account_type": "cash",
    "risk_profile": "balanced",
}


def _hammer(n: int, work: Callable[[int], None]) -> list[BaseException]:
    """Run ``work(i)`` on ``n`` threads released together; return what they raised."""
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def run(i: int) -> None:
        barrier.wait()
        try:
            work(i)
        except BaseException as exc:  # every failure counts, not only Exception
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return errors


# ------------------------------------------------------------------------------------ stores
@pytest.mark.slow
def test_trend_store_survives_sixteen_threads(tmp_path: Path) -> None:
    store = TrendStore(tmp_path / "trends.sqlite")
    signals: list[Any] = []
    base = datetime(2026, 11, 1, tzinfo=UTC)

    def work(i: int) -> None:
        for j in range(40):
            store.save(SimpleNamespace(signals=signals, as_of=base + timedelta(minutes=i * 40 + j)))
            assert store.latest(10**6, now=base + timedelta(days=1)) == []
            store.purge(24 * 365, now=base)

    assert _hammer(16, work) == []


@pytest.mark.slow
def test_bottleneck_store_survives_sixteen_threads(tmp_path: Path) -> None:
    store = BottleneckStore(tmp_path / "bottlenecks.sqlite")
    base = datetime(2026, 11, 1, tzinfo=UTC)

    def work(i: int) -> None:
        for j in range(40):
            run = SimpleNamespace(
                signals=[],
                as_of=base + timedelta(hours=i * 40 + j),
                layer_components={"ai/power": {"lead_time": float(j)}},
            )
            store.save(run)  # type: ignore[arg-type]
            assert store.latest(10**6, now=base + timedelta(days=90)) == []
            store.layer_history("ai/power")
            store.count()

    assert _hammer(16, work) == []
    assert store.count() == 16 * 40


@pytest.mark.slow
def test_knowledge_store_is_usable_from_other_threads(tmp_path: Path) -> None:
    docs = [
        Document(
            id=f"d{i}",
            title=f"Doc {i}",
            source="test",
            url="https://example.org",
            kind="concepts",
            as_of=date(2026, 11, 3),
            body=f"# Doc {i}\n\nA cash-secured put number {i} sets aside the strike in cash.",
        )
        for i in range(20)
    ]
    chunks = chunk_documents(docs)
    embedder = HashEmbedder(256)
    store = KnowledgeStore(tmp_path / "index.sqlite")  # opened on this thread
    store.rebuild(chunks, embedder)
    query = embedder.embed(["cash-secured put"])[0]

    def work(i: int) -> None:
        for _ in range(20):
            assert len(store) == len(chunks)
            assert store.dense_scores(query).shape == (len(chunks),)
            assert store.get(chunks[i % len(chunks)].id) is not None
            if i == 0:
                store.rebuild(chunks, embedder)  # a writer while the others read

    assert _hammer(12, work) == []


@pytest.mark.slow
def test_lazy_knowledge_retriever_is_built_once(
    monkeypatch: pytest.MonkeyPatch, config: AppConfig
) -> None:
    from options_scout.agent import deps as deps_mod

    built: list[object] = []

    def slow_build(_cfg: AppConfig) -> object:
        time.sleep(0.05)  # wide enough for every thread to arrive during the load
        built.append(object())
        return built[-1]

    monkeypatch.setattr(deps_mod.KnowledgeRetriever, "from_config", staticmethod(slow_build))
    d = deps_mod.Deps(cfg=config, md=None, llm=None, scout=None, trend_store=None)  # type: ignore[arg-type]
    seen: list[object] = []
    assert _hammer(8, lambda _i: seen.append(d.knowledge())) == []
    assert len(built) == 1 and all(s is built[0] for s in seen)


# --------------------------------------------------------------------------------------- API
@pytest.fixture
def api_env(tmp_path: Path) -> Iterator[tuple[Any, TestClient]]:
    """A fresh registry per test, every store under ``tmp_path`` (never ``data/``)."""
    import options_scout.api.main as api
    from options_scout.config import get_config

    mp = pytest.MonkeyPatch()
    mp.setenv("OPTIONS_SCOUT_API_KEY", KEY)
    mp.setenv("OPTIONS_SCOUT_CHECKPOINT_DB", str(tmp_path / "checkpoints.sqlite"))
    get_config.cache_clear()
    saved_registry, saved_limit = api._registry, api._RATE_LIMIT_PER_MIN
    api._RATE_LIMIT_PER_MIN = 10_000
    api._registry = None
    _isolate(api.registry(), tmp_path)
    c = TestClient(api.app, headers={"X-API-Key": KEY})
    yield api, c
    if api._registry is not None:
        api._registry.executor.shutdown(wait=True, cancel_futures=True)
    api._registry, api._RATE_LIMIT_PER_MIN = saved_registry, saved_limit
    mp.undo()
    get_config.cache_clear()


def _isolate(reg: Any, tmp_path: Path) -> None:
    reg.deps.trend_store = TrendStore(tmp_path / "trends.sqlite")
    reg.deps.bottleneck_store = BottleneckStore(tmp_path / "bottlenecks.sqlite")


def _restart(api: Any, tmp_path: Path) -> Any:
    """A new registry on the same checkpoint file: what a process restart leaves behind."""
    api._registry.executor.shutdown(wait=True)
    api._registry = api.RunRegistry()
    _isolate(api._registry, tmp_path)
    return api._registry


def _start(resp: Any) -> tuple[str, dict[str, str]]:
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["thread_id"], {TOKEN: body["thread_token"]}


def _wait(c: TestClient, tid: str, want: set[str], h: dict[str, str]) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < 60:
        r = c.get(f"/v1/runs/{tid}", headers=h)
        assert r.status_code == 200, r.text
        if r.json()["status"] in want:
            return r.json()  # type: ignore[no-any-return]
        time.sleep(0.1)
    raise AssertionError("timeout waiting for run")


def _caller_graphs(api: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[list[Any], list[Any]]:
    """Stand-ins for caller-keyed graphs (fixture data, so no network), and a record of the
    graph every resume ran on."""
    from options_scout.agent.graph import build_graph
    from options_scout.data.market import MarketData

    reg = api.registry()
    made: list[Any] = []
    resumed_on: list[Any] = []
    real_graph_for = reg.graph_for
    real_stream_resume = api.stream_resume

    def graph_for(auth: Any) -> Any:
        if auth is None:
            return real_graph_for(None)
        g = build_graph(reg.deps.with_market(MarketData.from_config(reg.cfg)), reg.ckpt)
        made.append(g)
        return g

    def stream_resume(graph: Any, thread_id: str, answer: dict[str, Any]) -> Any:
        resumed_on.append(graph)
        return real_stream_resume(graph, thread_id, answer)

    monkeypatch.setattr(reg, "graph_for", graph_for)
    monkeypatch.setattr(api, "stream_resume", stream_resume)
    return made, resumed_on


def test_resume_runs_on_the_source_the_run_started_with(
    api_env: tuple[Any, TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, c = api_env
    made, resumed_on = _caller_graphs(api, monkeypatch)
    tid, h = _start(
        c.post(
            "/v1/screen",
            json={"request_text": "help me find income ideas", "market_data": CALLER_KEY},
        )
    )
    assert _wait(c, tid, {"interrupted", "completed", "failed"}, h)["status"] == "interrupted"
    r = c.post(f"/v1/runs/{tid}/resume", json={"answer": ANSWER}, headers=h)
    assert r.status_code == 200, r.text
    assert _wait(c, tid, {"completed", "failed"}, h)["status"] == "completed"
    assert resumed_on == [made[0]] and made[0] is not api.registry().graph
    assert tid not in api.registry().graphs  # dropped once no resume can follow


def test_resume_without_the_callers_key_fails_clearly_never_falls_back(
    api_env: tuple[Any, TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, c = api_env
    made, resumed_on = _caller_graphs(api, monkeypatch)
    tid, h = _start(
        c.post(
            "/v1/screen",
            json={"request_text": "help me find income ideas", "market_data": CALLER_KEY},
        )
    )
    _wait(c, tid, {"interrupted"}, h)
    api.registry().graphs.clear()  # the key is gone, as after a restart

    r = c.post(f"/v1/runs/{tid}/resume", json={"answer": ANSWER}, headers=h)
    assert r.status_code == 409 and "same market_data" in r.json()["detail"]
    assert "caller-key-not-real" not in r.text
    other = {"provider": "tradier", "api_key": "x", "sandbox": True}
    r = c.post(f"/v1/runs/{tid}/resume", json={"answer": ANSWER, "market_data": other}, headers=h)
    assert r.status_code == 422 and "caller:marketdata" in r.json()["detail"]
    assert resumed_on == []  # nothing ran on the server's own source

    r = c.post(
        f"/v1/runs/{tid}/resume", json={"answer": ANSWER, "market_data": CALLER_KEY}, headers=h
    )
    assert r.status_code == 200, r.text
    assert _wait(c, tid, {"completed", "failed"}, h)["status"] == "completed"
    assert resumed_on == [made[-1]] and len(made) == 2


def test_server_source_run_refuses_a_caller_key_on_resume(
    api_env: tuple[Any, TestClient],
) -> None:
    _api, c = api_env
    tid, h = _start(c.post("/v1/screen", json={"request_text": "help me find income ideas"}))
    _wait(c, tid, {"interrupted"}, h)
    r = c.post(
        f"/v1/runs/{tid}/resume", json={"answer": ANSWER, "market_data": CALLER_KEY}, headers=h
    )
    assert r.status_code == 422 and "server's market data" in r.json()["detail"]


def test_status_report_and_resume_survive_a_restart(
    api_env: tuple[Any, TestClient], tmp_path: Path
) -> None:
    api, c = api_env
    done, hd = _start(c.post("/v1/screen", json={"request_text": "$50k cash, balanced. CSPs."}))
    paused, hp = _start(c.post("/v1/screen", json={"request_text": "help me find income ideas"}))
    _wait(c, done, {"completed"}, hd)
    _wait(c, paused, {"interrupted"}, hp)

    reg = _restart(api, tmp_path)
    assert reg.status == {} and reg.events == {}  # nothing carried over in memory
    assert c.get(f"/v1/runs/{done}", headers=hd).json()["status"] == "completed"
    assert c.get(f"/v1/runs/{done}/report", headers=hd).status_code == 200
    stream = c.get(f"/v1/runs/{done}/stream", headers=hd)
    assert stream.status_code == 200 and "event: end" in stream.text
    body = c.get(f"/v1/runs/{paused}", headers=hp).json()
    assert body["status"] == "interrupted" and body["interrupt"] is not None
    r = c.post(f"/v1/runs/{paused}/resume", json={"answer": ANSWER}, headers=hp)
    assert r.status_code == 200, r.text
    assert _wait(c, paused, {"completed", "failed"}, hp)["status"] == "completed"
    assert c.get("/v1/runs/no-such-thread", headers=hd).status_code == 404


def _block(reg: Any, thread_id: str, gate: threading.Event) -> None:
    with reg._lock:
        reg.events.setdefault(thread_id, [])
        reg._submit(thread_id, lambda: (gate.wait(30), None)[1])


def test_a_busy_thread_refuses_a_second_turn_and_a_resume(
    api_env: tuple[Any, TestClient],
) -> None:
    api, c = api_env
    reg = api.registry()
    tid = "busy-thread"
    h = {TOKEN: reg.tokens.issue(tid)}
    gate = threading.Event()
    _block(reg, tid, gate)
    try:
        r = c.post("/v1/chat", json={"thread_id": tid, "message": "hello"}, headers=h)
        assert r.status_code == 409
        assert c.get(f"/v1/runs/{tid}", headers=h).json()["status"] == "running"
        r = c.post(f"/v1/runs/{tid}/resume", json={"answer": ANSWER}, headers=h)
        assert r.status_code == 409
    finally:
        gate.set()


def test_simultaneous_turns_on_one_thread_start_exactly_one(
    api_env: tuple[Any, TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, _c = api_env
    reg = api.registry()
    gate = threading.Event()
    calls: list[str] = []

    def send(thread_id: str, message: str, **_kw: Any) -> Any:
        calls.append(thread_id)
        gate.wait(30)
        raise RuntimeError("stopped by the test")

    monkeypatch.setattr(reg.session, "send", send)
    outcomes: list[int] = []

    def go(_i: int) -> None:
        try:
            reg.chat("one-thread", "hello")
            outcomes.append(200)
        except HTTPException as exc:
            outcomes.append(exc.status_code)

    try:
        assert _hammer(4, go) == []
        assert sorted(outcomes) == [200, 409, 409, 409]
    finally:
        gate.set()
    reg.futures["one-thread"].result(30)
    assert calls == ["one-thread"]


def test_a_full_pool_answers_429_and_frees_up(api_env: tuple[Any, TestClient]) -> None:
    api, c = api_env
    reg = api.registry()
    gate = threading.Event()
    try:
        for i in range(reg.max_workers + reg.max_queued):
            _block(reg, f"filler-{i}", gate)
        r = c.post("/v1/screen", json={"request_text": "$50k cash, balanced. CSPs."})
        assert r.status_code == 429 and r.headers.get("Retry-After")
        assert reg.in_flight() == reg.max_workers + reg.max_queued
        assert len(reg.events) == reg.max_workers + reg.max_queued  # the refused run left nothing
    finally:
        gate.set()
    for f in list(reg.futures.values()):
        f.result(30)
    tid, h = _start(c.post("/v1/screen", json={"request_text": "$50k cash, balanced. CSPs."}))
    assert _wait(c, tid, {"completed", "failed"}, h)["status"] == "completed"


def test_finished_runs_are_evicted_from_memory(
    api_env: tuple[Any, TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, c = api_env
    reg = api.registry()
    tid, h = _start(c.post("/v1/screen", json={"request_text": "$50k cash, balanced. CSPs."}))
    _wait(c, tid, {"completed"}, h)
    reg.finished_at[tid] -= 10_000  # long ago
    with reg._lock:
        reg._evict()
    assert tid not in reg.events and tid not in reg.futures and tid not in reg.finished_at
    assert c.get(f"/v1/runs/{tid}", headers=h).json()["status"] == "completed"  # checkpointer


# ------------------------------------------------------- the compose services share one volume
_WRITER = """
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from options_scout.bottleneck.engine import BottleneckStore
from options_scout.data.cache import SQLiteCache
from options_scout.jobs.snapshot_iv import IVSnapshotStore
from options_scout.social.pipeline import TrendStore

root, worker = Path(sys.argv[1]), int(sys.argv[2])
trends = TrendStore(root / "trends.sqlite")
board = BottleneckStore(root / "bottleneck_snapshots.sqlite")
iv = IVSnapshotStore(root / "iv_snapshots.sqlite")
cache = SQLiteCache(root / "cache.sqlite")
base = datetime(2026, 11, 1, tzinfo=UTC)
for j in range(60):
    at = base + timedelta(minutes=worker * 60 + j)
    trends.save(SimpleNamespace(signals=[], as_of=at))
    trends.latest(10**6, now=at)
    board.save(SimpleNamespace(signals=[], as_of=at, layer_components={"ai/power": {"x": 1.0}}))
    board.layer_history("ai/power")
    iv.record(f"T{worker}", date(2026, 1, 1) + timedelta(days=j), 0.3)
    iv.history(f"T{worker}")
    cache.set(f"k{worker}-{j}", {"v": j}, 3600)
    cache.get(f"k{worker}-{j}")
"""


@pytest.mark.slow
def test_four_processes_share_the_volume_stores(tmp_path: Path) -> None:
    """The api, ui and scheduler containers open the same SQLite files on scout-data."""
    import subprocess
    import sys

    script = tmp_path / "writer.py"
    script.write_text(_WRITER)
    procs = [
        subprocess.Popen(
            [sys.executable, str(script), str(tmp_path), str(i)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(4)
    ]
    results = [p.communicate(timeout=120) for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0, 0], [err for _out, err in results]
    assert BottleneckStore(tmp_path / "bottleneck_snapshots.sqlite").count() == 4 * 60


_HOLDER = """
import sqlite3, sys, time
conns = [sqlite3.connect(path, isolation_level=None) for path in sys.argv[2:]]
for conn in conns:
    conn.execute("BEGIN IMMEDIATE")  # another service mid-write: holds each file's write lock
print("locked", flush=True)
time.sleep(float(sys.argv[1]))
for conn in conns:
    conn.execute("COMMIT")
"""


@pytest.mark.slow
def test_writes_wait_out_another_services_long_write(tmp_path: Path) -> None:
    """SQLite's default wait is 5 s; a scheduler write longer than that made the API fail with
    "database is locked". Every shared store now waits up to 30 s (W39). One holder locks all
    four files for 6 s and the four writes run in parallel, so the test costs about 6 s."""
    import subprocess
    import sys

    from options_scout.data.cache import SQLiteCache
    from options_scout.jobs.snapshot_iv import IVSnapshotStore

    at = datetime(2026, 11, 1, tzinfo=UTC)
    trend = TrendStore(tmp_path / "trends.sqlite")
    board = BottleneckStore(tmp_path / "bottlenecks.sqlite")
    iv = IVSnapshotStore(tmp_path / "iv.sqlite")
    cache = SQLiteCache(tmp_path / "cache.sqlite")
    writes: list[Callable[[], None]] = [
        lambda: trend.save(SimpleNamespace(signals=[], as_of=at)),  # type: ignore[arg-type]
        lambda: board.save(SimpleNamespace(signals=[], as_of=at, layer_components={})),  # type: ignore[arg-type]
        lambda: iv.record("AAPL", date(2026, 11, 1), 0.3),
        lambda: cache.set("k", {"v": 1}, 3600),
    ]
    paths = sorted(tmp_path.glob("*.sqlite"))
    script = tmp_path / "holder.py"
    script.write_text(_HOLDER)
    holder = subprocess.Popen(
        [sys.executable, str(script), "6", *map(str, paths)], stdout=subprocess.PIPE, text=True
    )
    waited: list[float] = []

    def timed(i: int) -> None:
        t0 = time.monotonic()
        writes[i]()  # must wait for the holder (about 6 s), not fail at 5 s
        waited.append(time.monotonic() - t0)

    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "locked"
        assert _hammer(len(writes), timed) == []
    finally:
        holder.wait(30)
    assert holder.returncode == 0
    assert len(waited) == 4 and min(waited) > 5


def test_a_run_lost_to_a_killed_process_reports_failed(api_env: tuple[Any, TestClient]) -> None:
    """Runs checkpoint on exit (W19). A thread with a token but no saved state, and nothing
    running, is a run whose process died: failed, not an unknown thread."""
    api, c = api_env
    reg = api.registry()
    h = {TOKEN: reg.tokens.issue("killed-mid-run")}
    assert reg.run_state("killed-mid-run") == "failed"
    assert c.get("/v1/runs/killed-mid-run", headers=h).json()["status"] == "failed"
    assert c.get("/v1/runs/killed-mid-run/report", headers=h).status_code == 409
    assert reg.run_state("never-issued") == "unknown"
