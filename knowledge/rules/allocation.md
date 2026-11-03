---
id: rules-3-1-allocation
title: 'Rule 3.1: Allocation of buying power'
source: PRD.md section 3.1 and config/risk_profiles.yaml
url: PRD.md#31-allocation-of-buying-power
kind: rules
as_of: '2026-11-03'
---

# Rule 3.1 Allocation of buying power

This document is generated from PRD.md section 3.1 and `config/risk_profiles.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.1)

| Profile | CSP collateral | LEAPS / PMCC | Cash reserve |
|---|---|---|---|
| conservative | 50% | 15% | 35% |
| balanced | 45% | 25% | 30% |
| aggressive | 45% | 35% | 20% |

**Volatility regime tilt** (using VIX 1-year percentile from `^VIX`):
- VIX percentile ≥ 70 (high IV): shift **10 points from LEAPS to CSP** (sell expensive premium, avoid buying expensive LEAPS).
- VIX percentile ≤ 30 (low IV): shift **10 points from CSP to LEAPS** (LEAPS are cheap, put premium is thin).
- Never reduce the cash reserve via tilt.

## Values in force (config/risk_profiles.yaml)

| Profile | CSP collateral | LEAPS / PMCC | Cash reserve |
|---|---|---|---|
| conservative | 50% | 15% | 35% |
| balanced | 45% | 25% | 30% |
| aggressive | 45% | 35% | 20% |

Regime tilt: when the VIX 1-year percentile is at or above 70 the plan moves 10% of the account from LEAPS to CSP; at or below 30 it moves 10% from CSP to LEAPS. The cash reserve is never reduced by the tilt. A strategy bucket the user did not request is held as cash.
