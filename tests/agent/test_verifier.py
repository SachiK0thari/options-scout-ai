from __future__ import annotations

from options_scout.agent.verifier import (
    collect_payload_numbers,
    extract_narrative_numbers,
    verify_narrative,
)

DISC = "Educational screening tool. Not investment, tax or legal advice."
PAYLOAD = {
    "profile": {"buying_power": 50000.0, "risk_profile": "balanced"},
    "allocation": {"csp_pct": 0.45, "csp_dollars": 22500.0},
    "positions": [
        {"candidate_id": "CSP-NKE-2026-11-20-35P", "contracts": 2, "strike": 35.0, "mid": 0.56}
    ],
    "risk": {"stress": [{"shock": -0.1, "pnl": -616.4}, {"shock": -0.3, "pnl": -2321.0}]},
    "disclaimer": DISC,
}


def test_grounded_narrative_passes() -> None:
    text = (
        "With $50,000 of buying power, 45% ($22,500) goes to CSP collateral. "
        "CSP-NKE-2026-11-20-35P: 2 contracts at strike 35 for 0.56. A -10% move gives -616; "
        "a -30% move gives -2,321. Expires 2026-11-20. " + DISC
    )
    res = verify_narrative(text, PAYLOAD, disclaimer=DISC)
    assert res.passed, res
    assert res.ungrounded_numbers == []
    assert res.cited_candidate_ids == ["CSP-NKE-2026-11-20-35P"]
    assert res.numbers_checked >= 7


def test_invented_number_fails() -> None:
    text = "Expected annual return of 23.7% on $50,000. " + DISC
    res = verify_narrative(text, PAYLOAD, disclaimer=DISC)
    assert not res.passed and res.ungrounded_numbers == ["23.7%"]


def test_banned_phrase_and_missing_disclaimer_fail() -> None:
    res = verify_narrative(
        "This is a guaranteed, risk-free setup. You should buy.", PAYLOAD, disclaimer=DISC
    )
    assert not res.passed
    assert "guaranteed" in res.banned_phrases_found and "risk-free" in res.banned_phrases_found
    assert not res.disclaimer_present


def test_ids_dates_years_are_not_claims() -> None:
    nums = extract_narrative_numbers(
        "CSP-NKE-2026-11-20-35P expires 2026-11-20, in 2026, the 57th percentile"
    )
    assert nums == []


def test_payload_numbers_include_percent_variants() -> None:
    allowed = collect_payload_numbers({"x": 0.4536})
    assert 45.36 in allowed and 45.4 in allowed and 0.45 in allowed
