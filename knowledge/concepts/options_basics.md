---
id: options-basics
title: "Options basics: calls, puts, strike, expiry and exercise style"
source: "OCC, Characteristics and Risks of Standardized Options (the options disclosure document), chapters II and III"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: beginner
as_of: 2026-11-03
---

# Options basics: calls, puts, strike, expiry and exercise style

An **option** is a contract between two parties about a future transaction in an underlying asset. For the listed equity options this app screens, the underlying is 100 shares of a stock or an exchange-traded fund (ETF), the contracts are standardised by the exchanges, and the Options Clearing Corporation (OCC) stands between every buyer and seller as the issuer and guarantor of the contract.

## The two contract types

A **call** gives its holder the right, but not the obligation, to **buy** the underlying at a fixed price. A **put** gives its holder the right to **sell** the underlying at a fixed price. The person on the other side, the **writer** or seller of the option, takes on the matching obligation: a call writer must deliver shares if the holder exercises, a put writer is obliged to take the shares if the holder exercises. The holder pays the writer a **premium** for taking on that obligation, and that premium is the writer's to keep whatever happens next.

## The terms every contract carries

- **Strike price** (exercise price): the fixed price at which the holder may buy (call) or sell (put) the shares.
- **Expiration date**: the last day the option can be exercised. Standard monthly contracts expire on the third Friday; many liquid underlyings also list weekly expiries. The number of calendar days until that date is written **DTE**, days to expiration.
- **Contract multiplier**: 100 shares per contract for standard equity options, so a quoted premium of $1.50 is $150 per contract.
- **Exercise style**: U.S.-listed equity and ETF options are **American style**, exercisable on any trading day up to and including expiration. Most index options are European style and can only be exercised at expiration. The screeners in this app only look at American-style equity and ETF options, which is why early assignment is a real possibility for every short position they produce.

## Moneyness

A call is **in the money (ITM)** when the stock trades above the strike and **out of the money (OTM)** when it trades below; a put is ITM when the stock trades below the strike and OTM above it. **At the money (ATM)** means the strike is at or very near the current stock price. The part of an option's price that would be realised by exercising it immediately is **intrinsic value**; the rest is **extrinsic value**, also called time value.

## Opening and closing

Every position is opened with a "to open" order and closed with a "to close" order. **Sell to open** creates a short option, which is what a cash-secured put writer does. **Buy to open** creates a long option, which is what a LEAPS buyer does. A position can be closed before expiration by trading the opposite side, by exercise or assignment, or by letting the option expire worthless.

## How this app uses these terms

The screening report lists candidates by strategy, strike, expiry and DTE, and uses the words above exactly as the OCC disclosure document defines them. Every number next to a candidate (premium, delta, probability of expiring OTM, collateral, margin requirement) is computed by tested Python code from quoted bid and ask prices; the explanation text may describe those numbers but may not invent new ones.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter II (Options Nomenclature) and chapter III (Options on Equity Securities): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
