---
id: pe-and-earnings
title: "P/E and earnings: earnings per share, the price-to-earnings ratio, earnings season, and why the CSP screener avoids earnings dates"
source: "SEC investor.gov, Glossary (earnings per share, price-to-earnings ratio); SEC EDGAR (10-Q and 10-K filings)"
url: https://www.investor.gov/introduction-investing/investing-basics/glossary
kind: basics
level: beginner
as_of: 2026-11-04
---

# P/E and earnings: earnings per share, the price-to-earnings ratio, earnings season, and why the CSP screener avoids earnings dates

**Earnings** is the everyday word for a company's net profit: revenue minus all costs, interest and taxes over a period. Public companies in the United States report earnings every quarter in a filing with the SEC (a 10-Q for the first three quarters and a 10-K for the full year), usually accompanied by a press release and a conference call. Those filings are freely searchable on EDGAR.

## Earnings per share

**Earnings per share (EPS)** is net profit divided by the number of shares outstanding. Suppose a company earns $10 billion in a year and has 2 billion shares; its EPS is $5.00. EPS puts profit on the same per-share footing as the stock price, which is what makes the next ratio possible.

## The price-to-earnings ratio

The **price-to-earnings ratio (P/E)** is the share price divided by EPS. With a $150 share price and $5.00 EPS, the P/E is 30: an investor pays $30 for each dollar of annual profit. A **trailing P/E** uses the last four reported quarters; a **forward P/E** uses analysts' estimates for the next four. A high P/E means the market expects profits to grow quickly, or that the shares are expensive, or both; a low P/E means the opposite, or that the market expects trouble. P/E is useless when earnings are negative and misleading when a one-off gain or loss distorts a single year.

## Earnings season

Because most companies close their books on calendar quarters, reports cluster in the two to three weeks beginning about two weeks after each quarter ends: mid-January, mid-April, mid-July and mid-October. This period is called **earnings season**. The report date for each company is announced in advance and is usually known a month or more ahead.

## Why an earnings date matters so much for a short option

An earnings report is the single most predictable moment of unpredictable news. The company reveals a quarter's results, and the stock can gap 5%, 10% or more in either direction at the next open, with no chance to trade in between. Option prices reflect this: implied volatility rises into the report and collapses afterward. For a writer of a put, the premium looks attractive precisely because the market is pricing a possible large move. Collecting that premium is a bet on the outcome of the report, not a quiet way to be paid for waiting to buy shares.

## Why the CSP screener excludes expiries that span an earnings date

The cash-secured put screener in this app requires that no earnings release fall between today and the option's expiry. A candidate whose expiry would span a report date is dropped, not merely scored lower. The reason follows from the product's premise: a CSP is meant to be a conditional purchase of a company the user would accept owning, priced on normal day-to-day volatility. A 30-to-45-day put at a 0.15 to 0.30 delta that crosses an earnings date carries a materially higher chance of landing deep in the money than its delta suggests, because delta is computed from a volatility assumption that does not model a one-day gap. Removing those expiries keeps the probability figures on the Candidates tab honest.

## What can go wrong

Earnings dates can move, and a company can pre-announce bad results at any time. The exclusion depends on the date in the data feed being correct; the app uses delayed free-tier data, and a missing or stale date would let a candidate through. A P/E can also look reasonable right up to the quarter in which earnings fall by half.

## Where this shows up in OptionsScout

In the Candidates tab, the CSP list only contains expiries with no earnings date before expiry; the Under the hood tab shows the rule, which lives in `config/screener_rules.yaml` alongside the 30-45 DTE window, the open-interest floor of 500 contracts and the spread cap of 10% of mid. The planned News panel will surface upcoming report dates for universe names. When a user asks the Scout chat why a particular expiry is missing, the answer cites this document and the rule in force.

## Sources

- SEC investor.gov, *Glossary* (earnings per share, price-to-earnings ratio): https://www.investor.gov/introduction-investing/investing-basics/glossary
- SEC EDGAR full-text search (10-Q and 10-K filings): https://www.sec.gov/edgar/search/
- Cboe Options Institute education (implied volatility around events): https://www.cboe.com/education/
