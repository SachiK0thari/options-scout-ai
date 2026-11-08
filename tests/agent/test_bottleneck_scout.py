"""bottleneck_scout_node (step 11.4): snapshot reuse, fresh runs, degradation, never fatal."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from options_scout.agent.deps import Deps
from options_scout.agent.graph import initial_state
from options_scout.agent.nodes import bottleneck_scout
from options_scout.agent.nodes.bottleneck_scout import bottleneck_scores_from, fresh_snapshot
from options_scout.bottleneck.engine import BottleneckEngine, BottleneckStore
from options_scout.config import AppConfig


@pytest.fixture
def deps(config: AppConfig, tmp_path: Path) -> Deps:
    from options_scout.social.pipeline import TrendStore

    d = Deps.from_config(config, with_social=False)
    d.trend_store = TrendStore(tmp_path / "t.sqlite")
    d.bottleneck_store = BottleneckStore(tmp_path / "b.sqlite")
    return d


def _run(deps: Deps) -> dict[str, Any]:
    return bottleneck_scout.make(deps)(initial_state("x"))


def test_runs_the_engine_then_reuses_the_journalled_snapshot(deps: Deps) -> None:
    out = _run(deps)
    rows = out["bottlenecks"]
    assert len([s for s in rows if s.ticker is None]) == 8 and out["errors"] == []
    assert out["data_source_status"]["bottleneck"].startswith("ran (")
    assert out["data_source_status"]["bottleneck:edgar"] == "ok"
    scores = out["bottleneck_scores"]
    assert scores == bottleneck_scores_from(rows)
    assert {"HON", "CSCO", "XOM", "CVX", "UNP", "GEV"} <= set(scores)  # every supplier scores…
    assert "MSFT" not in scores  # …a customer never does (4A.4)
    assert all(0 <= v <= 100 for v in scores.values())
    assert deps.bottlenecks().count() == 1
    again = _run(deps)
    assert again["data_source_status"] == {"bottleneck": "snapshot"}
    assert [s.model_dump() for s in again["bottlenecks"]] == [s.model_dump() for s in rows]


def test_disabled_engine_writes_an_empty_board(deps: Deps) -> None:
    deps.disabled_sources.add("bottleneck")
    out = _run(deps)
    assert out["bottlenecks"] == [] and out["bottleneck_scores"] == {}
    assert out["data_source_status"] == {"bottleneck": "disabled"}
    assert any("engine disabled" in e for e in out["errors"])


def test_pipeline_failure_is_reported_not_raised(deps: Deps) -> None:
    class Boom:
        def run(self, **_: Any) -> Any:
            raise RuntimeError("edgar down")

    deps.bottleneck_engine = Boom()  # type: ignore[assignment]
    out = _run(deps)
    assert out["bottlenecks"] == [] and out["bottleneck_scores"] == {}
    assert out["data_source_status"] == {"bottleneck": "error"}
    assert any("edgar down" in e for e in out["errors"])


def test_fresh_snapshot_rejects_stale_and_future_dated_boards(
    deps: Deps, config: AppConfig
) -> None:
    store = deps.bottlenecks()
    run = BottleneckEngine(config, deps.llm, mode="fixture", store=store).run()
    max_age = config.bottleneck.snapshot_max_age_hours
    assert fresh_snapshot(store, max_age, run.as_of + timedelta(hours=1)) is not None
    assert fresh_snapshot(store, max_age, run.as_of + timedelta(hours=max_age + 1)) is None
    # a snapshot dated after the data clock (a live run next to fixture data) is not today's board
    assert fresh_snapshot(store, max_age, run.as_of - timedelta(hours=max_age + 1)) is None
    assert (
        fresh_snapshot(BottleneckStore(store.path.parent / "empty.sqlite"), max_age, run.as_of)
        is None
    )
