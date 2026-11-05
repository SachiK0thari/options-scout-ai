---
id: zero-dte-risk
title: "Zero-DTE options: gamma near expiry and why this app's windows exclude them"
source: "OCC, Characteristics and Risks of Standardized Options, chapter X; Cboe Options Institute; config/screener_rules.yaml"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: intermediate
as_of: 2026-11-04
---

# Zero-DTE options: gamma near expiry and why this app's windows exclude them

A **zero-DTE** (0DTE) option is one that expires on the day it is traded. Every option becomes a zero-DTE contract on its last day, but the term usually refers to a style of trading built around the daily expirations now listed on SPX, SPY and QQQ and the weekly Fridays of large stocks. A 40-day put becomes a 0DTE put on expiration Friday, and it behaves very differently.

## What changes on the last day

An option's price has two parts: **intrinsic value**, what exercise would be worth now, and **extrinsic value**, the rest. On the final day almost no extrinsic value remains except for strikes within reach of the day's move. **Theta**, the daily loss of extrinsic value, is at its largest in absolute terms for an at-the-money option, which is what attracts sellers. **Gamma**, the rate at which **delta** (the option's sensitivity to the stock) changes as the stock moves, is also at its largest, and that is the risk.

## Gamma near expiry

With 40 days left, a put struck 5% below the stock might have a delta of about -0.20 and move slowly as the stock drifts. On expiration day the same put has a delta near zero while the stock is above the strike and near -1.00 once it is below; the whole transition happens across a price range of a few cents and a few minutes. Suppose a stock closes the week at $50.40 with a $50 put quoted at $0.05 an hour before the close. A 1% late drop to $49.90 makes the put worth $0.10 intrinsic, a doubling, and leaves the writer facing assignment of shares that opened the hour comfortably out of the money. A buyer of the same put most often loses the entire premium.

## Risks specific to the short side

- **Assignment on a late move.** The OCC exercises any equity option that finishes at least $0.01 in the money unless instructed otherwise, and holders may exercise on after-hours news up to the broker's cut-off, so a put out of the money at the close can still be assigned.
- **Pin risk.** When the stock finishes within pennies of the strike, whether assignment happens is unknown until the weekend.
- **No time to adjust.** Rolling or closing a position that has gone wrong requires a liquid quote at a moment when spreads widen and quotes flicker.
- **Slippage.** A premium of a few cents can lose a large fraction to the bid-ask spread, so the realised return is far below the quoted one.

## Why the app's windows exclude them

The cash-secured put screener accepts 30 to 45 days to expiration, falling back to a 21 to 60 day window only when the strict window has no liquid candidate. The PMCC short leg uses the same windows, and LEAPS must have at least 365 days. Nothing the app screens has fewer than 21 days to expiration. The windows ensure a candidate has meaningful extrinsic value at entry, which keeps gamma low, keeps the 0.15-0.30 delta band meaningful, and gives the stock weeks rather than hours to move before the strike is tested. The app's thesis is a conditional purchase of a good company; a contract whose outcome turns on the last hour of trading is a bet on noise.

## What can go wrong anyway

A 30-day put becomes a 0DTE put if held to expiration. The gamma, pin and late-assignment risks described above return in the final days of every short put the screener produces; the *Exit rules and profit taking* document discusses the common practice of closing before that point. The app does not manage open positions.

## Where this shows up in OptionsScout

The `dte_min` and `dte_fallback_min` values in `config/screener_rules.yaml` (30 and 21 for CSP and PMCC, 365 for LEAPS) are the rule that keeps zero-DTE and short-dated contracts out of the Candidates tab, and the Learn tab's *Gamma* and *Theta* documents explain the Greeks involved.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter X (risks of option writers; exercise and assignment at expiration): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute, Greeks and expiration education: https://www.cboe.com/education/
- This app's rules in force: `config/screener_rules.yaml`.
