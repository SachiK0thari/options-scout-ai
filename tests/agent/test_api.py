"""API smoke tests through FastAPI's TestClient (fixture mode, no network)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    import options_scout.api.main as api

    api._registry = None
    # The per-IP limiter (30 req/min) is a module-level counter and every test here
    # shares one TestClient host, so polling in `_wait` would exhaust the budget on a
    # slow runner. Lift it for the smoke tests; the limiter has its own test below.
    saved_limit = api._RATE_LIMIT_PER_MIN
    api._RATE_LIMIT_PER_MIN = 10_000
    api._hits.clear()
    c = TestClient(api.app)
    reg = api.registry()
    from options_scout.social.pipeline import TrendStore

    reg.deps.trend_store = TrendStore(tmp_path_factory.mktemp("api") / "t.sqlite")
    yield c
    api._RATE_LIMIT_PER_MIN = saved_limit
    api._hits.clear()


def _wait(
    client: TestClient, thread_id: str, want: set[str], timeout: float = 60
) -> dict[str, object]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/v1/runs/{thread_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in want:
            return body  # type: ignore[no-any-return]
        time.sleep(0.2)
    raise AssertionError("timeout waiting for run")


def test_health(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["data_mode"] == "fixture" and "market_data" in r.json()["sources"]


def test_screen_report_and_markdown(client: TestClient) -> None:
    r = client.post(
        "/v1/screen",
        json={"request_text": "$100k margin account, balanced. CSPs and LEAPS. I like COST."},
    )
    assert r.status_code == 200
    tid = r.json()["thread_id"]
    body = _wait(client, tid, {"completed", "failed"})
    assert body["status"] == "completed", body["errors"]
    assert "report_node" in body["nodes_visited"]
    rep = client.get(f"/v1/runs/{tid}/report").json()
    assert rep["verification"]["passed"] and rep["disclaimer"]
    md = client.get(f"/v1/runs/{tid}/report?format=md")
    assert md.status_code == 200 and "## Explanation" in md.text
    stream = client.get(f"/v1/runs/{tid}/stream")
    assert stream.status_code == 200 and "event: end" in stream.text


def test_interrupt_and_resume_via_api(client: TestClient) -> None:
    r = client.post("/v1/screen", json={"request_text": "help me find income ideas"})
    tid = r.json()["thread_id"]
    body = _wait(client, tid, {"interrupted", "completed", "failed"})
    assert body["status"] == "interrupted" and body["interrupt"] is not None
    assert "buying_power" in body["interrupt"]["needs_clarification"]
    bad = client.get(f"/v1/runs/{tid}/report")
    assert bad.status_code == 409
    r2 = client.post(
        f"/v1/runs/{tid}/resume",
        json={
            "answer": {
                "buying_power": 50000,
                "account_value": 50000,
                "account_type": "cash",
                "risk_profile": "balanced",
            }
        },
    )
    assert r2.status_code == 200
    body = _wait(client, tid, {"completed", "failed"})
    assert body["status"] == "completed"
    assert client.get(f"/v1/runs/{tid}/report").json()["profile"]["buying_power"] == 50000


def test_validation_and_auth(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.post("/v1/screen", json={}).status_code == 422
    assert client.get("/v1/runs/nope").status_code == 404
    monkeypatch.setenv("OPTIONS_SCOUT_API_KEY", "secret")
    assert client.get("/v1/trends").status_code == 401
    assert client.get("/v1/trends", headers={"X-API-Key": "secret"}).status_code == 200


def test_recommend_front_door(client: TestClient) -> None:
    r = client.post("/v1/recommend", json={"buying_power": 40000, "strategy": "csp"})
    assert r.status_code == 200, r.text
    tid = r.json()["thread_id"]
    body = _wait(client, tid, {"completed", "failed"})
    assert body["status"] == "completed", body["errors"]
    rep = client.get(f"/v1/runs/{tid}/report").json()
    assert rep["profile"] == {
        **rep["profile"],
        "buying_power": 40000,
        "account_type": "cash",
        "risk_profile": "conservative",
        "strategies": ["csp"],
    }
    assert rep["quality"] and all(q["passed"] for q in rep["quality"])
    assert rep["leaps_candidates"] == [] and rep["allocation"]["leaps_pct"] == 0.0
    assert client.post("/v1/recommend", json={"buying_power": -5}).status_code == 422
    assert (
        client.post("/v1/recommend", json={"buying_power": 1000, "strategy": "yolo"}).status_code
        == 422
    )


def test_quality_universe_endpoint(client: TestClient) -> None:
    r = client.get("/v1/quality-universe")
    assert r.status_code == 200
    body = r.json()
    assert body["gates"]["max_hv30"] == 0.35
    tickers = {t["ticker"] for t in body["tickers"]}
    assert {"AAPL", "MSFT", "COST", "SPY"} <= tickers and "TSLA" not in tickers


def test_tradier_without_key_is_rejected_before_running(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRADIER_API_KEY", raising=False)
    r = client.post(
        "/v1/recommend",
        json={"buying_power": 40000, "market_data": {"provider": "tradier"}},
    )
    assert r.status_code == 422 and "API key" in r.json()["detail"]


def test_rate_limit_returns_429(monkeypatch: pytest.MonkeyPatch) -> None:
    import options_scout.api.main as api

    monkeypatch.delenv("OPTIONS_SCOUT_API_KEY", raising=False)
    monkeypatch.setattr(api, "_RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(api, "_hits", defaultdict(deque))
    c = TestClient(api.app)
    assert c.get("/v1/trends").status_code == 200
    assert c.get("/v1/trends").status_code == 200
    r = c.get("/v1/trends")
    assert r.status_code == 429 and "rate limit" in r.json()["detail"]
    # Unauthenticated public endpoints are not metered.
    assert c.get("/v1/quality-universe").status_code == 200


def test_api_key_is_a_secret_in_the_schema() -> None:
    from options_scout.api.schemas import MarketDataAuth

    auth = MarketDataAuth(provider="tradier", api_key="super-secret")  # type: ignore[arg-type]
    assert "super-secret" not in repr(auth) and "super-secret" not in auth.model_dump_json()
    assert auth.api_key is not None and auth.api_key.get_secret_value() == "super-secret"
