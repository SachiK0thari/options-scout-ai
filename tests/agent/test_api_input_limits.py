"""W40 at the API: bad tickers, oversized lists, non-finite amounts and oversized bodies are
rejected (422 / 413) before a run starts, and the 422 never echoes the rejected value. Fixture
mode, no network."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

KEY = "w40-test-key"
TOKEN = "X-Thread-Token"
PROFILE = {
    "buying_power": 50_000,
    "account_value": 50_000,
    "account_type": "cash",
    "risk_profile": "balanced",
}


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    import options_scout.api.main as api_mod
    from options_scout.bottleneck.engine import BottleneckStore
    from options_scout.social.pipeline import TrendStore

    mp = pytest.MonkeyPatch()
    mp.setenv("OPTIONS_SCOUT_API_KEY", KEY)
    mp.setattr(api_mod, "_RATE_LIMIT_PER_MIN", 10_000)
    api_mod._registry = None
    api_mod._hits.clear()
    reg = api_mod.registry()
    tmp: Path = tmp_path_factory.mktemp("w40")
    reg.deps.trend_store = TrendStore(tmp / "t.sqlite")
    reg.deps.bottleneck_store = BottleneckStore(tmp / "b.sqlite")
    yield TestClient(api_mod.app, headers={"X-API-Key": KEY})
    api_mod._registry = None
    api_mod._hits.clear()
    mp.undo()


def _rejected(r: Any, *fragments: str) -> None:
    assert r.status_code == 422, r.text
    for fragment in fragments:
        assert fragment not in r.text, f"the 422 echoed {fragment!r}"


@pytest.mark.parametrize("bad", ["AAPL/../../v1/user", "../../../secret", "<b>X</b>", "1ABC"])
def test_a_ticker_that_is_not_a_symbol_is_a_422(client: TestClient, bad: str) -> None:
    _rejected(client.post("/v1/screen", json={"profile": {**PROFILE, "watchlist": [bad]}}), bad)
    _rejected(client.post("/v1/screen", json={"profile": {**PROFILE, "exclude": [bad]}}), bad)
    _rejected(client.post("/v1/recommend", json={"buying_power": 5000, "watchlist": [bad]}), bad)
    _rejected(
        client.post(
            "/v1/screen",
            json={"request_text": "income", "holdings": [{"ticker": bad, "shares": 10}]},
        ),
        bad,
    )


def test_a_watchlist_over_twenty_is_a_422(client: TestClient) -> None:
    many = [f"T{i}" for i in range(2001)]
    r = client.post("/v1/screen", json={"profile": {**PROFILE, "watchlist": many}})
    assert r.status_code == 422 and "at most 20" in r.text
    r = client.post("/v1/recommend", json={"buying_power": 5000, "exclude": many[:21]})
    assert r.status_code == 422 and "at most 20" in r.text


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e10"])
def test_non_finite_or_huge_buying_power_is_a_422_not_a_500(
    client: TestClient, literal: str
) -> None:
    for path, body in (
        ("/v1/recommend", f'{{"buying_power": {literal}}}'),
        (
            "/v1/screen",
            '{"profile": {"buying_power": ' + literal + ', "account_value": 1000, '
            '"account_type": "cash", "risk_profile": "balanced"}}',
        ),
    ):
        r = client.post(path, content=body, headers={"Content-Type": "application/json"})
        assert r.status_code == 422, (path, literal, r.status_code, r.text)
        assert "buying_power" in r.text


def test_a_body_over_256_kb_is_refused(client: TestClient) -> None:
    big = '{"request_text": "' + "x" * 300_000 + '"}'
    r = client.post("/v1/screen", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413

    def chunks() -> Iterator[bytes]:  # no Content-Length: counted as it arrives
        yield b'{"request_text": "'
        for _ in range(40):
            yield b"x" * 8192
        yield b'"}'

    r = client.post("/v1/screen", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    ok = client.post("/v1/recommend", json={"buying_power": 5000, "watchlist": ["AAPL"]})
    assert ok.status_code == 200, ok.text


def test_a_resume_answer_with_a_bad_ticker_or_amount_is_a_422(client: TestClient) -> None:
    r = client.post("/v1/screen", json={"request_text": "help me find income ideas"})
    assert r.status_code == 200, r.text
    tid, token = r.json()["thread_id"], r.json()["thread_token"]
    for _ in range(600):
        s = client.get(f"/v1/runs/{tid}", headers={TOKEN: token}).json()
        if s["status"] in ("interrupted", "completed", "failed", "withheld"):
            break
        time.sleep(0.1)
    assert s["status"] == "interrupted"
    for answer in (
        {"buying_power": 5000, "watchlist": ["../../x"]},
        {"buying_power": 5000, "watchlist": [f"T{i}" for i in range(21)]},
        {"buying_power": -1},
        {"max_positions": 10_000},
    ):
        resp = client.post(
            f"/v1/runs/{tid}/resume", json={"answer": answer}, headers={TOKEN: token}
        )
        _rejected(resp, "../../x")
    resp = client.post(
        f"/v1/runs/{tid}/resume",
        content='{"answer": {"buying_power": NaN}}',
        headers={TOKEN: token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422
