"""W38 step 1: one live-mode screen with canary keys and every upstream failing. No canary may
appear in the captured logs, the run state (which the API serves), the report, the chat turn or
any file the run wrote (checkpoint database and its write-ahead log, caches)."""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.conftest import REPO_ROOT

CANARIES = {
    name: f"CANARY{name}Zq9"
    for name in (
        "FRED_API_KEY",
        "ALPHAVANTAGE_API_KEY",
        "MARKETDATA_TOKEN",
        "TRADIER_API_KEY",
        "REDDIT_CLIENT_SECRET",
        "X_BEARER_TOKEN",
    )
}


def _dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump(mode="json"), default=str)
    if isinstance(value, dict):
        return json.dumps({k: _dump(v) for k, v in value.items()}, default=str)
    if isinstance(value, list | tuple):
        return json.dumps([_dump(v) for v in value], default=str)
    return json.dumps(value, default=str)


def test_no_canary_key_leaves_a_live_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import options_scout.observability as obs

    for name, value in CANARIES.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("OPTIONS_SCOUT_DATA_MODE", "live")
    monkeypatch.setenv("OPTIONS_SCOUT_LLM_MODE", "fixture")
    monkeypatch.setenv("OPTIONS_SCOUT_CHECKPOINT_DB", str(tmp_path / "ck.sqlite"))

    def no_network(*_a: Any, **_k: Any) -> None:
        raise OSError("network disabled in the canary test")

    def refuse(_self: Any, request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request, json={"error": "invalid api key"})

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    # the redaction-by-value backstop must not be what saves the run: only the patterns and the
    # adapters' own error messages may. Turn it off for this test.
    monkeypatch.setattr(obs, "_secret_env_values", lambda: [], raising=False)

    from options_scout.agent.chat import ChatSession
    from options_scout.agent.deps import Deps
    from options_scout.agent.graph import sqlite_checkpointer
    from options_scout.config import load_config

    cfg = load_config(REPO_ROOT)
    cfg = cfg.model_copy(
        update={
            "settings": cfg.settings.model_copy(
                update={
                    "paths": cfg.settings.paths.model_copy(
                        update={
                            "cache_db": tmp_path / "cache.sqlite",
                            "iv_snapshot_db": tmp_path / "iv.sqlite",
                            "llm_cache_dir": tmp_path / "llm",
                        }
                    )
                }
            )
        }
    )
    deps = Deps.from_config(cfg)
    from options_scout.social.pipeline import TrendStore

    deps.trend_store = TrendStore(tmp_path / "trends.sqlite")
    session = ChatSession(deps, sqlite_checkpointer(tmp_path / "ck.sqlite", 7))
    caplog.set_level(logging.DEBUG)
    result = session.send(
        "canary", "I have $100,000 in a cash account, balanced. Show me cash-secured puts."
    )
    values = session.graph.get_state({"configurable": {"thread_id": "canary"}}).values
    assert values.get("errors"), "the failing upstreams should have been recorded"

    places = {
        "logs": caplog.text,
        "state (API responses read it)": _dump(dict(values)),
        "report markdown": str(values.get("report_markdown") or ""),
        "chat turn": _dump(result.turn),
    }
    for f in tmp_path.rglob("*"):
        if f.is_file():
            places[f"file {f.name}"] = f.read_bytes().decode("latin-1")
    leaks = {
        f"{name} in {where}"
        for name, value in CANARIES.items()
        for where, text in places.items()
        if value in text
    }
    assert not leaks, sorted(leaks)
