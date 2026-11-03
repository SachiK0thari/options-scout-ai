---
id: earnings-risk
title: "Earnings risk: why a scheduled announcement inside the option's life changes everything"
source: "OCC disclosure document chapter X; SEC EDGAR (Form 10-Q and 8-K filings announce results); PRD.md section 3.3"
url: https://www.sec.gov/edgar/search/
kind: concepts
as_of: 2026-11-03
---

# Earnings risk

Public companies in the United States report results every quarter, filing a Form 10-Q (or a 10-K for the fourth quarter) with the Securities and Exchange Commission and usually announcing the numbers in a press release filed on Form 8-K the same day. The announcement date is known weeks in advance, and the market treats it as the single most important scheduled event in a stock's calendar. For an option writer it is the one day on which a stock in a quiet uptrend can gap 10% or more in a single session.

## What the market does around earnings

Because everyone knows a large move is possible, options expiring after the announcement carry extra implied volatility in the days before it. That extra IV is the market's estimate of the expected move. Once the numbers are out, the uncertainty is gone and implied volatility falls back, often sharply: the **earnings crush**. A premium seller who holds through the event collects that crush if the stock stays inside the expected range, and takes the full gap loss if it does not. The payoff is lopsided: a few extra cents of premium against the risk of a double-digit move.

## Why this app excludes earnings from short puts

A cash-secured put is written on the premise that the writer is content to own the stock near the strike. An earnings gap of −15% does not deliver the stock near the strike; it delivers the stock far below it, and the realistic-loss arithmetic assumes an ordinary decline, not an overnight repricing of the business. The CSP screener in this repository therefore **excludes any put whose expiration falls after the next earnings date**. The rule is `exclude_earnings_before_expiry: true` in `config/screener_rules.yaml`; switching it to false would turn the exclusion into a flag that is shown but not enforced. The excluded candidates are listed in the report with the reason "earnings before expiry" so the user can see what was dropped and why.

## LEAPS and PMCC are affected differently

A LEAPS call spanning a year will contain four earnings announcements; excluding them is impossible and unnecessary, because the long holding period averages over them and the position is sized to lose at most its premium. The **short call** of a PMCC, however, lives 30 to 45 days and is exposed in the same way a short put is: an earnings rally through the short strike caps the position's gain and risks assignment. The report flags any short call whose life spans an earnings date.

## The data and its limits

The earnings date comes from the market data provider's calendar for each ticker and is shown in the report. Companies occasionally move their dates, and the provider's calendar may lag by a day or two, so the report's earnings flag should be checked against the company's investor-relations page before expiry. ETFs such as SPY and QQQ have no earnings date of their own, but their constituents report throughout the season, which is why index implied volatility rises in the heaviest reporting weeks.

## Reading the filing itself

The Item 1A *Risk Factors* section of a company's latest 10-K, excerpts of which are indexed in this knowledge base for the demo tickers, is the company's own description of what could make a quarter go badly. A put writer who would be assigned shares after a bad report is, in effect, taking on exactly those risks.

## Sources

- U.S. Securities and Exchange Commission, EDGAR full-text search for 10-K, 10-Q and 8-K filings: https://www.sec.gov/edgar/search/
- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on the effect of news and volatility changes on option values: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Rule in force in this app: PRD.md section 3.3 and `config/screener_rules.yaml` (generated document *Rule 3.3: CSP screener rules*).
