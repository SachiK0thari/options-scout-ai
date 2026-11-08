"""The engine end to end in fixture mode, the snapshot store and the refresh job (step 11.3)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from options_scout.bottleneck.engine import BottleneckEngine, BottleneckStore
from options_scout.bottleneck.thesis import FLAG_EASING, FLAG_WEAKENING
from options_scout.config import AppConfig
from options_scout.jobs import refresh_bottlenecks
from options_scout.llm.client import LLMClient

CURATED_SUPPLIERS = {"HON", "CSCO", "XOM", "CVX", "UNP"}


def test_fixture_run_builds_the_board_and_journals_it(config: AppConfig, tmp_path: Path) -> None:
    llm = LLMClient.from_config(config, mode="none")
    store = BottleneckStore(tmp_path / "snap.sqlite")
    engine = BottleneckEngine(config, llm, mode="fixture", store=store)
    run = engine.run()
    layers = run.layer_rows
    companies = run.company_rows
    assert len(layers) == 8 and len(companies) == 30 and run.snippets_in > 250
    assert (
        run.classification.from_ground_truth > 200
        and run.classification.unvalidated_tickers_rejected == 0
    )
    assert run.errors == [] and run.as_of.date().isoformat() == "2026-10-27"
    for row in layers:
        assert row.ticker is None and row.role is None and 0 <= row.score <= 100
        assert 3 <= len(row.evidence) <= 5 and any(e.kind == "filing" for e in row.evidence)
        assert all(len(e.excerpt) <= 200 for e in row.evidence)
        assert any(
            e.kind == "price" and e.url and e.url.startswith("https://fred.stlouisfed.org/series/")
            for e in row.evidence
        )
        assert row.components["price_series_points"] >= 6 and "price_trend" in row.components
        assert row.falsifiers and all(f.observed is not None for f in row.falsifiers)
    for s in companies:
        assert s.role == "supplier" and 0 <= s.score <= 100 and s.investable == s.curated
        assert s.layer_score == next(
            lr.score for lr in layers if lr.layer_id == s.layer_id and lr.theme_id == s.theme_id
        )
        assert "exposure" in s.components and 0 <= s.components["priced_in"] <= 1
        assert s.catalyst_days is None  # no market facts until step 11.4
    assert {s.ticker for s in companies if s.curated} == CURATED_SUPPLIERS
    assert set(run.scores(curated_only=True)) == CURATED_SUPPLIERS
    assert set(run.scores()) > CURATED_SUPPLIERS and all(
        0 <= v <= 100 for v in run.scores().values()
    )
    # designed shapes: battery's new-supply headlines trip its falsifier and decay its companies
    battery = next(lr for lr in layers if lr.layer_id == "battery")
    assert battery.thesis_weakening and FLAG_WEAKENING in battery.flags
    for s in companies:
        if s.layer_id == "battery":
            assert FLAG_EASING in s.flags and s.score == round(
                s.components["score_before_decay"] * 0.5, 2
            )
    power = next(lr for lr in layers if lr.layer_id == "power")
    assert not power.thesis_weakening and power.score > battery.score
    # the journal: one snapshot, readable while fresh, with per-layer component history
    assert store.count() == 1
    latest = store.latest(24, now=run.as_of + timedelta(hours=1))
    assert latest is not None and len(latest) == 38
    assert store.latest(24, now=run.as_of + timedelta(days=2)) is None
    assert store.layer_history("ai_datacenter/power", before=run.as_of.date()) == []
    assert [d for d, _ in store.layer_history("ai_datacenter/power")] == [run.as_of.date()]


def test_history_feeds_the_thesis_monitor_on_the_next_day(
    config: AppConfig, tmp_path: Path
) -> None:
    llm = LLMClient.from_config(config, mode="none")
    store = BottleneckStore(tmp_path / "snap.sqlite")
    day1 = BottleneckEngine(config, llm, mode="fixture", store=store).run()
    day2 = BottleneckEngine(config, llm, mode="fixture", store=store).run(
        end=day1.as_of + timedelta(days=1)
    )
    assert store.count() == 2
    history = store.layer_history("electrification/battery", before=day2.as_of.date())
    assert [d for d, _ in history] == [day1.as_of.date()]
    battery1 = next(lr for lr in day1.layer_rows if lr.layer_id == "battery")
    battery2 = next(lr for lr in day2.layer_rows if lr.layer_id == "battery")
    trend1 = next(f for f in battery1.falsifiers if f.signal == "price_trend")
    trend2 = next(f for f in battery2.falsifiers if f.signal == "price_trend")
    assert trend1.observed is not None and trend1.observed < 0 and not trend1.tripped  # needs 2
    assert trend2.tripped and trend2.since == day1.as_of.date()  # two consecutive daily hits
    # a run that does not persist leaves the journal alone (the signal study's point-in-time mode)
    BottleneckEngine(config, llm, mode="fixture", store=store).run(persist=False)
    assert store.count() == 2


def test_store_purges_by_retention(config: AppConfig, tmp_path: Path) -> None:
    llm = LLMClient.from_config(config, mode="none")
    store = BottleneckStore(tmp_path / "snap.sqlite")
    engine = BottleneckEngine(config, llm, mode="fixture", store=store)
    run = engine.run()
    assert store.purge(config.bottleneck.retention_days, now=run.as_of + timedelta(days=179)) == 0
    assert store.purge(config.bottleneck.retention_days, now=run.as_of + timedelta(days=181)) == 1
    assert store.count() == 0 and store.latest(24) is None
    store.close()


def test_refresh_job_prints_the_thesis_monitor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(refresh_bottlenecks, "store_path", lambda cfg: tmp_path / "snap.sqlite")
    assert refresh_bottlenecks.main(["--fixture", "--no-llm", "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Bottleneck board as of 2026-10-27")
    assert "Thesis monitor:" in out and "tripped since 2026-10-27" in out and "WEAKENING" in out
    assert "not on the good-to-own list" in out and "snapshots stored: 1" in out
    assert (tmp_path / "snap.sqlite").exists()
    for banned in ("exit", "sell", "take profits", "you should buy"):
        assert banned not in out.lower()
