---
id: leaps
title: "LEAPS: long-dated call options as a leveraged stand-in for owning shares"
source: "Cboe Options Institute; OCC disclosure document chapter III; PRD.md section 3.4"
url: https://www.cboe.com/education/
kind: concepts
as_of: 2026-11-03
---

# LEAPS calls

**LEAPS** (Long-term Equity AnticiPation Securities) is the exchanges' name for listed options with more than a year until expiration. They trade and settle exactly like shorter options; only the time horizon is different. This app screens **deep in-the-money LEAPS calls** as a way to hold long exposure to a good-to-own stock for a year or more while committing less capital than buying the shares outright.

## Why deep in the money

A call with a delta of 0.70 to 0.85 moves 70–85 cents for every dollar move in the stock and is priced mostly on intrinsic value. Its **extrinsic value**, the part of the premium that decays to zero by expiration, is a small fraction of the stock price. That matters because extrinsic value is the real cost of renting the exposure: the buyer pays it up front and it is gone at expiry no matter what the stock does. A deep in-the-money LEAPS behaves like a stock position with built-in leverage and a defined maximum loss, while an at-the-money or out-of-the-money LEAPS behaves more like a bet on a large move and loses most of its value if the stock merely drifts.

## Payoff at expiration

- Breakeven: strike + premium paid.
- Maximum loss: the full premium, if the stock closes at or below the strike at expiration.
- Gain above breakeven: one for one with the stock, without the dividends a shareholder would have collected.

The risk engine in this app counts the whole premium as the **realistic loss** of a LEAPS position, because a long option can in fact go to zero, and sizes positions so that this loss stays within the per-position limit for the user's risk profile.

## What a LEAPS buyer gives up

Owning a call instead of the shares means no dividends, no voting rights, and a fixed deadline. If the stock pays a dividend, the call's price already reflects that expected payment, which is one reason deep calls on high-dividend names carry little extrinsic value and are candidates for early exercise ahead of the ex-dividend date. The deadline is the larger risk: a correct view on the company that plays out in year three is still a total loss for a two-year option.

## The screener rules in force

This app requires at least 365 days to expiration and prefers the longest available series (540 days or more), a call delta between 0.70 and 0.85, extrinsic value of no more than 5% of the stock price **per year** (so a two-year option may carry up to 10%), open interest of at least 100 contracts and a bid-ask spread of at most 5% of the mid price. An IV rank at or below 40% is preferred because LEAPS are a purchase of volatility: buying them when implied volatility is elevated means paying more extrinsic value for the same exposure. When a held LEAPS falls below 240 days to expiration the report flags it "roll or close", because time decay accelerates as expiration approaches and the position stops behaving like stock.

## Relation to the other strategies

A LEAPS call is the long leg of a **poor man's covered call (PMCC)**: a shorter-dated call sold against it collects premium much as a covered call does against shares. Allocation in this app treats LEAPS and PMCC as one bucket of buying power, separate from the cash-secured-put bucket and from the cash reserve, and tilts between the two buckets depending on the volatility regime.

## Sources

- Cboe Options Institute, LEAPS education: https://www.cboe.com/education/
- OCC, *Characteristics and Risks of Standardized Options*, chapter III (Options on Equity Securities) and chapter X (risks of option holders): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Rule in force in this app: PRD.md section 3.4 and `config/screener_rules.yaml` (generated document *Rule 3.4: LEAPS screener rules*).
