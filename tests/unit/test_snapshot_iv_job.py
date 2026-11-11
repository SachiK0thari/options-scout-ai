"""The daily IV job records each reading under the session its quotes are from (W11 step 4)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from options_scout.core.models import OptionChain, SpotQuote, TickerSnapshot
from options_scout.jobs import snapshot_iv


def test_the_reading_is_dated_to_the_quotes_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Any
) -> None:
    session = datetime(2026, 11, 9, 21, 0, tzinfo=UTC)  # Monday's close
    ran = datetime(2026, 11, 11, 1, 30, tzinfo=UTC)  # the job ran two days later (UTC)

    class _Source:
        name = "marketdata"

    class _MD:
        source = _Source()

        def build_snapshot(self, ticker: str) -> TickerSnapshot:
            chain = OptionChain(
                ticker=ticker, expiry=date(2026, 12, 18), as_of=session, calls=[], puts=[]
            )
            return TickerSnapshot(
                ticker=ticker,
                as_of=ran,
                spot=SpotQuote(ticker=ticker, price=100.0, avg_volume=1e6, as_of=session),
                chains=[chain],
                earnings_date=None,
                atm_iv=0.25,
            )

    cfg = config.model_copy(
        update={
            "settings": config.settings.model_copy(
                update={
                    "paths": config.settings.paths.model_copy(
                        update={"iv_snapshot_db": tmp_path / "iv.sqlite"}
                    )
                }
            )
        }
    )
    monkeypatch.setattr("options_scout.config.get_config", lambda: cfg)
    monkeypatch.setattr("options_scout.env.check_startup_or_exit", lambda: None)
    monkeypatch.setattr(
        "options_scout.data.market.MarketData.from_config", classmethod(lambda cls, c: _MD())
    )
    assert snapshot_iv.main(["AAPL"]) == 0
    store = snapshot_iv.IVSnapshotStore(tmp_path / "iv.sqlite")
    rows = store._conn.execute("SELECT ticker, day, atm_iv FROM iv_snapshots").fetchall()
    assert rows == [("AAPL", "2026-11-09", 0.25)]


def test_fixture_mode_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Any
) -> None:
    paths = config.settings.paths.model_copy(update={"iv_snapshot_db": tmp_path / "iv.sqlite"})
    cfg = config.model_copy(
        update={
            "settings": config.settings.model_copy(update={"paths": paths, "data_mode": "fixture"})
        }
    )
    monkeypatch.setattr("options_scout.config.get_config", lambda: cfg)
    monkeypatch.setattr("options_scout.env.check_startup_or_exit", lambda: None)
    assert snapshot_iv.main(["AAPL"]) == 0  # skipped, not failed
    store = snapshot_iv.IVSnapshotStore(tmp_path / "iv.sqlite")
    assert store._conn.execute("SELECT COUNT(*) FROM iv_snapshots").fetchone() == (0,)


def test_a_session_already_recorded_is_not_fetched_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Any
) -> None:
    """Weekend passes: the historical feed's session is known before fetching, and a ticker
    whose reading for it is stored costs nothing."""
    built: list[str] = []

    class _Source:
        name = "marketdata"
        chain_feed = "historical"

        @staticmethod
        def _today() -> date:
            return date(2026, 11, 15)  # a Sunday: the expected session is Friday 13 Nov

    class _MD:
        source = _Source()

        def build_snapshot(self, ticker: str) -> TickerSnapshot:
            built.append(ticker)
            raise AssertionError("should not fetch")

    paths = config.settings.paths.model_copy(update={"iv_snapshot_db": tmp_path / "iv.sqlite"})
    cfg = config.model_copy(
        update={"settings": config.settings.model_copy(update={"paths": paths})}
    )
    snapshot_iv.IVSnapshotStore(tmp_path / "iv.sqlite").record("AAPL", date(2026, 11, 13), 0.24)
    monkeypatch.setattr("options_scout.config.get_config", lambda: cfg)
    monkeypatch.setattr("options_scout.env.check_startup_or_exit", lambda: None)
    monkeypatch.setattr(
        "options_scout.data.market.MarketData.from_config", classmethod(lambda cls, c: _MD())
    )
    assert snapshot_iv.main(["AAPL"]) == 0 and built == []
    assert snapshot_iv.expected_session(_MD()) == date(2026, 11, 13)
