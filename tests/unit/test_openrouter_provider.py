"""OpenRouterProvider against a mocked HTTP transport (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from options_scout.config import AppConfig, LLMProviderSettings, ModelPrice
from options_scout.llm.client import LLMClient, OpenRouterProvider

MODEL = "deepseek/deepseek-v4.1-flash"


class Answer(BaseModel):
    ticker: str
    score: int


def _settings() -> LLMProviderSettings:
    return LLMProviderSettings(
        extraction_model=MODEL,
        explanation_model=MODEL,
        judge_model=MODEL,
        pricing={MODEL: ModelPrice(input=0.14, output=0.42)},
        base_url="https://openrouter.test/api/v1",
    )


def _completion(content: str, usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 0,
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": usage,
    }


class _Server:
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-key"
        assert str(request.url).startswith("https://openrouter.test/api/v1/chat/completions")
        return httpx.Response(200, json=self.replies[len(self.requests) - 1])


def _provider(monkeypatch: pytest.MonkeyPatch, server: _Server) -> OpenRouterProvider:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return OpenRouterProvider(
        _settings(), http_client=httpx.Client(transport=httpx.MockTransport(server))
    )


def test_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterProvider(_settings())


def test_structured_request_and_reported_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _Server(
        [
            _completion(
                '{"ticker": "COST", "score": 7}',
                {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.000123},
            )
        ]
    )
    out, usage = _provider(monkeypatch, server).complete(
        task="parse_profile", model=MODEL, system="sys", user="usr", schema=Answer, max_tokens=64
    )
    assert out == Answer(ticker="COST", score=7)
    assert (usage.input_tokens, usage.output_tokens) == (100, 20)
    assert usage.cost_usd == pytest.approx(0.000123)  # OpenRouter-reported cost wins
    assert usage.model == MODEL and usage.task == "parse_profile" and not usage.cached

    body = server.requests[0]
    assert body["model"] == MODEL and body["max_tokens"] == 64
    assert body["temperature"] == 0  # deterministic task
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    rf = body["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["properties"].keys() == {"ticker", "score"}
    assert body["provider"] == {"require_parameters": True}
    assert body["usage"] == {"include": True}


def test_list_price_fallback_and_fenced_json(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _Server(
        [
            _completion(
                '```json\n{"ticker": "NKE", "score": 3}\n```',
                {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
            )
        ]
    )
    out, usage = _provider(monkeypatch, server).complete(
        task="explain_report", model=MODEL, system="s", user="u", schema=Answer, max_tokens=8
    )
    assert out.ticker == "NKE"
    assert usage.cost_usd == pytest.approx(0.14 + 0.42)
    assert "temperature" not in server.requests[0]  # narrative keeps provider default


def test_retries_once_with_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01}
    server = _Server(
        [
            _completion('{"ticker": "SBUX"}', usage),  # missing score
            _completion('{"ticker": "SBUX", "score": 1}', usage),
        ]
    )
    out, total = _provider(monkeypatch, server).complete(
        task="judge_explanation", model=MODEL, system="s", user="u", schema=Answer, max_tokens=8
    )
    assert out.score == 1
    assert len(server.requests) == 2
    assert total.input_tokens == 20 and total.cost_usd == pytest.approx(0.02)
    retry_msgs = server.requests[1]["messages"]
    assert retry_msgs[2]["role"] == "assistant" and "SBUX" in retry_msgs[2]["content"]
    assert "did not match the required JSON schema" in retry_msgs[3]["content"]


def test_gives_up_after_second_bad_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = {"prompt_tokens": 1, "completion_tokens": 1}
    server = _Server([_completion("not json", usage), _completion("{}", usage)])
    with pytest.raises(RuntimeError, match="schema validation failed"):
        _provider(monkeypatch, server).complete(
            task="extract_entities", model=MODEL, system="s", user="u", schema=Answer, max_tokens=8
        )


def test_refusal_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = _completion("", {"prompt_tokens": 1, "completion_tokens": 0})
    reply["choices"][0]["message"]["refusal"] = "no"
    with pytest.raises(RuntimeError, match="refused"):
        _provider(monkeypatch, _Server([reply])).complete(
            task="parse_profile", model=MODEL, system="s", user="u", schema=Answer, max_tokens=8
        )


def test_from_config_openrouter_mode_is_live_with_key(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client = LLMClient.from_config(config, mode="live")
    assert client.is_live and client.provider.name == "openrouter"
    assert client.models.extraction_model == MODEL
    assert client.mode == "live"
