---
id: reg-t-margin
title: "Regulation T and the margin requirement for an uncovered short put"
source: "Federal Reserve Regulation T, 12 CFR Part 220; FINRA Rule 4210(f)(2)(D)"
url: https://www.ecfr.gov/current/title-12/chapter-II/subchapter-A/part-220
kind: concepts
level: advanced
as_of: 2026-11-03
---

# Regulation T and the uncovered put margin requirement

**Regulation T** is the Federal Reserve Board rule, codified at 12 CFR Part 220, that governs how much credit a broker-dealer may extend to a customer for buying and carrying securities. It establishes the margin account, sets the initial margin for stock purchases at 50% of the purchase price, and requires that option transactions be margined under the rules of the exchange on which the option trades. Those exchange rules, harmonised in **FINRA Rule 4210**, set the minimum collateral a broker must collect from the writer of an uncovered (naked) option.

## The formula for an uncovered equity put

Under Rule 4210(f)(2)(D), the minimum requirement for a short equity put is the premium received plus the **greater** of:

1. 20% of the current price of the underlying stock, minus the amount by which the put is out of the money (the stock price minus the strike, when positive), or
2. 10% of the strike price (the "minimum" leg),

all multiplied by 100 shares per contract. In this app's notation: requirement = (premium + max(0.20 × S − OTM, 0.10 × K)) × 100 with OTM = max(S − K, 0).

Worked example from the repository's golden test: a stock at $100, a $90 put sold for $1.50. The put is $10 out of the money, so leg 1 is $20 − $10 = $10 and leg 2 is $9; the greater is $10, and the requirement is ($1.50 + $10) × 100 = **$1,150**. Had the stock been at $92 instead, leg 1 would be $18.40 − $2 = $16.40 and the requirement $1,790; the requirement rises as the stock falls toward and through the strike, which is the mechanism behind margin calls on short puts in a sell-off.

## Why "exchange minimum" is written next to every margin number

The figure above is the floor set by regulation. Brokers almost always require more, through **house requirements** that may be a higher percentage, a higher minimum leg, concentration add-ons for large positions in one name, or outright higher requirements for volatile stocks. House requirements change without notice, often in the middle of a market decline. Portfolio-margin accounts use a different, risk-based system that can require less for hedged books and more for concentrated ones. This app computes the Reg T / Rule 4210 minimum because it is the only number that can be derived from public rules; the report labels it as the exchange minimum and states that brokers can raise it.

## How the requirement feeds the sizing engine

For margin accounts the sizing engine treats the requirement as the buying power consumed by each short put and applies a per-profile cap on total margin usage (30% conservative, 40% balanced, 50% aggressive) as well as caps on total short-put notional and dollar delta. **Return on margin**, premium × 100 divided by the requirement, is reported alongside the return on full cash collateral so the leverage is explicit. For cash accounts none of this applies: the full strike value, less premium, is reserved and the margin constraints are skipped.

## Reg T and the assigned shares

When a short put is assigned, the account buys 100 shares at the strike and the position becomes an ordinary long stock holding. Regulation T's 50% initial margin and the broker's maintenance margin now apply to those shares, which can require more equity than the option requirement did. Writers who sized positions to the option requirement alone can therefore face a margin call on the morning after assignment.

## Sources

- Federal Reserve Board, Regulation T, Credit by Brokers and Dealers, 12 CFR Part 220: https://www.ecfr.gov/current/title-12/chapter-II/subchapter-A/part-220
- FINRA Rule 4210, Margin Requirements: https://www.finra.org/rules-guidance/rulebooks/finra-rules/4210
- FINRA, "Understanding Margin Accounts" for investors: https://www.finra.org/investors/investing/investment-accounts/margin-accounts
