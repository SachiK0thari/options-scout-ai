"""Structured logging, per-node timing and tracing (LangSmith if configured, else OTel console).

* ``structlog`` JSON logs keyed by ``thread_id``.
* LangSmith: opt-in only. Tracing needs ``OPTIONS_SCOUT_TRACING=langsmith`` as well as
  ``LANGSMITH_API_KEY``, and then sends ids, timings and token counts with inputs and outputs
  hidden (W38). A key alone turns nothing on.
* ``redact`` removes credentials from any string that leaves the process: log lines (structlog
  and stdlib), and every entry of the run's ``errors`` and ``data_source_status`` (the state
  reducers call it), which the API, the reports and the checkpoint file all read.
* Otherwise an OpenTelemetry tracer with a console (JSON) exporter emits one span per node.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt

_configured = False

REDACTED = "[redacted]"
# query-string and form parameters that carry a credential (``apikey=…``, ``token=…`` and so on)
_SECRET_PARAM = re.compile(
    r"(?i)\b((?:api[_-]?key|apikey|access[_-]?token|token|client[_-]?secret|secret|password)"
    r"[\"']?\s*[=:]\s*[\"']?)[^\s&\"',;)}\]]+"
)
_AUTH_HEADER = re.compile(
    r"(?i)\b(authorization[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+|basic\s+|token\s+)?[^\s\"',;)}\]]+"
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
_SECRET_ENV = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD)$")
_QUIET_LOGGERS = ("httpx", "httpcore", "urllib3", "praw", "prawcore")


def _secret_env_values() -> list[str]:
    """Values of credential-looking environment variables, longest first (8+ characters)."""
    vals = {v for k, v in os.environ.items() if _SECRET_ENV.search(k.upper()) and len(v) >= 8}
    return sorted(vals, key=len, reverse=True)


def redact(text: str) -> str:
    """``text`` with credentials removed: any value of a ``*_KEY`` / ``*_TOKEN`` / ``*_SECRET``
    environment variable, ``apikey=``-style parameters and ``Authorization`` / bearer values."""
    if not text:
        return text
    for v in _secret_env_values():
        if v in text:
            text = text.replace(v, REDACTED)
    text = _AUTH_HEADER.sub(lambda m: m.group(1) + REDACTED, text)
    text = _BEARER.sub(lambda m: m.group(1) + REDACTED, text)
    return _SECRET_PARAM.sub(lambda m: m.group(1) + REDACTED, text)


def redact_value(value: Any) -> Any:
    """``redact`` applied to every string inside lists, tuples and dict values."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list | tuple):
        return type(value)(redact_value(v) for v in value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    return value


def _redact_event(_logger: Any, _name: str, event: dict[str, Any]) -> dict[str, Any]:
    return {k: redact_value(v) for k, v in event.items()}


class RedactingFilter(logging.Filter):
    """Stdlib logging filter: the formatted message is redacted before any handler writes it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


def configure_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return
    level = level or os.environ.get("OPTIONS_SCOUT_LOG_LEVEL", "INFO")
    logging.basicConfig(level=level, stream=sys.stderr, format="%(message)s")
    for name in _QUIET_LOGGERS:  # httpx logs every full URL, query-string keys included, at INFO
        logging.getLogger(name).setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _redact_event,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(**bind: Any) -> Any:
    configure_logging()
    return structlog.get_logger().bind(**bind)


_TRACING_FLAGS = ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2")


def tracing_backend() -> str:
    """LangSmith only on an explicit ``OPTIONS_SCOUT_TRACING=langsmith`` with a key, and then
    with run inputs and outputs hidden. Otherwise every LangSmith/LangChain tracing flag is forced
    off, so a key left in the environment never uploads run state (profile, holdings)."""
    opted_in = os.environ.get("OPTIONS_SCOUT_TRACING", "").strip().lower() == "langsmith"
    if opted_in and os.environ.get("LANGSMITH_API_KEY"):
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_HIDE_INPUTS"] = "true"
        os.environ["LANGSMITH_HIDE_OUTPUTS"] = "true"
        os.environ.setdefault("LANGSMITH_PROJECT", "options-scout-ai")
        return "langsmith"
    for flag in _TRACING_FLAGS:
        os.environ[flag] = "false"
    return "otel-console"


class _Tracer:
    """Thin wrapper so the rest of the code never imports OpenTelemetry directly."""

    def __init__(self) -> None:
        self.backend = tracing_backend()
        self._otel: Any | None = None
        if self.backend == "otel-console" and os.environ.get("OPTIONS_SCOUT_OTEL", "0") == "1":
            try:
                from opentelemetry import trace
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

                provider = TracerProvider(
                    resource=Resource.create({"service.name": "options-scout-ai"})
                )
                provider.add_span_processor(
                    SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr))
                )
                trace.set_tracer_provider(provider)
                self._otel = trace.get_tracer("options_scout")
            except Exception:  # OTel is optional
                self._otel = None

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[None]:
        if self._otel is None:
            yield
            return
        with self._otel.start_as_current_span(name) as sp:
            for k, v in attrs.items():
                sp.set_attribute(k, str(v))
            yield


TRACER = _Tracer()


def timed_node(name: str, fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Wrap a node so every call records latency, visit order, and a trace span."""

    def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        log = get_logger(node=name, run_id=state.get("run_id"))
        t0 = time.perf_counter()
        with TRACER.span(f"node:{name}", run_id=state.get("run_id", "")):
            try:
                out = fn(state, *args, **kwargs)
            except GraphInterrupt:
                raise  # human-in-the-loop pause, not a failure
            except Exception as exc:
                log.error("node_failed", error=redact(str(exc)))
                raise
        ms = (time.perf_counter() - t0) * 1000.0
        log.info("node_done", latency_ms=round(ms, 1))
        out = dict(out or {})
        prev = (
            float(out.get("node_latency_ms", {}).get(name, 0.0))
            if isinstance(out.get("node_latency_ms"), dict)
            else 0.0
        )
        out["node_latency_ms"] = {**out.get("node_latency_ms", {}), name: round(prev + ms, 1)}
        out["nodes_visited"] = [*out.get("nodes_visited", []), name]
        return out

    wrapper.__name__ = name
    return wrapper


AgentFn = Callable[..., dict[str, Any]]  # (state, config) -> partial state


def timed_agent(name: str, fn: AgentFn) -> AgentFn:
    """Wrap a specialist's parent-graph node (Phase 10): ``agent.start`` / ``agent.end`` events,
    a trace span, per-agent latency (summed over retries) and the order specialists ran in."""

    def wrapper(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        log = get_logger(agent=name, run_id=state.get("run_id"))
        log.info("agent.start")
        t0 = time.perf_counter()
        with TRACER.span(f"agent:{name}", run_id=state.get("run_id", "")):
            try:
                out = fn(state, config)
            except GraphInterrupt:
                log.info("agent.end", status="interrupted")
                raise  # human-in-the-loop pause, not a failure
            except Exception as exc:
                log.error("agent.end", status="failed", error=redact(str(exc)))
                raise
        ms = (time.perf_counter() - t0) * 1000.0
        log.info("agent.end", status="ok", latency_ms=round(ms, 1))
        out = dict(out or {})
        prev = float((state.get("agent_latency_ms") or {}).get(name, 0.0))
        out["agent_latency_ms"] = {**out.get("agent_latency_ms", {}), name: round(prev + ms, 1)}
        out["agents_visited"] = [*out.get("agents_visited", []), name]
        return out

    wrapper.__name__ = name
    return wrapper
