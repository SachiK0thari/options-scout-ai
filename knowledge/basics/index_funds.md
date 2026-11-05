---
id: index-funds
title: "Index funds: what an index is, the S&P 500 and Nasdaq-100, and passive versus active"
source: "SEC investor.gov, Mutual Funds and Exchange-Traded Funds (ETFs); Bogleheads wiki"
url: https://www.investor.gov/introduction-investing/investing-basics/investment-products/mutual-funds-and-exchange-traded-funds-etfs
kind: basics
level: beginner
as_of: 2026-11-04
---

# Index funds: what an index is, the S&P 500 and Nasdaq-100, and passive versus active

An **index** is a list of securities, with a rule for which ones are included and a rule for how much weight each one gets, whose combined value is published as a single number. The number itself cannot be bought. An **index fund** is a mutual fund or ETF that holds the securities on the list in the published weights, so that its return matches the index's return minus a small fee.

## The two indexes behind this app's ETFs

The **S&P 500** tracks about 500 of the largest U.S. companies, selected by a committee that applies rules on size, profitability and trading volume. Companies are weighted by **float-adjusted market capitalisation**: share price multiplied by the number of shares available to the public. A company worth $3 trillion therefore counts for roughly 30 times more than one worth $100 billion. The **Nasdaq-100** tracks the 100 largest non-financial companies listed on the Nasdaq exchange, weighted by a modified market-cap rule that caps the largest names. Because many of the biggest Nasdaq companies are technology firms, the Nasdaq-100 is far more concentrated in that sector than the S&P 500. SPY tracks the first index and QQQ the second.

## Passive versus active

A **passive** fund follows its index mechanically; the manager's job is to hold the list accurately and cheaply. An **active** fund tries to beat an index by choosing securities, timing purchases or weighting differently. Active management costs more, because research and trading are expensive, and over long periods the majority of active funds have trailed the index they compare themselves to after fees. The Bogleheads wiki collects the evidence and the reasoning. Neither approach removes market risk: a passive S&P 500 fund falls when the S&P 500 falls.

## How an index differs from a curated list

It is easy to confuse a published index with any list of companies, so the distinction is worth stating. An index has a transparent, rules-based membership that an outsider can reproduce, a weighting scheme, a committee or sponsor that maintains it, and funds that hold it. A curated watchlist has none of those properties. It is somebody's opinion about which companies are worth looking at, it has no weights, nothing tracks it, and it can change whenever its author changes their mind.

This app's "good-to-own" universe is a curated list of roughly 30 large companies plus SPY and QQQ, kept in `config/quality_universe.yaml`. It is explicitly **not an index**. Its purpose is to act as a filter that keeps volatile, speculative or distressed names out of a put-selling screen, so that assignment, if it happens, is in a company the user would accept owning. The file's own header says the list is not a recommendation.

## What can go wrong

An index fund promises nothing except to roughly match its index, including in a year when the index falls 40%. Market-cap weighting means that when a handful of giant companies dominate, as they have in the Nasdaq-100, a "diversified" fund can carry a large bet on one sector. Investors sometimes also assume that a list of well-known companies is diversified simply because it is long; the sector mix matters more than the count, which the *Diversification* and *Concentration risk* documents cover.

## Where this shows up in OptionsScout

The Quality Screen tab displays every ticker from the curated universe and whether it passed the quality gate on the day of the run, with the two index ETFs at the top of the list. The ranking that follows blends option economics (50%), a quality score (35%) and a consumer-trend signal (15%); the trend signal can re-order names but never adds one that is not on the list or that fails the gate. When the Scout chat is asked whether the universe is "like an index fund", it cites this document to explain that it is a filter, not an index.

## Sources

- SEC investor.gov, *Mutual Funds and Exchange-Traded Funds (ETFs)*: https://www.investor.gov/introduction-investing/investing-basics/investment-products/mutual-funds-and-exchange-traded-funds-etfs
- Bogleheads wiki, main page (index investing philosophy and evidence): https://www.bogleheads.org/wiki/Main_Page
- SEC investor.gov, *Glossary* (index, market capitalisation): https://www.investor.gov/introduction-investing/investing-basics/glossary
