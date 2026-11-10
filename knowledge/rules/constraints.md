---
id: rules-3-2-constraints
title: 'Rule 3.2: Portfolio risk constraints (all configurable)'
source: PRD.md section 3.2 and config/risk_profiles.yaml
url: PRD.md#32-portfolio-risk-constraints-all-configurable
kind: rules
level: intermediate
as_of: '2026-11-10'
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

**When the ranking and the limits disagree (decided 2026-11-09, W6).** The loss cap is a dollar
amount per contract, so on a small account it selects by share price: the best-ranked names can
fail to fit while a low-ranked one does. The sizer does not hide this:
- Every candidate that cannot fit one contract is listed with the smallest account (value equal
  to buying power) at which it would, and the report prints that "fits from" figure.
- **Too small for this universe.** If no candidate on the best five distinct underlyings in the
  ranking fits (`reporting.top_tickers`, counted by ticker so that many strikes of one name do
  not crowd out the rest), nothing is sized. The report says the account is too small and gives
  the account size at which the top-ranked candidate fits. Lower-ranked leftovers are not
  presented as the screen's answer (`reporting.require_top_ranked`).
- Otherwise the portfolio is sized and labelled: a **one-stock portfolio** warning when every
  position is on one underlying, a **ranking not followed** warning naming the higher-ranked
  underlyings that did not fit, and a **low deployment** warning when less than half of the
  requested strategy buckets is used (`reporting.low_deployment_pct`).
- The narrative must state each of these (Compliance check 4); "all constraints pass" alone is
  not an acceptable summary of such a portfolio.

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
