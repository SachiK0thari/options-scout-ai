---
id: rules-3-8-goal-feasibility
title: 'Rule 3.8: Goal feasibility (Goal Planning agent)'
source: PRD.md section 3.8 and config/goals.yaml
url: PRD.md#38-goal-feasibility-goal-planning-agent
kind: rules
level: intermediate
as_of: '2026-11-06'
---

# Rule 3.8 Goal feasibility (Goal Planning agent)

This document is generated from PRD.md section 3.8 and `config/goals.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.8)

Logic in `core/goals.py` (pure, golden-tested), assumptions in `config/goals.yaml`. A goal is checked against what the current screen yields under stress and against the risk profile's return cap. Every return here is an assumption printed beside the chart; nothing is a forecast.

1. **Required return.** Income goal: `12 × target monthly income / start balance`. Growth, contribution and FIRE goals: the effective annual return that turns the start balance plus monthly contributions into the target over the horizon (closed form for a lump sum, bisection with contributions; compounding is monthly at the rate equivalent to the annual one). The target of a FIRE goal is the FIRE number, `expense target / withdrawal rate`. A coast goal assumes no further contributions.
2. **Available return** is the **stress-adjusted yield** of the sized portfolio: the capital-weighted annualised premium yield of the short options, with LEAPS counted at 0% income and the cash reserve at the T-bill rate, minus `assignment frequency × realistic loss / total capital` (the −30% scenario amortised at the profile's assumed frequency). Without a screen on the thread the balance is treated as cash at the T-bill rate.
3. **Verdict:**

| Status | Condition |
|---|---|
| `fits` | required return ≤ the lower of the available return and the profile's cap |
| `stretch` | required return ≤ the lower of (available return + stretch band) and the profile's cap |
| `does_not_fit` | anything else: a required return above the profile's cap whatever the screen yields, a goal with no horizon or no starting capital, or a target that needs more than 1,000% a year |

   The gap is the required return minus the available return, in return points.
4. **Levers** are listed together with their numbers and never chosen for the user: `more_capital` (the start balance that reaches the target at the available return; for an income goal `12 × monthly income / available return`), `longer_horizon` (the years to the target at the available return, or "not reached" within the maximum horizon) and `different_profile` (the first profile, conservative to aggressive, whose cap admits the required return, or none).
5. **Projection paths** on one chart: `stress` (the base path less the −30% scenario's realistic loss taken in year one and the growth it forgoes), `base` (the stress-adjusted yield), `best` (the gross yield capped at the profile's maximum) and `assumed` (the profile's diversified-portfolio return, labelled as not options income). The stress path is shown whenever a projection is.
6. **FIRE variants.** Expense target: minimum expenses (`lean`), current expenses (`regular`, `coast`), the entered fat expenses or the fat multiple × current expenses (`fat`), current expenses minus part-time income (`barista`). Years to independence and the coast balance (the present value of the FIRE number at the target age) use the profile's assumed diversified return, never the options yield. Income coverage (`stress-adjusted yield × buying power / expense target`) is shown beside them and never blended: a short-put yield is not a safe withdrawal rate.

## Values in force (config/goals.yaml)

| Assumption | conservative | balanced | aggressive |
|---|---|---|---|
| Return cap a goal may assume (above it the verdict is `does_not_fit`) | 6% | 9% | 12% |
| Diversified-portfolio return assumed for the conventional and FIRE projections | 5% | 6% | 7% |
| Share of years in which the −30% stress scenario is assumed to hit | 10% | 15% | 20% |

Stretch band: a required return up to 2 percentage points above the stress-adjusted yield, and still within the profile's cap, is a `stretch`.

Withdrawal rate: 4% unless the user states one (FIRE number = expense target / withdrawal rate). Fat FIRE expense target when none is entered: 1.5 × current expenses. A target is reported as not reached beyond 100 years.

Savings-rate illustration on the Goals tab: savings rates of 10%, 20%, 30%, 50% at a real return of 5%.
