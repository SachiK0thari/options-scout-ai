"""Structured logging, per-node timing and tracing (LangSmith if configured, else OTel console).

* ``structlog`` JSON logs keyed by ``thread_id``.
* LangSmith: LangGraph traces automatically when ``LANGSMITH_API_KEY`` is set and
  ``LANGSMITH_TRACING=true``; we only set the project name.
* Otherwise an OpenTelemetry tracer with a console (JSON) exporter emits one span per node.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from langgraph.errors import GraphInterrupt

_configured = False


def configure_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return
    level = level or os.environ.get("OPTIONS_SCOUT_LOG_LEVEL", "INFO")
    logging.basicConfig(level=level, stream=sys.stderr, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
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


def tracing_backend() -> str:
    if os.environ.get("LANGSMITH_API_KEY"):
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_PROJECT", "options-scout-ai")
        return "langsmith"
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
                log.error("node_failed", error=str(exc))
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
