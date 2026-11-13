---
id: expiration-cycles-and-weeklies
title: "Expiration cycles and weeklies: third Fridays, weekly series and the 30-45 DTE window"
source: "OCC, Characteristics and Risks of Standardized Options, chapter II (expiration); Cboe Options Institute; config/screener_rules.yaml"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: beginner
as_of: 2026-11-13
---

# Expiration cycles and weeklies: third Fridays, weekly series and the 30-45 DTE window

Every option has an **expiration date**, the last day it can be exercised. Which dates are available for a given stock is decided by the listing exchanges under rules the OCC standardises, and the pattern of available dates shapes what a 30-45 day screener can find in any given week.

## Monthly expirations

The standard, or **monthly**, expiration for U.S. equity options falls on the third Friday of the month. If that Friday is an exchange holiday the contract expires on the Thursday before. Actively traded names have a monthly listed for each of the next several months, plus longer-dated **LEAPS** expiring in January of later years. The monthly third-Friday series is usually the one with the deepest open interest, because it has been listed longest and because institutional hedges are concentrated there.

## Weekly expirations

**Weeklies** are series that expire on Fridays other than the third Friday. For a liquid stock the exchanges typically list new weeklies several weeks ahead, and for SPY and QQQ there are expirations on every trading day of the week. A weekly listed today for a Friday six weeks out will have little or no open interest on its first day and may remain thinner than the neighbouring monthly for its whole life.

## Days to expiration and the 30-45 window

**DTE** is the number of calendar days from today until expiration. The cash-secured put screener looks for 30 to 45 DTE, a window chosen because the rate of time decay is already meaningful while the option still has enough extrinsic value that a small move in the stock does not put the writer at risk of early assignment. Suppose today is Monday the 2nd of a month whose third Friday is the 20th. That monthly is 18 days away, too close; the next monthly is about 46 to 53 days away, just outside the window. Only weeklies fall inside 30-45 days in that week. Two weeks later the next monthly is inside the window. The window therefore alternates between weeks where a monthly qualifies and weeks where only weeklies do.

## The fallback and the dte_outside_preferred flag

Because weekly series can fail the open-interest filter of 500 contracts, there are weeks in which the strict 30-45 window holds no candidate that passes every liquidity rule. Rather than return nothing, the screener then widens the search once, to a **fallback window of 21 to 60 DTE**, picks the nearest qualifying expiration inside it, and marks each resulting candidate with the flag `dte_outside_preferred`. The flag is informational: a candidate with it has passed every other rule, but its expiration was accepted only because the preferred window was empty. A 25-day put decays faster but sits closer to assignment risk; a 55-day put ties up collateral longer. The same mechanism applies to the short leg of a PMCC.

## What can go wrong

A monthly that expires on a Thursday because of a holiday has one fewer day than a calendar count suggests. A weekly that qualifies today because its open interest crossed 500 can be the only liquid series at that expiration, so a fill at a reasonable price depends on that one strike. Companies report about every 91 days, so a company's next earnings date falls within 45 days of today about half the time, excluding some of the window's expirations, and within 30 days about a third of the time, excluding all of them; that shrinks the choice further in earnings season.

## Where this shows up in OptionsScout

The Candidates tab shows the expiration date and DTE for every CSP and PMCC short leg, and marks fallback picks with `dte_outside_preferred` so the Scout chat can explain why a 24-day put appears. The windows live in `config/screener_rules.yaml` as `dte_min: 30`, `dte_max: 45`, `dte_fallback_min: 21` and `dte_fallback_max: 60`. LEAPS use a separate rule of at least 365 DTE with 540 preferred.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter II (Options Nomenclature, expiration dates): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute, expiration and weekly options education: https://www.cboe.com/education/
- This app's rules in force: `config/screener_rules.yaml` (see the generated document *Rule 3.3: CSP screener rules*).
