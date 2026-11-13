---
id: rules-3-10-holdings-concentration
title: 'Rule 3.10: Holdings and concentration after assignment (seventh constraint)'
source: PRD.md section 3.10 and config/risk_profiles.yaml, config/holdings.yaml
url: PRD.md#310-holdings-and-concentration-after-assignment-seventh-constraint
kind: rules
level: intermediate
as_of: '2026-11-13'
---

# Rule 3.10 Holdings and concentration after assignment (seventh constraint)

This document is generated from PRD.md section 3.10 and `config/risk_profiles.yaml`, `config/holdings.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.10)

Logic in `core/holdings.py`, `core/sizing.py` and `core/risk.py`; the cap is in `config/risk_profiles.yaml` and the analysis parameters in `config/holdings.yaml`. The constraint applies only when the user has entered holdings.

| Constraint | conservative | balanced | aggressive |
|---|---|---|---|
| Max ticker concentration after assignment: (market value already held + strike × 100 × contracts of every sized put on the ticker) / (holdings value + buying power) | 25% | 30% | 40% |

- **Sizing:** the contracts of a cash-secured put are capped so that assignment cannot push its ticker above the cap. The collateral is cash inside the base, so the base does not grow on assignment. When this cap is the binding one, the reason recorded is "concentration after assignment". LEAPS and PMCC short calls are not affected.
- **Risk report:** the check `ticker_concentration_after_assignment` reports the heaviest ticker among those with a sized put. A ticker the user already holds above the cap is a **warning**, not a failed check, and no put on it is sized.
- **Holdings analysis:** lots of the same ticker are merged and each position is valued at the run's price (a ticker without a price is left out and noted). Weights are computed per position and per sector (`Unknown` when no sector is configured). HHI = the sum of squared weights, effective positions = 1 / HHI, diversification score = 100 × (1 − HHI). The weighted expense ratio covers the ETFs held. Beta is the slope of daily log returns on the index's, and the beta-weighted exposure is the sum of weight × beta over the positions with a beta. A position is covered-call eligible when it holds at least one full lot of shares.

## Values in force (config/risk_profiles.yaml, config/holdings.yaml)

| Constraint | conservative | balanced | aggressive |
|---|---|---|---|
| Max ticker concentration after assignment | 25% | 30% | 40% |

The cap is measured against holdings value plus buying power and applies only when holdings were entered.

Covered-call lot: 100 shares. Beta: daily log returns over 252 trading days against SPY, joined on date and needing at least 60 shared returns, reported with its 95% range. The beta-weighted exposure is one regression of the portfolio's weighted daily returns on the index, with its own range.

### Expense ratios used for the weighted expense ratio

| ETF | Annual expense ratio |
|---|---|
| DIA | 0.16% |
| IVV | 0.03% |
| IWM | 0.19% |
| QQQ | 0.18% |
| SPY | 0.0945% |
| VOO | 0.03% |
| VTI | 0.03% |

A stock has no expense ratio; an ETF outside this table is reported without one.
