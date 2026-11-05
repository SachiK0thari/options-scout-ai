---
id: rules-3-4-leaps-screener
title: 'Rule 3.4: LEAPS screener rules'
source: PRD.md section 3.4 and config/screener_rules.yaml
url: PRD.md#34-leaps-screener-rules
kind: rules
level: intermediate
as_of: '2026-11-03'
---

# Rule 3.4 LEAPS screener rules

This document is generated from PRD.md section 3.4 and `config/screener_rules.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.4)

| Rule | Default |
|---|---|
| DTE | ≥ 365 days, prefer the longest available (≥ 540 preferred) |
| Call delta | 0.70–0.85 |
| Extrinsic value per year | ≤ 5% of stock price per year (score lower is better) |
| Open interest | ≥ 100 |
| Bid-ask spread | ≤ 5% of mid |
| IV rank | prefer ≤ 40 (soft scoring) |
| Management note | flag "roll or close" when DTE < 240 |

## Values in force (config/screener_rules.yaml)

| Rule | Value in force |
|---|---|
| Days to expiry | ≥ 365; prefer ≥ 540 |
| Call delta | 0.7–0.85 |
| Extrinsic value per year | ≤ 5% of the stock price |
| Open interest | ≥ 100 |
| Bid-ask spread | ≤ 5% of mid |
| IV rank | prefer ≤ 40% (soft score) |
| Roll warning | flag "roll or close" when days to expiry fall below 240 |
