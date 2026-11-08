"""``build_universe`` (step 11.4): the two Market Intelligence signals promote curated names and
never add one; a non-curated signal ticker is reported as skipped with the signal that found it."""

from __future__ import annotations

import pytest

from options_scout.agent.nodes.universe import build_universe, combine_signal_scores

CURATED = ["SPY", "QQQ", "AAPL", "MSFT", "COST", "NKE", "HON", "UNP"]


def _build(scores: dict[str, float], kinds: dict[str, str] | None = None, **over: object):
    kwargs: dict[str, object] = {
        "curated": CURATED,
        "watchlist": [],
        "exclude": [],
        "signal_scores": scores,
        "max_tickers": 10,
        "available": None,
        "signal_kinds": kinds,
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
    scores, kinds = combine_signal_scores({}, {"HON": 40.0, "UNP": 3.0, "GEV": 79.0, "VST": 79.0})
    universe, notes = _build(scores, kinds)
    assert universe[:2] == ["HON", "UNP"] and set(universe) == set(CURATED)
    assert "GEV" not in universe and "VST" not in universe  # re-orders, never adds (4A.1)
    assert notes == [
        "universe: bottleneck ticker GEV is not on the good-to-own list; skipped",
        "universe: bottleneck ticker VST is not on the good-to-own list; skipped",
    ]


def test_both_signals_order_by_the_higher_score() -> None:
    scores, kinds = combine_signal_scores({"COST": 80.0, "HON": 10.0}, {"HON": 40.0, "NKE": 60.0})
    universe, notes = _build(scores, kinds)
    assert universe[:3] == ["COST", "NKE", "HON"]
    assert notes == []


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
