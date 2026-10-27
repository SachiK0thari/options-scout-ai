"""API smoke tests through FastAPI's TestClient (fixture mode, no network)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    import options_scout.api.main as api

    api._registry = None
    c = TestClient(api.app)
    reg = api.registry()
    from options_scout.social.pipeline import TrendStore

    reg.deps.trend_store = TrendStore(tmp_path_factory.mktemp("api") / "t.sqlite")
    return c


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
