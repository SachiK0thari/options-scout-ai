---
id: exit-rules-and-profit-taking
title: "Exit rules and profit taking: closing a short put at half its premium, rolling, and what the app leaves to the user"
source: "OCC, Characteristics and Risks of Standardized Options, chapter X; Cboe Options Institute; PRD.md section on scope"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: intermediate
as_of: 2026-11-04
---

# Exit rules and profit taking

A short put can end in four ways: it expires worthless, it is assigned, the writer buys it back, or the writer rolls it to a later expiration. The first two happen to the writer; the last two are decisions. This document describes the rules option sellers commonly use and why this app does not apply them.

## Closing at half of maximum profit

The most widely quoted rule among systematic put sellers is to buy the put back once it can be repurchased for half of what it was sold for. Suppose a $50 put is sold for $1.20 with 40 days to expiration. If the stock drifts up and two weeks later the put is quoted at $0.55 by $0.60, the writer can buy it to close at $0.60, keeping $0.60 of the original $1.20, 50% of the maximum profit, in 14 of the 40 days. The collateral is released for a new put.

## Why half, and the asymmetry of time decay

The logic rests on an asymmetry. The reward remaining in a short put is the premium still to be collected; the risk remaining is the full distance from the strike to zero. After half the premium has been earned, the writer is holding the same downside for half the reward. Time decay (theta) is fastest for at-the-money options in the last few weeks, but an out-of-the-money put loses most of its extrinsic value earlier; the last few cents decay slowly while gamma, the sensitivity of delta to the stock, rises sharply near expiry. Holding a put from 60 cents to zero means waiting weeks for $60 per contract while exposed to a late drop that could cost thousands. Many writers pair the 50% rule with a time rule, closing any put with fewer than about 21 days left.

## Rolling versus closing

**Rolling** means closing the current put and opening another on the same stock at a later expiration, often at a lower strike, in a single order. A roll for a **credit** collects more for the new put than it costs to close the old; a roll for a **debit** pays the difference. Rolling is sometimes described as a way to avoid a loss, which it is not: the loss on the old put is realised at the roll, and the new position must earn it back. Rolling buys time for the stock to recover and lowers the assignment strike, at the cost of tying up collateral longer. Closing outright ends the position. Both depend on a market existing; a roll on a stock that has gapped down may be available only at a wide spread.

## What can go wrong

The 50% rule is a convention, not a result; it caps each trade's gain while leaving its loss uncapped, and a sequence of early exits produces many small gains that one unmanaged loss can erase. Rolling repeatedly down a falling stock can chase the price for months. And every exit is a trade with its own bid-ask spread, so a put sold for $1.20 and closed at $0.60 has given up spread twice.

## Why the app shows entries, not exits

This app's job ends when a candidate is ranked, sized and explained. Managing an open position needs facts the app does not hold: the fill actually received, the current quote on the exact contract, the account's other positions and the holder's intent, and the app never connects to a brokerage. The product requirements list a "management mode" that would flag positions at 50% profit or under 21 DTE as a possible future feature; it is not part of the current app, and the Compliance agent's language policy means that even then the app would report a state, never say "close" or "roll".

## Where this shows up in OptionsScout

The Candidates tab shows puts to open with their premium at the mid, from which a reader can compute the 50% level themselves. The *Rolling* document in Learn covers the LEAPS roll warning at 240 DTE, the one time-based flag the app raises. The Scout chat answers questions about exit rules as education and does not evaluate a user's open position.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter X (closing transactions and the risk that no market exists): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute, position management and rolling education: https://www.cboe.com/education/
- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
