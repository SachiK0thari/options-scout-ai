"""W38: credentials never leave the process (redaction, provider errors, tracing opt-in)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
import pytest

from options_scout import observability
from options_scout.config import AppConfig
from options_scout.observability import REDACTED, redact

KEY = "CANARYunitKEY123"


@pytest.mark.parametrize(
    "text",
    [
        f"GET https://www.alphavantage.co/query?function=NEWS&apikey={KEY}&limit=5",
        f"https://api.stlouisfed.org/fred/series/observations?series_id=X&api_key={KEY}",
        f"https://example.com/?token={KEY}",
        f"headers: Authorization: Bearer {KEY}",
        f'{{"Authorization": "Bearer {KEY}"}}',
        f"client_secret={KEY}",
    ],
)
def test_redact_strips_credentials_by_pattern(text: str) -> None:
    out = redact(text)
    assert KEY not in out and REDACTED in out


def test_redact_strips_the_value_of_any_secret_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOME_PROVIDER_API_KEY", KEY)
    assert redact(f"provider said: invalid key {KEY}.") == f"provider said: invalid key {REDACTED}."
    assert (
        redact("nothing secret here: 40 tokens, HTTP 401")
        == "nothing secret here: 40 tokens, HTTP 401"
    )


def test_log_lines_are_redacted_and_httpx_is_quiet(caplog: pytest.LogCaptureFixture) -> None:
    observability.configure_logging()
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    event = observability._redact_event(None, "info", {"event": "x", "url": f"?apikey={KEY}"})
    assert KEY not in str(event)
    record = logging.LogRecord(
        "t", logging.ERROR, __file__, 1, "GET %s", (f"/q?apikey={KEY}",), None
    )
    assert observability.RedactingFilter().filter(record) and KEY not in record.getMessage()


def test_tracing_needs_an_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in (
        "LANGSMITH_TRACING_V2",
        "LANGCHAIN_TRACING_V2",
        "LANGSMITH_HIDE_INPUTS",
        "LANGSMITH_HIDE_OUTPUTS",
        "LANGSMITH_PROJECT",
    ):
        monkeypatch.setenv(flag, "")  # registers each flag so monkeypatch restores it
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-canary-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("OPTIONS_SCOUT_TRACING", raising=False)
    assert observability.tracing_backend() == "otel-console"
    import os

    assert os.environ["LANGSMITH_TRACING"] == "false"
    monkeypatch.setenv("OPTIONS_SCOUT_TRACING", "langsmith")
    assert observability.tracing_backend() == "langsmith"
    assert os.environ["LANGSMITH_HIDE_INPUTS"] == "true"
    assert os.environ["LANGSMITH_HIDE_OUTPUTS"] == "true"


def test_state_reducers_redact_errors_and_source_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from options_scout.agent.state import add_redacted, merge_redacted, reducer_kinds

    assert add_redacted(["a"], [f"news: GET ?apikey={KEY}"]) == [
        "a",
        f"news: GET ?apikey={REDACTED}",
    ]
    assert KEY not in str(merge_redacted({}, {"fred": f"error api_key={KEY}"}))
    kinds = reducer_kinds()
    assert kinds["errors"] == "add" and kinds["data_source_status"] == "merge"


def _error_of(exc: pytest.ExceptionInfo[BaseException]) -> str:
    return str(exc.value) + repr(exc.value)


def test_alphavantage_error_carries_status_and_host_only(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from options_scout.social.adapters.alphavantage_news import AlphaVantageNewsAdapter

    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", KEY)
    adapter = AlphaVantageNewsAdapter(
        "live",
        config.news.sources.alphavantage,
        None,
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"x": 1})),
        sleep=lambda _s: None,
    )
    with pytest.raises(RuntimeError) as exc:
        adapter._fetch_live("COST", datetime(2026, 11, 1, tzinfo=UTC))
    assert _error_of(exc) and KEY not in _error_of(exc) and "apikey" not in _error_of(exc)
    assert "HTTP 401 from www.alphavantage.co" in str(exc.value)


def test_fred_transport_error_carries_no_url(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date

    from options_scout.bottleneck.adapters.fred import FredSeriesAdapter

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    monkeypatch.setenv("FRED_API_KEY", KEY)
    fred = FredSeriesAdapter(
        "live",
        config.bottleneck_sources.fred,
        None,
        transport=httpx.MockTransport(boom),
        sleep=lambda _s: None,
    )
    with pytest.raises(RuntimeError) as exc:
        fred._fetch_live("WPU0543", date(2026, 1, 1), date(2026, 11, 1))
    assert KEY not in _error_of(exc) and "api_key" not in _error_of(exc)
