---
id: pattern-day-trading-rule
title: "The pattern day trading rule: what it is and why a 30-45 DTE put seller rarely meets it"
source: "FINRA, Day Trading investor page (pattern day trader definition and minimum equity); FINRA Rule 4210(f)(8)(B); Regulation T, 12 CFR Part 220"
url: https://www.finra.org/investors/investing/investment-products/stocks/day-trading
kind: tax
level: beginner
as_of: 2026-11-04
---

# The pattern day trading rule: what it is and why a 30-45 DTE put seller rarely meets it

A **day trade** is the purchase and sale, or sale and purchase, of the same security on the same day in a margin account. Options count: selling a put to open and buying the same put back later the same day is one day trade. FINRA's margin rules give accounts that do this often a special status with its own equity requirement. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## The definition

FINRA's day trading page and Rule 4210(f)(8)(B) define a **pattern day trader** as a customer who makes four or more day trades within five business days in a margin account, provided those day trades are more than six percent of the customer's total trades in the account over the same period. A broker may also designate a customer as a pattern day trader if it knows or has a reasonable basis to believe the customer will day trade.

## The $25,000 minimum equity requirement

A pattern day trader must maintain minimum equity of $25,000 in the margin account on any day the customer day trades. The figure is set by FINRA Rule 4210 and quoted on FINRA's investor page; it is a regulatory floor, and brokers may set a higher house requirement. If the account's equity falls below $25,000, the customer is not permitted to day trade until it is restored. The rule also sets a specific **day-trading buying power**, and a day-trading margin call follows if it is exceeded; the FINRA page explains how the call is met.

## Why the rule rarely touches a 30-45 DTE put seller

The cash-secured put screener in this app looks for puts with 30 to 45 days to expiration, opened once and then either left to expire, bought back weeks later, or assigned. None of those is a day trade, because the opening and closing transactions fall on different days. Suppose an investor sells four different puts on a Monday and buys them all back the following Friday; that is zero day trades. The rule is reached only when a position is opened and closed within one session, for example buying back a put a few hours after writing it because the price moved, and doing so four times in a week.

## Cash accounts are governed by settlement instead

The pattern day trader rule applies to margin accounts. A **cash account** is not subject to it, but it is subject to Regulation T's rule that purchases must be paid for with settled funds. Since the SEC's move to **T+1 settlement** in 2024, stock and option trades settle one business day after the trade. Buying with proceeds from a sale that has not yet settled, and then selling the new position before that sale settles, is a **good-faith violation**, and repeated violations lead the broker to restrict the account to settled cash for a period. A cash account can therefore trade as often as it likes but must respect what has settled.

## What can go wrong

A margin account owner who closes a put the same day it was written, several times in a volatile week, can be labelled a pattern day trader with little warning and find the account frozen for day trading if its equity is under $25,000. Confusing the two regimes is the other error: a cash account owner who assumes "no day trading rule" also means "no settlement rule" will collect good-faith violations.

## Where this shows up in OptionsScout

The app's CSP screener only produces 30-45 DTE candidates and never places trades, so nothing in the Candidates tab is a day trade. The Setup tab asks for the account type, and the Portfolio & Risk tab applies a margin-usage constraint only to margin accounts; the app does not track day trades or the pattern day trader count, so a user who also trades actively elsewhere has to watch that count at the broker.

## Sources

- FINRA, Day Trading investor page: https://www.finra.org/investors/investing/investment-products/stocks/day-trading
- FINRA Rule 4210, Margin Requirements, paragraph (f)(8)(B) day-trading: https://www.finra.org/rules-guidance/rulebook/finra-rules/4210
- Regulation T, 12 CFR Part 220, including section 220.8 on cash accounts: https://www.ecfr.gov/current/title-12/chapter-II/subchapter-A/part-220
- SEC press release 2023-29, adoption of T+1 settlement: https://www.sec.gov/news/press-release/2023-29
