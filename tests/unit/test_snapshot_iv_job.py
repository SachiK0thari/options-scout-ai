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


def test_backfill_fills_missing_sessions_skips_stored_ones_and_holidays(tmp_path: Path) -> None:
    """W4 step 6: the last N sessions come from historical chains, newest first; a stored session
    costs no request and a holiday (no chain) does not count as a session."""
    from options_scout.core.models import OptionQuote

    asked: list[date] = []
    holiday = date(2026, 11, 11)

    class _Source:
        name = "marketdata"
        chain_feed = "historical"

        @staticmethod
        def _today() -> date:
            return date(2026, 11, 13)  # Friday: the latest session is Thursday 12 Nov

        def session_chains(self, ticker: str, day: date) -> Any:
            asked.append(day)
            if day == holiday:
                return None
            expiry = date(2026, 12, 18)
            quotes = [
                OptionQuote(
                    contract_symbol=f"X{kind}",
                    kind=kind,
                    strike=100.0,
                    expiry=expiry,
                    bid=0.0,
                    ask=0.0,
                    iv=0.20 + 0.01 * day.day / 10,
                )
                for kind in ("call", "put")
            ]
            chain = OptionChain(
                ticker=ticker,
                expiry=expiry,
                as_of=datetime(day.year, day.month, day.day, 21, tzinfo=UTC),
                calls=[quotes[0]],
                puts=[quotes[1]],
            )
            return 100.0, [chain]

    class _MD:
        source = _Source()
        near_dte = (20, 60)

        def get_risk_free_rate(self) -> float:
            return 0.04

        def get_dividend_yield(self, ticker: str) -> float:
            raise RuntimeError("no dividend data")  # falls back to 0.0, as build_snapshot does

    store = snapshot_iv.IVSnapshotStore(tmp_path / "iv.sqlite")
    store.record("AAPL", date(2026, 11, 10), 0.99)  # already stored: kept, not fetched
    added = snapshot_iv.backfill(_MD(), store, ["AAPL"], 4)
    # sessions newest first: 12th, (11th holiday), 10th stored, 9th, 6th
    assert asked == [date(2026, 11, 12), holiday, date(2026, 11, 9), date(2026, 11, 6)]
    assert added == {"AAPL": 3}
    days = [r[0] for r in store._conn.execute("SELECT day FROM iv_snapshots ORDER BY day")]
    assert days == ["2026-11-06", "2026-11-09", "2026-11-10", "2026-11-12"]
    assert store.history("AAPL")[2] == 0.99


def test_marketdata_session_chains_splits_the_whole_chain_by_expiry() -> None:
    import httpx

    from options_scout.data.market import MarketDataAppSource

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params["date"] == "2026-11-11":
            return httpx.Response(204)
        body = {
            "s": "ok",
            "optionSymbol": ["A1", "A2", "B1"],
            "side": ["call", "put", "call"],
            "strike": [100, 100, 110],
            "expiration": [1797627600, 1797627600, 1800046800],
            "bid": [1.0, 1.1, 2.0],
            "ask": [1.2, 1.3, 2.2],
            "openInterest": [10, 20, 30],
            "underlyingPrice": [101.5, 101.5, 101.5],
            "updated": [1762981200, 1762981200, 1762981200],
        }
        return httpx.Response(200, json=body)

    client = httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler))
    src = MarketDataAppSource("token", http_client=client)
    got = src.session_chains("aapl", date(2026, 11, 12))
    assert got is not None
    spot, chains = got
    assert spot == 101.5 and [len(c.calls) + len(c.puts) for c in chains] == [2, 1]
    assert chains[0].expiry < chains[1].expiry and chains[0].ticker == "AAPL"
    assert seen[0].url.params["expiration"] == "all" and seen[0].url.path.endswith("/AAPL/")
    assert src.session_chains("AAPL", date(2026, 11, 11)) is None
