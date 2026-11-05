---
id: risk-profiles
title: "Risk profiles in OptionsScout: allocation, constraints and the return a goal may assume"
source: "OptionsScout config/risk_profiles.yaml (PRD sections 3.1 and 3.2); SEC investor.gov, Introduction to Investing"
url: https://www.investor.gov/introduction-investing
kind: basics
level: intermediate
as_of: 2026-11-04
---

# Risk profiles in OptionsScout

A **risk profile** is a named bundle of sizing rules. OptionsScout has three: **conservative**, **balanced** and **aggressive**, as named in `config/risk_profiles.yaml`. Chosen once on the Setup tab, it governs how buying power is split between strategies, how tight the portfolio constraints are, and how large a return the Goal Planning agent will let a goal assume. A profile is a set of limits, not a forecast.

## The allocation split

Each profile divides buying power into three buckets: cash-secured puts (CSP), LEAPS calls and a cash reserve that is never allocated to options.

| Profile | CSP | LEAPS | Cash |
|---|---|---|---|
| Conservative | 50% | 15% | 35% |
| Balanced | 45% | 25% | 30% |
| Aggressive | 45% | 35% | 20% |

Moving from conservative to aggressive shifts money from the reserve into LEAPS, the strategy with the largest possible loss (the whole premium paid). The volatility regime can tilt 10 points between CSP and LEAPS, but never touches the cash reserve.

## The six constraints

The constraints are fractions of account value unless noted, and a candidate that would breach any of them is sized down or dropped. The **realistic loss** of a CSP is the loss if the stock falls 30% at expiry, not the premium at risk.

| Constraint | Conservative | Balanced | Aggressive |
|---|---|---|---|
| Realistic loss per position | 2% | 3% | 5% |
| Realistic loss per ticker | 5% | 8% | 10% |
| Realistic loss per sector | 25% | 30% | 35% |
| Dollar delta / account | 0.8x | 1.0x | 1.5x |

The two remaining constraints are short put notional (strike times 100 times contracts) of at most 1.0x account value for conservative and balanced and 1.5x for aggressive, and, in margin accounts only, margin usage of at most 30%, 40% or 50% of buying power. The 2% to 5% realistic-loss cap is what limits the number of contracts.

## The profile caps the return a goal can assume

The Goal Planning agent computes the constant annual return a goal would require and compares it with the profile's assumed-return cap, a configured ceiling that rises from conservative to aggressive. If the required return exceeds the cap, the verdict is `does_not_fit` and the agent shows three levers: more time, more contribution, or a smaller target. It never raises the assumed return to make the goal fit.

Worked example, with every number an assumption. Suppose a $50,000 account on the conservative profile, a goal of $400 a month of premium income, and a conservative assumed-return cap of 6% a year. The goal requires $4,800 a year, or 9.6% of the account, before any stress adjustment. That exceeds the 6% cap, so the verdict is `does_not_fit` with a gap of 3.6 percentage points. The levers would read: at 6% the account would produce about $250 a month; reaching $400 at 6% would require about $80,000; or a profile with a higher cap, accepting its looser loss limits. The example is arithmetic on stated assumptions, not a statement about the market.

## What can go wrong

A profile limits the loss the engine will *size for*; it does not limit the loss the market can deliver. A stock can fall more than 30%, several names in one sector can fall together, and the dollar-delta constraint assumes past relationships hold. If a user overstates account value, every percentage constraint loosens in proportion. And three profiles cannot represent every household; money with a short horizon should be treated as outside even the conservative profile.

## Where this shows up in OptionsScout

The Setup tab selects the profile; the Portfolio & Risk tab shows the allocation and each constraint with its usage; the Goals tab shows the feasibility card and lever table. The Compliance agent rejects any narrative that omits the profile name or states a return without the word "would" beside it. All thresholds are read from `config/risk_profiles.yaml` and reproduced in the generated *Rule 3.1* and *Rule 3.2* documents.

## Sources

- OptionsScout rule in force: `config/risk_profiles.yaml`, PRD sections 3.1 and 3.2, and the generated documents *Rule 3.1* and *Rule 3.2*.
- SEC investor.gov, Introduction to Investing, on matching an allocation to risk tolerance and horizon: https://www.investor.gov/introduction-investing
- FINRA, Margin accounts investor page, for the margin-usage constraint: https://www.finra.org/investors/investing/investment-accounts/margin-accounts
