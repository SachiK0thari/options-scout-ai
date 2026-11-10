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
