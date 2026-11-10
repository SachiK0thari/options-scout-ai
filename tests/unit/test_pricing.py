"""Golden-value and property tests for core/pricing.py. Written before the implementation."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from options_scout.core import pricing

GOLDEN = json.loads((Path(__file__).parents[1] / "fixtures" / "golden_greeks.json").read_text())


@pytest.mark.parametrize("case", GOLDEN["greeks"], ids=lambda c: f"{c['kind']}-S{c['S']}-K{c['K']}")
def test_bsm_greeks_match_golden(case: dict[str, object]) -> None:
    exp = case["expected"]
    assert isinstance(exp, dict)
    g = pricing.bsm_greeks(
        S=float(case["S"]),  # type: ignore[arg-type]
        K=float(case["K"]),  # type: ignore[arg-type]
        T=float(case["T"]),  # type: ignore[arg-type]
        r=float(case["r"]),  # type: ignore[arg-type]
        q=float(case["q"]),  # type: ignore[arg-type]
        sigma=float(case["sigma"]),  # type: ignore[arg-type]
        kind=case["kind"],  # type: ignore[arg-type]
    )
    assert g.price == pytest.approx(exp["price"], abs=1e-3)
    assert g.delta == pytest.approx(exp["delta"], abs=1e-4)
    assert g.gamma == pytest.approx(exp["gamma"], abs=1e-4)
    assert g.theta == pytest.approx(exp["theta"], abs=1e-3)
    assert g.vega == pytest.approx(exp["vega"], abs=1e-3)
    kind = case["kind"]
    assert pricing.prob_otm(
        S=float(case["S"]),  # type: ignore[arg-type]
        K=float(case["K"]),  # type: ignore[arg-type]
        T=float(case["T"]),  # type: ignore[arg-type]
        r=float(case["r"]),  # type: ignore[arg-type]
        q=float(case["q"]),  # type: ignore[arg-type]
        sigma=float(case["sigma"]),  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
    ) == pytest.approx(exp["prob_otm"], abs=1e-4)


def test_spec_golden_deltas() -> None:
    """Section 3.6: S=100, K=100, T=1, r=0.05, q=0, sigma=0.20."""
    call = pricing.bsm_greeks(100, 100, 1, 0.05, 0, 0.20, "call")
    put = pricing.bsm_greeks(100, 100, 1, 0.05, 0, 0.20, "put")
    assert call.delta == pytest.approx(0.6368, abs=5e-5)
    assert put.delta == pytest.approx(-0.3632, abs=5e-5)


def test_expired_option_is_intrinsic() -> None:
    assert pricing.bsm_price(110, 100, 0.0, 0.05, 0.0, 0.2, "call") == pytest.approx(10.0)
    assert pricing.bsm_price(90, 100, 0.0, 0.05, 0.0, 0.2, "put") == pytest.approx(10.0)
    g = pricing.bsm_greeks(110, 100, 0.0, 0.05, 0.0, 0.2, "call")
    assert g.delta == 1.0 and g.gamma == 0.0 and g.vega == 0.0


def test_mid_and_spread() -> None:
    assert pricing.mid_price(1.0, 1.2) == pytest.approx(1.1)
    assert pricing.spread_pct(1.0, 1.2) == pytest.approx(0.2 / 1.1)
    assert pricing.spread_pct(0.0, 0.0) == math.inf


def test_implied_vol_round_trip() -> None:
    target = 0.37
    price = pricing.bsm_price(120, 110, 0.4, 0.04, 0.01, target, "put")
    assert pricing.implied_vol(price, 120, 110, 0.4, 0.04, 0.01, "put") == pytest.approx(
        target, abs=1e-5
    )


def test_implied_vol_below_intrinsic_returns_none() -> None:
    assert pricing.implied_vol(5.0, 120, 110, 0.4, 0.04, 0.0, "call") is None
    # a guess never rescues a price outside the no-arbitrage band
    assert pricing.implied_vol(5.0, 120, 110, 0.4, 0.04, 0.0, "call", guess=0.3) is None


_S = st.floats(min_value=5, max_value=1000)
_K = st.floats(min_value=5, max_value=1000)
_T = st.floats(min_value=0.01, max_value=3)
_r = st.floats(min_value=0.0, max_value=0.10)
_q = st.floats(min_value=0.0, max_value=0.06)
_sig = st.floats(min_value=0.05, max_value=1.5)


def test_implied_vol_seeded_newton_matches_bisection_with_fewer_evaluations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The screeners seed the solver with the provider's vol (W1 follow-up). Seeded or not,
    the answer is the same; seeded, it needs a fraction of the price evaluations."""
    target = 0.345
    S, K, T, r, q = 255.0, 250.0, 780 / 365, 0.04, 0.005  # the AAPL LEAPS from the W1 table
    price = pricing.bsm_price(S, K, T, r, q, target, "call")
    calls: list[int] = [0]
    real_price, real_greeks = pricing.bsm_price, pricing.bsm_greeks

    def counting_price(*args: object, **kwargs: object) -> float:
        calls[0] += 1
        return real_price(*args, **kwargs)  # type: ignore[arg-type]

    def counting_greeks(*args: object, **kwargs: object) -> pricing.Greeks:
        calls[0] += 1
        return real_greeks(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pricing, "bsm_price", counting_price)
    monkeypatch.setattr(pricing, "bsm_greeks", counting_greeks)
    plain = pricing.implied_vol(price, S, K, T, r, q, "call")
    plain_calls = calls[0]
    calls[0] = 0
    seeded = pricing.implied_vol(price, S, K, T, r, q, "call", guess=0.449)  # provider said 0.449
    seeded_calls = calls[0]
    assert plain == pytest.approx(target, abs=1e-6)
    assert seeded == pytest.approx(target, abs=1e-6)
    assert seeded_calls < plain_calls / 3, (seeded_calls, plain_calls)


@pytest.mark.parametrize("guess", [1e-4, 0.01, 0.3, 2.0, 4.99, 7.0, -1.0, float("nan")])
def test_implied_vol_any_guess_gives_the_same_answer(guess: float) -> None:
    """A poor, out-of-range or non-finite guess falls back to bisection and still converges."""
    target = 0.62
    price = pricing.bsm_price(80.0, 95.0, 0.15, 0.03, 0.0, target, "put")
    assert pricing.implied_vol(price, 80.0, 95.0, 0.15, 0.03, 0.0, "put", guess=guess) == (
        pytest.approx(target, abs=1e-6)
    )


@settings(max_examples=200, deadline=None)
@given(S=_S, K=_K, T=_T, r=_r, q=_q, sigma=_sig, guess=_sig)
def test_implied_vol_round_trip_property(
    S: float, K: float, T: float, r: float, q: float, sigma: float, guess: float
) -> None:
    for kind in ("call", "put"):
        price = pricing.bsm_price(S, K, T, r, q, sigma, kind)  # type: ignore[arg-type]
        got = pricing.implied_vol(price, S, K, T, r, q, kind, guess=guess)  # type: ignore[arg-type]
        if got is None:
            continue  # a far-OTM price that rounds to the floor has no unique vol
        back = pricing.bsm_price(S, K, T, r, q, got, kind)  # type: ignore[arg-type]
        assert back == pytest.approx(price, abs=1e-6 * max(1.0, price))


@settings(max_examples=300, deadline=None)
@given(S=_S, K=_K, T=_T, r=_r, q=_q, sigma=_sig)
def test_put_call_parity(S: float, K: float, T: float, r: float, q: float, sigma: float) -> None:
    c = pricing.bsm_price(S, K, T, r, q, sigma, "call")
    p = pricing.bsm_price(S, K, T, r, q, sigma, "put")
    lhs = c - p
    rhs = S * math.exp(-q * T) - K * math.exp(-r * T)
    assert lhs == pytest.approx(rhs, abs=1e-6 * max(1.0, S, K))


@settings(max_examples=300, deadline=None)
@given(S=_S, K=_K, T=_T, r=_r, q=_q, sigma=_sig)
def test_delta_bounds_and_sign(
    S: float, K: float, T: float, r: float, q: float, sigma: float
) -> None:
    call = pricing.bsm_greeks(S, K, T, r, q, sigma, "call")
    put = pricing.bsm_greeks(S, K, T, r, q, sigma, "put")
    assert 0.0 <= call.delta <= 1.0
    assert -1.0 <= put.delta <= 0.0
    assert call.delta - put.delta == pytest.approx(math.exp(-q * T), abs=1e-9)
    assert call.gamma >= 0 and put.gamma >= 0
    assert call.vega >= 0 and put.vega >= 0
    assert 0.0 <= pricing.prob_otm(S, K, T, r, q, sigma, "put") <= 1.0
