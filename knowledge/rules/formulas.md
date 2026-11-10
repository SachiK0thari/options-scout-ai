---
id: rules-3-6-formulas
title: 'Rule 3.6: Formulas (implement exactly, test with golden values)'
source: PRD.md section 3.6 and config/settings.yaml
url: PRD.md#36-formulas-implement-exactly-test-with-golden-values
kind: rules
level: intermediate
as_of: '2026-11-09'
---

# Rule 3.6 Formulas (implement exactly, test with golden values)

This document is generated from PRD.md section 3.6 and `config/settings.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.6)

Notation: S spot, K strike, T years to expiry, r risk-free rate, q dividend yield, σ implied vol, N() standard normal CDF.

- `d1 = (ln(S/K) + (r − q + σ²/2)T) / (σ√T)`, `d2 = d1 − σ√T`
- Call delta = `e^(−qT) N(d1)`; Put delta = `e^(−qT) (N(d1) − 1)`
- Gamma, theta, vega: standard Black-Scholes-Merton with continuous dividend yield.
- Probability put expires OTM ≈ `N(d2)`; call expires OTM ≈ `N(−d2)`.
- Mid = `(bid + ask) / 2`; Spread % = `(ask − bid) / mid`.
- **CSP collateral (cash)** = `(K − premium) × 100`
- **CSP annualized return on collateral** = `premium / (K − premium) × 365 / DTE`
- **Reg T naked put margin** (exchange minimum; brokers may require more) = `(premium + max(0.20 × S − OTM, 0.10 × K)) × 100`, where `OTM = max(S − K, 0)`
- **Return on margin** = `premium × 100 / margin_requirement`
- **LEAPS intrinsic** = `max(S − K, 0)`; **extrinsic** = `price − intrinsic`
- **Extrinsic per year %** = `(extrinsic / S) / (DTE / 365)`
- **LEAPS breakeven at expiry** = `K + price`
- **Dollar delta** = `delta × 100 × S × contracts` (short put delta is positive dollar exposure for the seller: use `−put_delta`)
- **IV rank** = `(IV_now − IV_min_52w) / (IV_max_52w − IV_min_52w)`; **IV percentile** = share of days with IV below today.
  - Free data has no IV history, so the app **stores a daily ATM IV snapshot** per watchlist ticker (scheduled job). Until 30+ snapshots exist, fall back to `IV_now / HV30` and mark the field `iv_rank_source="hv_proxy"`.

Golden-value tests: use at least these, verified with an independent calculator and recorded in `tests/fixtures/golden_greeks.json`:
- S=100, K=100, T=1, r=0.05, q=0, σ=0.20 → call delta ≈ 0.6368, put delta ≈ −0.3632
- Margin example: S=100, K=90, premium=1.50 → OTM=10, max(20−10, 9)=10 → requirement = (1.50 + 10) × 100 = **$1,150**
- CSP example: K=90, premium=1.50, DTE=40 → annualized ≈ 1.50/88.50 × 365/40 ≈ **15.47%**
- LEAPS example: S=100, K=70, price=33 → intrinsic 30, extrinsic 3, breakeven 103

## Values in force (config/settings.yaml)

Stress test shocks applied to every sized portfolio: -10%, -20%, -30% on the underlying with implied volatility raised by 50% on down moves. The vol shock applies in full to legs of 30 days or fewer to expiry and shrinks as the square root of 30 / DTE for longer-dated legs, since long-dated vol moves less in a selloff. Each leg is priced before and after with the same model, so the P&L is model-after minus model-before.

The compliance check matches every number in a narrative against the computed payload with a relative tolerance of 0.01.
