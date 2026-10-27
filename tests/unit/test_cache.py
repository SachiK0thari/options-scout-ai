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
