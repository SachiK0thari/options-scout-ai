---
id: rules-3-3-csp-screener
title: 'Rule 3.3: CSP screener rules'
source: PRD.md section 3.3 and config/screener_rules.yaml
url: PRD.md#33-csp-screener-rules
kind: rules
level: intermediate
as_of: '2026-11-09'
---

# Rule 3.3 CSP screener rules

This document is generated from PRD.md section 3.3 and `config/screener_rules.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.3)

| Rule | Default |
|---|---|
| DTE | 30–45 days |
| Put delta (absolute) | 0.15–0.30 |
| Open interest | ≥ 500 |
| Bid-ask spread | ≤ 10% of mid |
| Bid | > $0.10 |
| Earnings date | not before expiry (flag, and exclude by default) |
| Underlying price | ≥ $10, avg volume ≥ 1M shares |
| IV rank | prefer ≥ 30 (soft scoring, not hard filter) |

## Values in force (config/screener_rules.yaml)

| Rule | Value in force |
|---|---|
| Days to expiry | 30–45 (fallback 21–60 when the strict window has no liquid candidate, flagged `dte_outside_preferred`) |
| Put delta (absolute) | 0.15–0.3 |
| Open interest | ≥ 500 |
| Bid-ask spread | ≤ 10% of mid |
| Bid | > $0.10 |
| Earnings before expiry | excluded |
| Earnings date unknown (single stocks) | excluded |
| Underlying price | ≥ $10 |
| Average volume | ≥ 1,000,000 shares/day |
| IV rank | prefer ≥ 30% (soft score, not a filter) |
