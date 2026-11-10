from __future__ import annotations

import time
from pathlib import Path

from options_scout.data.cache import MemoryCache, SQLiteCache


def test_sqlite_cache_roundtrip_and_ttl(tmp_path: Path) -> None:
    c = SQLiteCache(tmp_path / "c.sqlite")
    c.set("k", {"a": 1, "b": [1, 2]}, ttl_seconds=60)
    assert c.get("k") == {"a": 1, "b": [1, 2]}
    c.set("old", 1, ttl_seconds=-1)
    assert c.get("old") is None
    c.set("old2", 1, ttl_seconds=-1)
    assert c.purge_expired() >= 1
    c.delete("k")
    assert c.get("k") is None
    c.close()


def test_memory_cache_expires() -> None:
    c = MemoryCache()
    c.set("k", [1], ttl_seconds=0)
    time.sleep(0.01)
    assert c.get("k") is None


def test_expired_rows_are_purged_when_the_cache_opens(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "c.sqlite"
    c = SQLiteCache(path)
    c.set("old", {"x": 1}, ttl_seconds=-1)
    c.set("fresh", {"x": 2}, ttl_seconds=600)
    SQLiteCache(path)  # reopening deletes what has expired
    keys = [k for (k,) in sqlite3.connect(path).execute("SELECT key FROM cache")]
    assert keys == ["fresh"]
