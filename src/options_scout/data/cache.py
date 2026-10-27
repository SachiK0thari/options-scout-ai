"""Tiny SQLite TTL cache for JSON-serialisable payloads (market data, resolutions, posts)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class SQLiteCache:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "expires_at REAL NOT NULL, created_at REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at < now:
            self.delete(key)
            return None
        return json.loads(value)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        now = time.time()
        payload = json.dumps(value, default=str, sort_keys=True)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at, created_at) "
                "VALUES (?, ?, ?, ?)",
                (key, payload, now + ttl_seconds, now),
            )
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._conn.commit()

    def purge_expired(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
            self._conn.commit()
            return int(cur.rowcount)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class MemoryCache:
    """Same interface, process-local. Used in tests and fixture mode."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at < time.time():
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._data[key] = (json.loads(json.dumps(value, default=str)), time.time() + ttl_seconds)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def purge_expired(self) -> int:
        now = time.time()
        dead = [k for k, (_, exp) in self._data.items() if exp < now]
        for k in dead:
            del self._data[k]
        return len(dead)

    def close(self) -> None:
        self._data.clear()
