---
id: fire-and-safe-withdrawal
title: "FIRE and safe withdrawal rates: the 4% rule, its five variants, and why it does not transfer to options income"
source: "Bogleheads wiki, Safe withdrawal rates; Bogleheads wiki, Trinity study; Bengen (1994), Determining Withdrawal Rates Using Historical Data"
url: https://www.bogleheads.org/wiki/Safe_withdrawal_rates
kind: basics
level: intermediate
as_of: 2026-11-04
---

# FIRE and safe withdrawal rates

**FIRE** stands for Financial Independence, Retire Early. Its central idea is that a person is financially independent when investments can fund expenses indefinitely, and that the balance required is a multiple of annual spending rather than a function of age. The multiple comes from the **safe withdrawal rate** (SWR) research: the percentage of a starting portfolio that could be withdrawn each year, adjusted for inflation, without the portfolio running out over a long retirement.

## The 4% rule: Bengen and the Trinity study

William Bengen's 1994 paper tested U.S. stock and bond returns since 1926 and found that a portfolio of roughly 50% to 75% stocks, the rest in intermediate Treasury bonds, had survived every 30-year period when withdrawals started at 4% of the initial balance and rose with inflation. The **Trinity study** (Cooley, Hubbard and Walz, 1998) reached a similar conclusion using success rates across many starting years and allocations. The Bogleheads wiki pages on safe withdrawal rates and the Trinity study summarise both, including that 4% was the worst-case survivor, not the average outcome. Inverting the rate gives the **FIRE number**: 1 / 0.04 = 25 times annual expenses.

## The five variants

Each variant changes the expense figure that is multiplied, not the rate.

- **Lean FIRE**: independence on a deliberately frugal budget, below current spending.
- **Regular FIRE**: independence on current expenses, so the FIRE number is 25 times what the household spends today.
- **Fat FIRE**: independence on a higher-than-current budget with room for discretionary spending.
- **Coast FIRE**: the balance that would grow, with no further contributions, to the FIRE number by a target age; after reaching it the saver only has to cover current expenses from income.
- **Barista FIRE**: independence on current expenses minus expected part-time income, so a smaller portfolio suffices while some work continues.

Suppose a household spends $48,000 a year and uses a 4% rate. Regular FIRE is $1,200,000; lean at $36,000 of spending is $900,000; fat at $72,000 is $1,800,000; barista with $18,000 of part-time income is $750,000. Coast FIRE at age 35 for a target of 60, assuming a 5% real return, is $1,200,000 divided by 1.05 to the 25th power, about $354,000.

## Why the research does not transfer to options premium income

The 4% figure rests on a diversified portfolio of stocks and bonds, rebalanced, with returns drawn from a century of history. Every part of that description fails for a portfolio whose income is premium from short puts. First, **assignment**: a put writer's return is payment for a conditional purchase, and in a decline the collateral becomes shares of single companies bought above the market. Second, **drawdown**: each cash-secured put's realistic loss is the loss at a 30% fall, several can be assigned in one month, and a 4% withdrawal from what remains is a far larger share. Third, **regime risk**: premium yield depends on implied volatility, highest when the market is falling and lowest when calm, so the income is least reliable when most needed and cannot be inflation-adjusted on schedule. There is no century of data on short-put income, and a yield of, say, 8% on collateral in a screen is an estimate for the next 30 to 45 days that assumes the stocks drift and swing as the app's stated assumptions say, not a withdrawal rate.

## What can go wrong

The 4% rule is a U.S. historical result over 30-year horizons. A 50-year retirement, lower expected returns or a bad first decade can break it, and the Bogleheads pages describe the debate over lower rates for early retirees. A FIRE number is a planning target, not a promise.

## Where this shows up in OptionsScout

The Goals tab's **FIRE card** takes annual expenses, current balance, monthly contribution, a withdrawal rate that defaults to 4% with its source tag, and a variant selector. The Goal Planning agent shows two views side by side and never blends them: the projection to the FIRE number at the profile's assumed diversified return, and an **income-coverage** ratio, the share of the expense target the current screen's expected premium yield (premium less the expected cost of assignment) would cover. The Compliance agent requires the narrative to name the variant, say that the withdrawal rate comes from diversified-portfolio research and not from options income, and give no date without "would" and the assumed return beside it.

## Sources

- Bogleheads wiki, Safe withdrawal rates: https://www.bogleheads.org/wiki/Safe_withdrawal_rates
- Bogleheads wiki, Trinity study: https://www.bogleheads.org/wiki/Trinity_study
- SEC investor.gov, Compound Interest Calculator, for reproducing the Coast FIRE present-value example: https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator
