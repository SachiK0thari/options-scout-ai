"""``build_universe`` (step 11.4): the two Market Intelligence signals promote curated names and
never add one; a non-curated signal ticker is reported as skipped with the signal that found it.

W29: only a score at or above ``universe.signal_promotion_min`` (60) moves a curated name forward.
A weaker score leaves the name at its list position."""

from __future__ import annotations

from pathlib import Path

import pytest

from options_scout.agent.nodes.universe import build_universe, combine_signal_scores
from options_scout.config import AppConfig

CURATED = ["SPY", "QQQ", "AAPL", "MSFT", "COST", "NKE", "HON", "UNP"]
PROMOTE = 60.0


def _build(scores: dict[str, float], kinds: dict[str, str] | None = None, **over: object):
    kwargs: dict[str, object] = {
        "curated": CURATED,
        "watchlist": [],
        "exclude": [],
        "signal_scores": scores,
        "max_tickers": 10,
        "available": None,
        "signal_kinds": kinds,
        "promotion_min": PROMOTE,
    }
    kwargs.update(over)
    return build_universe(**kwargs)  # type: ignore[arg-type]


def test_combine_takes_the_max_and_remembers_which_signal() -> None:
    scores, kinds = combine_signal_scores({"COST": 80.0, "HON": 20.0}, {"HON": 40.0, "GEV": 79.0})
    assert scores == {"COST": 80.0, "HON": 40.0, "GEV": 79.0}
    assert kinds == {"COST": "trending", "HON": "bottleneck", "GEV": "bottleneck"}
    assert combine_signal_scores({}, {}) == ({}, {})


def test_neither_signal_keeps_list_order() -> None:
    universe, notes = _build({})
    assert universe == CURATED and notes == []


def test_only_social_promotes_trending_curated_names() -> None:
    universe, notes = _build({"NKE": 70.0, "COST": 80.0, "CMG": 90.0}, {"CMG": "trending"})
    assert universe[:2] == ["COST", "NKE"] and set(universe) == set(CURATED)
    assert notes == ["universe: trending ticker CMG is not on the good-to-own list; skipped"]


def test_only_bottleneck_promotes_curated_suppliers_and_skips_pure_plays() -> None:
    scores, kinds = combine_signal_scores({}, {"HON": 65.0, "UNP": 3.0, "GEV": 79.0, "VST": 79.0})
    universe, notes = _build(scores, kinds)
    assert universe[0] == "HON" and set(universe) == set(CURATED)
    assert universe.index("UNP") == len(CURATED) - 1  # 3 is below the threshold: list position
    assert "GEV" not in universe and "VST" not in universe  # re-orders, never adds (4A.1)
    assert notes == [
        "universe: bottleneck ticker GEV is not on the good-to-own list; skipped",
        "universe: bottleneck ticker VST is not on the good-to-own list; skipped",
    ]


def test_both_signals_order_by_the_higher_score() -> None:
    scores, kinds = combine_signal_scores({"COST": 80.0, "HON": 10.0}, {"HON": 70.0, "NKE": 60.0})
    universe, notes = _build(scores, kinds)
    assert universe[:3] == ["COST", "HON", "NKE"]
    assert notes == []


@pytest.mark.parametrize(
    ("score", "promoted"), [(PROMOTE, True), (PROMOTE - 0.1, False), (3.0, False)]
)
def test_only_a_score_at_the_threshold_promotes(score: float, promoted: bool) -> None:
    """W29 step 2: the threshold is inclusive; below it the name keeps its list position."""
    universe, _ = _build({"UNP": score})
    assert (universe[0] == "UNP") is promoted
    if not promoted:
        assert universe == CURATED


def test_low_scores_do_not_push_list_names_out_of_a_capped_run() -> None:
    """W29: HON, XOM, CVX and UNP (37, 11, 11, 3 on the fixture board) used to jump the queue and
    push ACN, COST, WMT and PG out of a 12-ticker run."""
    curated = [f"C{i:02d}" for i in range(28)] + ["HON", "XOM", "CVX", "UNP"]
    low = {"HON": 37.0, "XOM": 11.0, "CVX": 11.0, "UNP": 3.0}
    plain, _ = _build({}, curated=curated, max_tickers=12)
    universe, _ = _build(low, curated=curated, max_tickers=12)
    assert universe == plain == curated[:12]


def test_fixture_boards_leave_the_curated_order_unchanged(
    config: AppConfig, tmp_path: Path
) -> None:
    """W29 step 1: with the fixture bottleneck board no curated supplier reaches 60, so the
    universe is the no-signal universe."""
    from options_scout.agent.deps import Deps
    from options_scout.agent.graph import initial_state
    from options_scout.agent.nodes import bottleneck_scout
    from options_scout.bottleneck.engine import BottleneckStore
    from options_scout.social.pipeline import TrendStore

    deps = Deps.from_config(config, with_social=False)
    deps.trend_store = TrendStore(tmp_path / "t.sqlite")
    deps.bottleneck_store = BottleneckStore(tmp_path / "b.sqlite")
    board = bottleneck_scout.make(deps)(initial_state("x"))["bottleneck_scores"]
    curated = config.quality.symbols
    assert set(board) & set(curated)  # the board does score curated suppliers…
    assert all(board[t] < PROMOTE for t in set(board) & set(curated))  # …all below 60
    scores, kinds = combine_signal_scores({}, board)
    common = {"curated": curated, "max_tickers": config.quality.universe.max_tickers}
    plain, _ = _build({}, **common)
    universe, _ = _build(scores, kinds, **common)
    assert universe == plain


def test_promotion_threshold_is_configured(config: AppConfig) -> None:
    assert config.quality.universe.signal_promotion_min == PROMOTE


@pytest.mark.parametrize("watch", [["GEV"], ["gev", "COST"]])
def test_user_added_pure_play_is_considered_then_gated_by_availability(watch: list[str]) -> None:
    scores, kinds = combine_signal_scores({}, {"GEV": 79.0, "HON": 40.0})
    universe, notes = _build(scores, kinds, watchlist=watch)
    assert universe[0] == "GEV"  # the user's ticker is screened, no "skipped" note for it
    assert not any("GEV" in n for n in notes)
    universe, notes = _build(scores, kinds, watchlist=watch, available=set(CURATED))
    assert "GEV" not in universe
    assert any(n.startswith("universe: no offline fixture for GEV") for n in notes)


def test_exclusions_beat_signals() -> None:
    scores, kinds = combine_signal_scores({"COST": 80.0}, {"HON": 40.0})
    universe, notes = _build(scores, kinds, exclude=["cost", "HON"])
    assert "COST" not in universe and "HON" not in universe and notes == []
