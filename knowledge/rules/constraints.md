---
id: rules-3-2-constraints
title: 'Rule 3.2: Portfolio risk constraints (all configurable)'
source: PRD.md section 3.2 and config/risk_profiles.yaml
url: PRD.md#32-portfolio-risk-constraints-all-configurable
kind: rules
level: intermediate
as_of: '2026-11-03'
---

# Rule 3.2 Portfolio risk constraints (all configurable)

This document is generated from PRD.md section 3.2 and `config/risk_profiles.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.2)

| Constraint | conservative | balanced | aggressive |
|---|---|---|---|
| Max total short-put notional (strike × 100 × contracts) / account value | 1.0x | 1.0x | 1.5x |
| Max margin usage of buying power | 30% | 40% | 50% |
| Max realistic loss per position (% of account) | 2% | 3% | 5% |
| Max exposure per ticker (risk terms) | 5% | 8% | 10% |
| Max per sector | 25% | 30% | 35% |
| Max total dollar delta / account value | 0.8x | 1.0x | 1.5x |

- "Realistic loss" for a CSP = loss if the stock drops 30% at expiry. For a LEAPS = full premium paid.
- Cash accounts: margin constraints do not apply, and CSP collateral = full cash-secured amount.
- Same ticker in a CSP and a PMCC: combined exposure counts against the per-ticker cap.

## Values in force (config/risk_profiles.yaml)

| Constraint | conservative | balanced | aggressive |
|---|---|---|---|
| Max total short-put notional / account value | 1x | 1x | 1.5x |
| Max margin usage of buying power | 30% | 40% | 50% |
| Max realistic loss per position (% of account) | 2% | 3% | 5% |
| Max exposure per ticker (realistic loss) | 5% | 8% | 10% |
| Max per sector (realistic loss) | 25% | 30% | 35% |
| Max total dollar delta / account value | 0.8x | 1x | 1.5x |

Realistic loss for a cash-secured put is the loss if the stock falls 30% by expiry; for a LEAPS call it is the full premium paid. Margin constraints do not apply to cash accounts. A position that would break any constraint is skipped and the reason is recorded on the portfolio.
