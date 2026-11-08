"""Signals, score and thesis monitor (PRD 4A.7–4A.9): goldens, property tests, falsifiers."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from options_scout.bottleneck import signals as sig
from options_scout.bottleneck.score import company_score, exposure, layer_score
from options_scout.bottleneck.themes import Falsifier, Layer, ThemeCompany
from options_scout.bottleneck.thesis import (
    FLAG_EASING,
    FLAG_NO_PRICE_DATA,
    FLAG_SUPPORT,
    FLAG_WEAKENING,
    apply_thesis,
    company_flags,
    evaluate_falsifiers,
)
from options_scout.config import AppConfig
from options_scout.core.models import ConstraintLabel, FilingSnippet, SeriesPoint

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_bottleneck.json").read_text()
)
END = date(2026, 10, 27)


def _item(
    day: date, direction: str, *, side: str = "supplier", kind: str = "price", source: str = "edgar"
) -> tuple[FilingSnippet, ConstraintLabel]:
    sid = f"{source}-{day.isoformat()}-{direction}-{side}-{kind}"
    snip = FilingSnippet(id=sid, source=source, text="x", date=day)  # type: ignore[arg-type]
    lbl = ConstraintLabel(
        snippet_id=sid, layer_id="grid", side=side, direction=direction, kind=kind, confidence=0.9
    )  # type: ignore[arg-type]
    return snip, lbl


def _golden_layer_series() -> sig.LayerSeries:
    """Six tightening mentions in the last 7 days, two per week in the eight prior weeks."""
    items = []
    recent_start = END - timedelta(days=6)
    for i in range(6):
        items.append(_item(recent_start + timedelta(days=i), "tightening"))
    for w in range(8):
        week_end = recent_start - timedelta(days=1 + 7 * w)
        items.append(_item(week_end, "tightening"))
        items.append(_item(week_end - timedelta(days=3), "tightening", side="customer"))
    return sig.aggregate_layer(items)


def _golden_points() -> list[SeriesPoint]:
    g = GOLDEN["layer"]
    return [
        SeriesPoint(day=date.fromisoformat(d), value=v)
        for d, v in zip(g["series_days"], g["series_values"], strict=True)
    ]


# ------------------------------------------------------------------------------- goldens
def test_golden_tightness_z(config: AppConfig) -> None:
    ls = _golden_layer_series()
    assert sig.tightness_z(ls, END, config.bottleneck.normalization) == pytest.approx(
        GOLDEN["layer"]["tightness_z"], abs=1e-6
    )
    assert sig.customer_confirmation(ls) == pytest.approx(8 / 22)


def test_golden_price_trend_and_deceleration(config: AppConfig) -> None:
    norm = config.bottleneck.normalization
    pts = _golden_points()
    assert sig.price_trend(pts, END, norm) == pytest.approx(
        GOLDEN["layer"]["price_trend"], abs=1e-6
    )
    assert sig.price_deceleration(pts, END, norm) == pytest.approx(
        GOLDEN["layer"]["price_deceleration"], abs=1e-6
    )


def test_golden_layer_and_company_score(config: AppConfig) -> None:
    cfg = config.bottleneck
    comps = GOLDEN["layer"]["components"]
    assert layer_score(comps, cfg) == pytest.approx(GOLDEN["layer"]["layer_score"], abs=0.011)
    g = GOLDEN["company"]
    company = ThemeCompany(
        ticker="HON",
        role="supplier",
        materiality=g["materiality"],
        pricing_power=g["pricing_power"],
        capacity=g["capacity"],
    )
    exp = exposure(company, g["priced_in"], cfg)
    assert exp == pytest.approx(g["exposure"], abs=1e-6)
    assert company_score(GOLDEN["layer"]["layer_score"], exp) == pytest.approx(
        g["score"], abs=0.011
    )
    with pytest.raises(ValueError):
        exposure(ThemeCompany(ticker="MSFT", role="customer"), 0.0, cfg)


# ------------------------------------------------------------------------ property tests
_BASE = {
    "customer_confirmation": 0.3,
    "price_trend": 0.2,
    "cross_source_norm": 0.5,
    "supplier_scarcity": 0.5,
    "capacity_lead": 0.4,
    "price_deceleration": 0.0,
}


@settings(max_examples=150, deadline=None)
@given(
    tz=st.floats(-4, 4),
    cc=st.floats(0, 1),
    pt=st.floats(-1, 1),
    cs=st.floats(0, 1),
    dec=st.floats(0, 1),
    srz=st.floats(-4, 4),
)
def test_layer_score_is_bounded(
    tz: float, cc: float, pt: float, cs: float, dec: float, srz: float
) -> None:
    from options_scout.config import load_config

    cfg = load_config().bottleneck
    comps = {
        **_BASE,
        "tightness_z": tz,
        "customer_confirmation": cc,
        "price_trend": pt,
        "cross_source_norm": cs,
        "price_deceleration": dec,
        "supply_response_z": srz,
    }
    assert 0.0 <= layer_score(comps, cfg) <= 100.0


@settings(max_examples=100, deadline=None)
@given(a=st.floats(-4, 4), b=st.floats(-4, 4))
def test_layer_score_is_monotone_in_tightness_and_non_increasing_in_supply_response(
    a: float, b: float
) -> None:
    from options_scout.config import load_config

    cfg = load_config().bottleneck
    lo, hi = sorted((a, b))
    assert layer_score({**_BASE, "tightness_z": lo, "supply_response_z": 0.0}, cfg) <= layer_score(
        {**_BASE, "tightness_z": hi, "supply_response_z": 0.0}, cfg
    )
    assert layer_score({**_BASE, "tightness_z": 1.0, "supply_response_z": hi}, cfg) <= layer_score(
        {**_BASE, "tightness_z": 1.0, "supply_response_z": lo}, cfg
    )


@settings(max_examples=100, deadline=None)
@given(a=st.floats(0, 1), b=st.floats(0, 1))
def test_company_score_is_non_increasing_in_priced_in(a: float, b: float) -> None:
    from options_scout.config import load_config

    cfg = load_config().bottleneck
    company = ThemeCompany(
        ticker="HON",
        role="supplier",
        materiality="high",
        pricing_power="high",
        capacity="constrained",
    )
    lo, hi = sorted((a, b))
    assert company_score(80.0, exposure(company, hi, cfg)) <= company_score(
        80.0, exposure(company, lo, cfg)
    )


# ------------------------------------------------------------------- missing price data
def test_missing_series_read_as_missing_not_flat(config: AppConfig) -> None:
    norm = config.bottleneck.normalization
    cfg = config.bottleneck
    short = _golden_points()[:4]
    assert (
        sig.price_trend(short, END, norm) is None
        and sig.price_deceleration(short, END, norm) is None
    )
    assert sig.price_trend([], END, norm) is None
    layer = config.themes.get("electrification").get_layer("grid")  # type: ignore[union-attr]
    assert layer is not None
    comps = sig.layer_components(layer, sig.LayerSeries(), {}, end=END, cfg=cfg, sources_enabled=6)
    assert comps["price_trend"] is None and comps["price_deceleration"] is None
    assert "price_trend" not in sig.finite(comps) and comps["price_series_points"] == 0.0
    # with nothing known the score is the bias alone, and a strong tightness is not diluted by
    # the absent price term (the remaining weights are scaled up to the full mass)
    nothing = {
        **{k: 0.0 for k in _BASE},
        "tightness_z": 0.0,
        "price_trend": None,
        "price_deceleration": None,
    }
    assert layer_score(nothing, cfg) == layer_score({**nothing, "price_trend": 0.0}, cfg)
    strong = {**_BASE, "tightness_z": 3.0, "price_trend": None}
    assert layer_score(strong, cfg) > layer_score({**strong, "price_trend": 0.0}, cfg)
    assert FLAG_NO_PRICE_DATA in company_flags(10.0, strong, [], cfg)


def test_priced_in_blend_and_catalyst_days() -> None:
    assert sig.priced_in(None, None, 4.0) == 0.0
    assert sig.priced_in(2.0, None, 4.0) == 0.5
    facts = sig.CompanyMarketFacts(
        rel_return_90d=0.15, dist_from_high=0.0, iv_rank=50.0, next_event=END + timedelta(days=12)
    )
    assert sig.priced_in(None, facts, 4.0) == pytest.approx((0.5 + 1.0 + 0.5) / 3, abs=1e-4)
    assert sig.priced_in(-1.0, facts, 4.0) == pytest.approx((0.0 + 0.5 + 1.0 + 0.5) / 4, abs=1e-4)
    assert sig.catalyst_days(END, facts.next_event) == 12 and sig.catalyst_days(END, None) is None
    assert sig.catalyst_days(END, END - timedelta(days=3)) == 0


# ---------------------------------------------------------------------- thesis monitor
def _layer() -> Layer:
    return Layer(
        id="grid",
        name="Grid",
        keywords=["transformer lead time"],
        supplier_count="few",
        capacity_lead_years=3,
        thesis="Transformers are scarce for years.",
        falsifiers=[
            Falsifier(signal="price_deceleration", op=">", value=0.5, snapshots=2),
            Falsifier(signal="supply_response_z", op=">", value=1.5, snapshots=1),
            Falsifier(signal="tightness_z", op="<", value=-1.0, snapshots=3),
        ],
        companies=[
            ThemeCompany(
                ticker="GEV",
                role="supplier",
                materiality="high",
                pricing_power="high",
                capacity="constrained",
            )
        ],
    )


def test_falsifiers_need_consecutive_snapshots_and_skip_missing_signals(config: AppConfig) -> None:
    d1, d2, d3 = END - timedelta(days=2), END - timedelta(days=1), END
    history = [
        (d1, {"price_deceleration": 0.6, "supply_response_z": 0.0, "tightness_z": -1.5}),
        (d2, {"price_deceleration": 0.6, "supply_response_z": 0.0, "tightness_z": None}),
        (d3, {"price_deceleration": 0.6, "supply_response_z": 2.0, "tightness_z": -1.5}),
    ]
    status = {f.signal: f for f in evaluate_falsifiers(_layer(), history)}
    assert status["price_deceleration"].tripped and status["price_deceleration"].since == d1
    assert status["supply_response_z"].tripped and status["supply_response_z"].since == d3
    assert status["supply_response_z"].observed == 2.0
    assert not status["tightness_z"].tripped  # the missing middle day breaks the run of three
    assert (
        status["tightness_z"].state == "holding"
        and "tripped since" in status["supply_response_z"].state
    )
    only_today = evaluate_falsifiers(_layer(), history[-1:])
    assert [f.tripped for f in only_today] == [False, True, False]  # decel needs two snapshots
    assert evaluate_falsifiers(_layer(), []) and all(
        not f.tripped for f in evaluate_falsifiers(_layer(), [])
    )


def test_tripped_falsifier_halves_the_score_and_sets_the_flags(config: AppConfig) -> None:
    cfg = config.bottleneck
    tripped = evaluate_falsifiers(
        _layer(), [(END, {"supply_response_z": 2.0, "price_deceleration": 0.0, "tightness_z": 1.0})]
    )
    assert apply_thesis(80.0, tripped, cfg) == (40.0, True)
    holding = evaluate_falsifiers(
        _layer(), [(END, {"supply_response_z": 0.0, "price_deceleration": 0.0, "tightness_z": 1.0})]
    )
    assert apply_thesis(80.0, holding, cfg) == (80.0, False)
    comps = {"price_trend": 0.5, "price_deceleration": 0.0, "supply_response_z": 2.0}
    flags = company_flags(72.0, comps, tripped, cfg)
    assert flags == [FLAG_SUPPORT, FLAG_EASING, FLAG_WEAKENING]
    assert company_flags(72.0, comps, holding, cfg) == [FLAG_SUPPORT, FLAG_EASING]  # 4A.8 threshold
    calm = {"price_trend": 0.5, "price_deceleration": 0.1, "supply_response_z": 0.0}
    assert company_flags(30.0, calm, holding, cfg) == []
    assert company_flags(30.0, {**calm, "price_deceleration": 0.6}, holding, cfg) == [FLAG_EASING]
