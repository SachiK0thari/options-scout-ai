---
id: rules-3-4-leaps-screener
title: 'Rule 3.4: LEAPS screener rules'
source: PRD.md section 3.4 and config/screener_rules.yaml
url: PRD.md#34-leaps-screener-rules
kind: rules
level: intermediate
as_of: '2026-11-13'
---

# Rule 3.4 LEAPS screener rules

This document is generated from PRD.md section 3.4 and `config/screener_rules.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.4)

| Rule | Default |
|---|---|
| DTE | ≥ 365 days, prefer the longest available (≥ 540 preferred) |
| Call delta | 0.70–0.85 |
| Extrinsic value per year | ≤ 5% of stock price per year (hard filter) |
| Ranking | by carry per year (3.6), cheapest first; a carry of 5% or more scores 0 on the cost term (`leaps.carry_score_cap`) |
| Open interest | ≥ 100 |
| Bid-ask spread | ≤ 5% of mid |
| IV rank | prefer ≤ 40 (soft scoring) |
| Management note | roll or close guidance below 240 DTE (education: the app does not track held LEAPS, and a screened LEAPS has at least 365 days) |

## Values in force (config/screener_rules.yaml)

| Rule | Value in force |
|---|---|
| Days to expiry | ≥ 365; prefer ≥ 540 |
| Call delta | 0.7–0.85 |
| Extrinsic value per year | ≤ 5% of the stock price |
| Ranking | by carry per year (extrinsic + dividends forgone − interest saved), cheapest first; a carry of 5% or more scores 0 on cost |
| Open interest | ≥ 100 |
| Bid-ask spread | ≤ 5% of mid |
| IV rank | prefer ≤ 40% (soft score; applies only once 30 daily IV snapshots are stored; until then IV/HV is shown and not scored) |
| Roll warning | roll or close guidance below 240 days to expiry (education only: the app does not track held LEAPS, and a screened LEAPS has at least 365 days) |
