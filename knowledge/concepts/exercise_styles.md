---
id: exercise-styles
title: "Exercise styles: American and European options and what they mean for a short put"
source: "OCC, Characteristics and Risks of Standardized Options, chapters II, III and IV (exercise style, equity options, index options)"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: intermediate
as_of: 2026-11-04
---

# Exercise styles: American and European options and what they mean for a short put

An option's **exercise style** says when its holder may exercise it. An **American-style** option can be exercised on any trading day up to and including expiration. A **European-style** option can be exercised only at expiration. The names are historical; both styles trade on U.S. exchanges. For an option writer the distinction decides one thing: whether assignment can arrive before expiration.

## Which contracts are which

- **Equity and ETF options** listed in the United States, including every contract this app screens, are American style. They are **physically settled**: exercise of a put means the writer buys 100 shares per contract at the strike; exercise of a call means delivering 100 shares.
- **Most broad-based index options**, such as options on the S&P 500 index (SPX), are European style and **cash settled**: at expiration the holder of an in-the-money option receives the difference between the settlement value and the strike in cash, and no shares change hands. A few index products are American style, so the contract specifications, not the word "index", are what count.

## Why early exercise is rare but real

Exercising an American option early throws away its remaining **extrinsic value**, the part of the price above intrinsic value, so a holder is usually better off selling the option than exercising it. Early exercise therefore happens when extrinsic value has nearly vanished. For a put, that is a deep in-the-money contract near expiration; for a call it is usually the day before an ex-dividend date, when the dividend exceeds the remaining extrinsic value. Suppose a $50 put is sold for $1.20 with 40 days to expiration and the stock falls to $40 two weeks later. The put is worth about $10, almost all of it intrinsic, and its holder can exercise at any time.

## Implications for a short put

A cash-secured put writer in equity options can be assigned on any trading day the put is in the money. Assignment before expiration is uncommon while meaningful extrinsic value remains, which the 0.15-0.30 delta and 30-45 DTE rules are designed to produce at entry; the exposure grows as the stock falls and expiration approaches. Assignment happens after the close: the writer learns the next morning that 100 shares per contract have been bought at the strike, and the cash held as collateral has been spent. At expiration, the OCC automatically exercises any equity option that is at least $0.01 in the money unless the holder instructs otherwise, so a put that closes one cent below the strike on expiration Friday will be assigned.

A European-style cash-settled put would have neither early assignment nor a share position. This app does not screen index options, because its thesis is to end up owning good companies when assigned, and cash settlement cannot deliver that.

## What can go wrong

Writers sometimes assume a put cannot be assigned until expiration and are surprised by an early assignment after a sharp drop, with the shares then falling further before they notice. A writer who holds a short put through expiration with the stock near the strike faces **pin risk**: whether assignment happens depends on the closing price and on holders' instructions, and the result is not known until the weekend.

## Where this shows up in OptionsScout

Every contract in the Candidates tab is an American-style, physically settled equity or ETF option, and the Learn tab's *Assignment* and *Early assignment and dividends* documents build on that fact. The CSP screener's `exclude_earnings_before_expiry` rule and its delta band reduce, but cannot remove, the chance of early assignment; the Portfolio & Risk tab's realistic-loss figure treats assignment at a 30% lower price as the outcome to plan for.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter II (Options Nomenclature), chapter III (Options on Equity Securities) and chapter IV (Index Options): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute, exercise and assignment education: https://www.cboe.com/education/
- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
