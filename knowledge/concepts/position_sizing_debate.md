---
id: position-sizing-debate
title: "Position sizing: fixed fraction, the Kelly criterion, and the app's greedy fill under its portfolio constraints"
source: "FINRA, Margin accounts investor page; FINRA Rule 4210; config/risk_profiles.yaml; PRD.md section 3.2"
url: https://www.finra.org/investors/investing/investment-accounts/margin-accounts
kind: concepts
level: advanced
as_of: 2026-11-13
---

# Position sizing: fixed fraction, Kelly, and the app's greedy fill

Choosing which put to sell is half the problem; choosing how many contracts is the half that decides whether a bad month is survivable. Three approaches are compared here.

## Fixed-fraction sizing

The **fixed-fraction** rule risks a set percentage of the account on each position. Suppose a $100,000 account and a 2% rule: a put whose plausible loss is $1,500 per contract can be sold once; one whose plausible loss is $600, three times. The rule is simple and needs no probabilities. Its weakness is that "plausible loss" must be defined, and that ten 2% positions in one sector are a 20% bet on that sector.

## The Kelly criterion

The **Kelly criterion** sizes a bet to maximise the long-run growth rate of capital. For a bet that wins b times the stake with probability p and loses the stake with probability q = 1 - p, the fraction of capital to wager is f* = p - q/b. Suppose a put has a 0.80 probability of expiring worthless and pays $120 against a loss of $1,500 when it does not: b = 0.08, q = 0.20, and f* = 0.80 - 0.20/0.08 = -1.7, a negative number, meaning the bet as described has negative expectation and the rule says to size it at zero. With a $400 loss instead, b = 0.30 and f* = 0.13. Given its inputs the criterion is correct, but betting more than f* lowers growth and raises the chance of ruin, and even at f* the path is very volatile, which is why practitioners use a fraction such as half-Kelly.

## Why the app does not use Kelly

The inputs are the problem. The probability that a put expires out of the money is read from a pricing model and is wrong by several points in exactly the markets where sizing matters most; the loss if assigned is a distribution with a fat left tail, not a number. Moving p from 0.80 to 0.75 and the loss from $400 to $600 takes f* from 13% to under zero. A rule whose output swings from 13% of the account to zero on estimation error of that size is not one an automated system should apply to real money.

## What the app does instead: greedy fill under portfolio constraints

The sizing step takes the ranked candidates in order and adds contracts to each until any constraint would be breached, then moves on. The {{risk.constraints_margin}} constraints, per risk profile, are: short-put notional (strike x 100 x contracts) as a multiple of account value; margin usage, margin accounts only; **realistic loss** per position as a fraction of account value; realistic loss per ticker; realistic loss per sector; the realistic loss of the whole portfolio; the cash needed if every put were assigned, plus LEAPS debits, as a multiple of buying power; and total dollar delta as a multiple of account value. For the conservative profile these are {{risk.conservative.max_short_put_notional_x}}, {{risk.conservative.max_margin_usage}}, {{risk.conservative.max_loss_per_position}}, {{risk.conservative.max_exposure_per_ticker}}, {{risk.conservative.max_per_sector}}, {{risk.conservative.max_portfolio_loss}}, {{risk.conservative.max_assignment_cash_x}} and {{risk.conservative.max_dollar_delta_x}}; for aggressive {{risk.aggressive.max_short_put_notional_x}}, {{risk.aggressive.max_margin_usage}}, {{risk.aggressive.max_loss_per_position}}, {{risk.aggressive.max_exposure_per_ticker}}, {{risk.aggressive.max_per_sector}}, {{risk.aggressive.max_portfolio_loss}}, {{risk.aggressive.max_assignment_cash_x}} and {{risk.aggressive.max_dollar_delta_x}} (`config/risk_profiles.yaml`). With holdings entered, a concentration-after-assignment limit is added.

The **realistic-loss cap** does the work Kelly tries to do, without estimating a probability. Realistic loss is the loss if the stock falls 30% by expiry, a scenario that is severe, has happened to large companies, and is the same for every candidate. Capping it at 2% per position and 5% per ticker says that no single stock's bad year can cost more than a small fixed share of capital, whatever the model thinks the odds are.

## What can go wrong

Greedy fill is not optimal: a top-ranked candidate can consume a sector's whole budget and crowd out better-diversified positions below it; the product requirements note an integer optimisation as a possible improvement. The 30% scenario is a judgment; 2008 and 2020 saw larger drops, and a 30% fall in every name at once is reported separately by the -10/-20/-30% stress test. The constraints cannot see positions held outside the app.

## Where this shows up in OptionsScout

The Portfolio & Risk tab shows the sized positions, the contracts for each, which constraint stopped the fill, totals for notional, margin and dollar delta, and the stress test. The Scout chat explains a size by naming the binding constraint and its value, never by asserting a probability of success.

## Sources

- FINRA, *Margin accounts* investor page: https://www.finra.org/investors/investing/investment-accounts/margin-accounts
- FINRA Rule 4210, Margin Requirements: https://www.finra.org/rules-guidance/rulebook/finra-rules/4210
- Bogleheads wiki (general discussion of risk capacity and diversification): https://www.bogleheads.org/wiki/Main_Page
- This app's rules in force: `config/risk_profiles.yaml` and PRD.md section 3.2.
