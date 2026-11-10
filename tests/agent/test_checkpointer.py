"""W19: the SQLite checkpointer prunes idle threads on open and never touches the repo file."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import empty_checkpoint

from options_scout.agent.graph import prune_stale_threads, sqlite_checkpointer
from options_scout.core.models import utcnow

REPO_ROOT = Path(__file__).resolve().parents[2]


def _put(saver: Any, thread_id: str, *, days_ago: float) -> None:
    """Write one checkpoint for ``thread_id`` whose ``ts`` is ``days_ago`` days in the past."""
    checkpoint = empty_checkpoint()
    checkpoint["ts"] = (utcnow() - timedelta(days=days_ago)).isoformat()
    saver.put(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "input", "step": -1, "parents": {}},
        {},
    )


def _threads(saver: Any) -> set[str]:
    return {r[0] for r in saver.conn.execute("SELECT DISTINCT thread_id FROM checkpoints")}


def test_new_database_uses_incremental_auto_vacuum(tmp_path: Path) -> None:
    saver: Any = sqlite_checkpointer(tmp_path / "ckpt.sqlite", retention_days=7)
    assert saver.conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2  # 2 = INCREMENTAL
    assert saver.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_idle_threads_are_deleted_on_open(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.sqlite"
    saver: Any = sqlite_checkpointer(path)  # retention off: nothing pruned
    _put(saver, "idle", days_ago=8)
    _put(saver, "fresh", days_ago=6)
    _put(saver, "revived", days_ago=30)
    _put(saver, "revived", days_ago=1)  # the newest checkpoint decides, not the oldest
    assert _threads(saver) == {"idle", "fresh", "revived"}
    saver.conn.close()

    reopened: Any = sqlite_checkpointer(path, retention_days=7)
    assert _threads(reopened) == {"fresh", "revived"}
    assert reopened.get_tuple({"configurable": {"thread_id": "idle"}}) is None
    assert reopened.get_tuple({"configurable": {"thread_id": "fresh"}}) is not None


def test_retention_zero_keeps_every_thread(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.sqlite"
    saver: Any = sqlite_checkpointer(path)
    _put(saver, "ancient", days_ago=400)
    saver.conn.close()
    assert _threads(sqlite_checkpointer(path, retention_days=0)) == {"ancient"}


def test_prune_reports_what_it_deleted_and_keeps_unreadable_rows(tmp_path: Path) -> None:
    saver: Any = sqlite_checkpointer(tmp_path / "ckpt.sqlite")
    _put(saver, "idle", days_ago=10)
    _put(saver, "fresh", days_ago=0)
    saver.conn.execute(
        "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, type, checkpoint) "
        "VALUES ('garbage', '', '0', 'json', X'00')"
    )
    saver.conn.commit()
    assert prune_stale_threads(saver.conn, saver, 7) == ["idle"]
    assert _threads(saver) == {"fresh", "garbage"}
    assert prune_stale_threads(saver.conn, saver, 7) == []


def test_config_points_tests_at_a_temporary_database(config: Any) -> None:
    repo_db = REPO_ROOT / "data" / "checkpoints.sqlite"
    assert config.paths.checkpoint_db != repo_db
    assert "ckpt" in str(config.paths.checkpoint_db)
    assert config.settings.agent.checkpoint_retention_days == 7


# ------------------------------------------------------- step 4: fewer and smaller checkpoints
def _screen_deps(config: Any, tmp_path: Path) -> Any:
    from options_scout.agent.deps import Deps
    from options_scout.bottleneck.engine import BottleneckStore
    from options_scout.social.pipeline import TrendStore

    deps = Deps.from_config(config)
    deps.trend_store = TrendStore(tmp_path / "trends.sqlite")
    deps.bottleneck_store = BottleneckStore(tmp_path / "bottlenecks.sqlite")
    return deps


def _size(path: Path) -> int:
    """The database with its write-ahead log, which holds recent pages until a checkpoint."""
    return sum(p.stat().st_size for p in path.parent.glob(path.name + "*"))


def test_a_screen_writes_one_small_checkpoint(config: Any, tmp_path: Path) -> None:
    """Measured 2026-11-10: 50 checkpoints and 107 MB before; one checkpoint of 0.7 MB after."""
    from options_scout.agent.graph import build_graph, initial_state, stream_run, thread_config

    path = tmp_path / "ckpt.sqlite"
    saver: Any = sqlite_checkpointer(path)
    graph = build_graph(_screen_deps(config, tmp_path), saver)
    before = _size(path)
    for _ in stream_run(
        graph, initial_state("$100k margin account, balanced. CSPs and LEAPS."), "s"
    ):
        pass
    assert saver.conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 1
    assert saver.conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0] == 0
    assert _size(path) - before < 3_000_000
    values = graph.get_state(thread_config("s")).values
    assert values["report"] is not None and values["market_data"]
    # the chains are gone from the thread; the quote fields every later reader uses remain
    assert all(not s.chains and s.spot.price > 0 for s in values["market_data"].values())


def test_a_paused_run_is_saved_and_resumes_in_a_new_process(config: Any, tmp_path: Path) -> None:
    from options_scout.agent.graph import (
        build_graph,
        initial_state,
        pending_interrupt,
        stream_resume,
        stream_run,
        thread_config,
    )

    path = tmp_path / "ckpt.sqlite"
    deps = _screen_deps(config, tmp_path)
    first = build_graph(deps, sqlite_checkpointer(path))
    for _ in stream_run(first, initial_state("help me find income ideas"), "p"):
        pass
    assert pending_interrupt(first, "p") is not None
    second = build_graph(deps, sqlite_checkpointer(path))  # a restart
    answer = {"buying_power": 50000, "account_value": 50000, "account_type": "cash"}
    for _ in stream_resume(second, "p", {**answer, "risk_profile": "balanced"}):
        pass
    snap = second.get_state(thread_config("p"))
    assert snap.values["report"] is not None and not snap.next


def test_a_run_that_raises_is_saved_with_its_remaining_steps(
    config: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """Exit durability also saves on an error, so the API reports the run as failed."""
    import pytest

    from options_scout.agent.graph import build_graph, initial_state, stream_run, thread_config
    from options_scout.core import screeners

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("screener broke")

    monkeypatch.setattr(screeners, "screen_csp", boom)
    graph = build_graph(_screen_deps(config, tmp_path), sqlite_checkpointer(tmp_path / "c.sqlite"))
    with pytest.raises(RuntimeError, match="screener broke"):
        for _ in stream_run(graph, initial_state("$50k cash account, balanced. CSPs only."), "e"):
            pass
    snap = graph.get_state(thread_config("e"))
    assert snap.values and snap.next  # saved, and not finished
