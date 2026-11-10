"""W37: thread ownership, the API key required by default, and a limiter that counts failures.

Every thread route answers 404 (never 403) to a caller without the thread's token, so a guessed
id reveals nothing. Fixture mode, no network.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

KEY = "w37-test-key"
TOKEN = "X-Thread-Token"


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    import options_scout.api.main as api_mod
    from options_scout.bottleneck.engine import BottleneckStore
    from options_scout.social.pipeline import TrendStore

    mp = pytest.MonkeyPatch()
    mp.setenv("OPTIONS_SCOUT_API_KEY", KEY)
    mp.setattr(api_mod, "_RATE_LIMIT_PER_MIN", 10_000)
    api_mod._registry = None
    api_mod._hits.clear()
    reg = api_mod.registry()
    reg.deps.trend_store = TrendStore(tmp_path_factory.mktemp("w37") / "t.sqlite")
    reg.deps.bottleneck_store = BottleneckStore(tmp_path_factory.mktemp("w37-bn") / "b.sqlite")
    yield api_mod
    api_mod._registry = None
    api_mod._hits.clear()
    mp.undo()


def _client(api: Any) -> TestClient:
    return TestClient(api.app, headers={"X-API-Key": KEY})


def _wait(c: TestClient, tid: str, token: str) -> dict[str, Any]:
    for _ in range(600):
        r = c.get(f"/v1/runs/{tid}", headers={TOKEN: token})
        assert r.status_code == 200, r.text
        if r.json()["status"] in ("completed", "interrupted", "withheld", "failed"):
            return dict(r.json())
        time.sleep(0.1)
    raise AssertionError("timeout")


def _events(resp: Any) -> list[dict[str, Any]]:
    return [json.loads(ln[6:]) for ln in resp.text.splitlines() if ln.startswith("data: ")]


def test_another_caller_cannot_read_continue_or_resume_a_thread(api: Any) -> None:
    owner, stranger = _client(api), _client(api)
    r = owner.post("/v1/screen", json={"request_text": "help me find income ideas"})
    assert r.status_code == 200
    tid, token = r.json()["thread_id"], r.json()["thread_token"]
    assert len(token) >= 40 and tid not in token
    assert _wait(owner, tid, token)["status"] == "interrupted"
    for headers in ({}, {TOKEN: "x" * 43}):
        assert stranger.get(f"/v1/runs/{tid}", headers=headers).status_code == 404
        assert stranger.get(f"/v1/runs/{tid}/report", headers=headers).status_code == 404
        assert stranger.get(f"/v1/runs/{tid}/stream", headers=headers).status_code == 404
        assert stranger.get(f"/v1/threads/{tid}", headers=headers).status_code == 404
        resume = stranger.post(
            f"/v1/runs/{tid}/resume", json={"answer": {"buying_power": 1}}, headers=headers
        )
        assert resume.status_code == 404
        chat = stranger.post(
            "/v1/chat", json={"message": "what if I had 90000?", "thread_id": tid}, headers=headers
        )
        assert chat.status_code == 404
    # the same answers as for a thread that does not exist: existence is not revealed
    assert stranger.get("/v1/runs/doesnotexist", headers={TOKEN: token}).status_code == 404
    # the owner still can
    assert owner.get(f"/v1/threads/{tid}", headers={TOKEN: token}).status_code == 200


def test_thread_ids_are_generated_never_chosen(api: Any) -> None:
    c = _client(api)
    r = c.post("/v1/screen", json={"request_text": "$50k cash, conservative", "thread_id": "mine"})
    assert r.status_code == 422
    chat = c.post("/v1/chat", json={"message": "What is a put?", "thread_id": "brand-new"})
    assert chat.status_code == 404  # continuing needs an existing thread and its token


def test_a_chat_thread_and_its_handoff_belong_to_the_creator(api: Any) -> None:
    c = _client(api)
    r = c.post("/v1/chat", json={"message": "$50k cash account, conservative, CSPs only."})
    assert r.status_code == 200
    evs = _events(r)
    first = evs[0]
    assert first["event"] == "thread" and first["thread_token"]
    tid, token = first["thread_id"], first["thread_token"]
    assert r.headers[TOKEN] == token
    assert all("thread_token" not in e for e in evs[1:])  # sent once, never echoed again
    r2 = c.post(
        "/v1/chat",
        json={"message": "What if I only had 30k?", "thread_id": tid},
        headers={TOKEN: token},
    )
    assert r2.status_code == 200
    handoff = next(e for e in _events(r2) if e["event"] == "handoff")
    child = handoff["new_thread_id"]
    for _ in range(100):
        if api.registry().status.get(child) not in (None, "running"):
            break
        time.sleep(0.1)
    assert c.get(f"/v1/threads/{child}", headers={TOKEN: token}).status_code == 200
    assert c.get(f"/v1/threads/{child}").status_code == 404


def test_ui_threads_are_not_reachable_through_the_api(api: Any) -> None:
    """A thread the Streamlit app wrote has no token and lives in another checkpoint file."""
    reg = api.registry()
    assert reg.checkpoint_path != reg.cfg.paths.checkpoint_db
    from ui.session import new_thread_id

    tid = new_thread_id()
    assert tid.startswith("ui") and len(tid) == 34 and "-" not in tid  # uuid4 hex, unguessable
    assert _client(api).get(f"/v1/threads/{tid}").status_code == 404


def test_the_key_is_required_unless_anonymous_is_explicit(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = TestClient(api.app)
    assert bare.get("/v1/trends").status_code == 401
    assert bare.get("/v1/quality-universe").status_code == 401
    assert TestClient(api.app, headers={"X-API-Key": "wrong"}).get("/v1/trends").status_code == 401
    assert bare.get("/docs").status_code == 404 and bare.get("/openapi.json").status_code == 404
    health = bare.get("/healthz").json()
    assert health["status"] == "ok" and "sources" not in health and "data_mode" not in health
    assert "sources" in _client(api).get("/healthz").json()
    # no key configured: refuse, and refuse to start, unless anonymous is set explicitly
    monkeypatch.delenv("OPTIONS_SCOUT_API_KEY")
    monkeypatch.delenv("OPTIONS_SCOUT_ALLOW_ANONYMOUS", raising=False)
    assert bare.get("/v1/trends").status_code == 503
    with pytest.raises(RuntimeError, match="OPTIONS_SCOUT_API_KEY"):
        api.check_deployment()
    monkeypatch.setenv("OPTIONS_SCOUT_ALLOW_ANONYMOUS", "1")
    api.check_deployment()
    assert bare.get("/v1/trends").status_code == 200


def test_wrong_keys_are_rate_limited_with_retry_after(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "_RATE_LIMIT_PER_MIN", 3)
    monkeypatch.setattr(api, "_hits", defaultdict(deque))
    guesser = TestClient(api.app, headers={"X-API-Key": "guess"})
    codes = [guesser.get("/v1/trends").status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
    r = guesser.get("/v1/trends")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_idle_limiter_buckets_are_evicted(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    hits: defaultdict[str, deque[float]] = defaultdict(deque)
    hits["198.51.100.7"].append(time.time() - 3600)
    monkeypatch.setattr(api, "_hits", hits)
    monkeypatch.setattr(api, "_last_sweep", 0.0)
    _client(api).get("/v1/trends")
    assert "198.51.100.7" not in api._hits


def test_forwarded_for_is_used_only_behind_a_trusted_proxy(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.requests import Request

    def req(xff: str) -> Request:
        scope = {
            "type": "http",
            "headers": [(b"x-forwarded-for", xff.encode())],
            "client": ("10.0.0.2", 1234),
        }
        return Request(scope)

    monkeypatch.delenv("OPTIONS_SCOUT_TRUSTED_PROXY", raising=False)
    assert api.client_ip(req("203.0.113.9")) == "10.0.0.2"  # spoofable header ignored
    monkeypatch.setenv("OPTIONS_SCOUT_TRUSTED_PROXY", "1")
    assert api.client_ip(req("1.2.3.4, 203.0.113.9")) == "203.0.113.9"  # what the proxy saw


def test_compose_binds_the_ui_to_localhost_and_sets_no_anonymous_mode() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text()
    assert '"127.0.0.1:8501:8501"' in compose
    assert "OPTIONS_SCOUT_ALLOW_ANONYMOUS" not in compose
