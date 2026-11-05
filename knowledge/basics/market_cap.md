---
id: market-cap
title: "Market capitalisation: what it measures, the size buckets, and why this app stays large-cap"
source: "SEC investor.gov, Glossary (market capitalization); FINRA, Options investor page"
url: https://www.investor.gov/introduction-investing/investing-basics/glossary
kind: basics
level: beginner
as_of: 2026-11-04
---

# Market capitalisation: what it measures, the size buckets, and why this app stays large-cap

**Market capitalisation**, or **market cap**, is the total market value of a company's outstanding shares: the current share price multiplied by the number of shares in existence. Suppose a company has 2 billion shares and each trades at $150; its market cap is $300 billion. It is the simplest way to describe how large a company is in the eyes of the market, and it changes every second the price changes.

## What market cap does and does not measure

Market cap measures what investors collectively think the equity is worth. It is not revenue, not profit, and not the price of the shares. A stock trading at $800 can belong to a smaller company than one trading at $30, if the first has far fewer shares. Nor is market cap the whole value of the business: **enterprise value** adds debt and subtracts cash, and for a company with heavy borrowing the two can differ a great deal. Finally, a large market cap says nothing about whether the shares are cheap or expensive; that is the job of valuation measures such as the price-to-earnings ratio, covered in a separate document.

## The size buckets

There are no official boundaries, and index providers draw them differently, but the conventional labels are:

- **Mega-cap**: roughly $200 billion and above. A few dozen companies worldwide.
- **Large-cap**: roughly $10 billion to $200 billion. Most of the S&P 500.
- **Mid-cap**: roughly $2 billion to $10 billion.
- **Small-cap**: roughly $300 million to $2 billion; below that, **micro-cap**.

Because market caps move with prices, a company can migrate between buckets, and a long bull market pushes the typical boundary upward. The labels are useful for describing a portfolio's mix and for understanding how an index is weighted: a market-cap-weighted index gives a $3 trillion company thirty times the weight of a $100 billion one.

## Why size matters for options

Size correlates with several things an options screen cares about. Larger companies tend to have more shares traded daily, more analysts following them, more frequent and detailed disclosure, and, in the options market, more strikes, more expiries, higher open interest and tighter bid-ask spreads. Their share prices also tend to move less from day to day than small-company prices, though "less" is relative: large caps still fall 30% or more in bad years. Small caps can have options too, but the chains are often thin and a single retail order can move the quote.

## Why this app's universe is large-cap only

The curated "good-to-own" list in `config/quality_universe.yaml` contains large and mega-cap companies plus the two index ETFs. The reason is the product's premise: a cash-secured put is a conditional purchase of 100 shares, so every name must be one the user would accept owning after assignment. Large companies with long dividend records and deep option chains fit that test more often than small ones. The numeric quality gate reinforces the choice indirectly: a minimum price of $20, an average daily volume of at least 1 million shares, 30-day realised volatility at or below 35% and at-the-money implied volatility at or below 45% are thresholds that small and micro-cap stocks rarely clear.

## What can go wrong

Large-cap is not a synonym for safe. Several companies once among the largest in the world have lost most of their value or disappeared. Large caps also move together in a market sell-off, so a portfolio of ten of them is still exposed to the whole market falling at once. And the gate is backward-looking: a company passes on yesterday's volatility, not tomorrow's news.

## Where this shows up in OptionsScout

The Quality Screen tab lists each universe ticker with its gate results; the `mega_cap` and `large_cap` tags from the universe file appear in the ticker details. The Setup tab lets a user add their own ticker, which must still pass the same deterministic gate before the Candidates tab will show it. When the Scout chat is asked why a small company is missing from the screen, it cites this document and the gate thresholds.

## Sources

- SEC investor.gov, *Glossary* (market capitalization): https://www.investor.gov/introduction-investing/investing-basics/glossary
- SEC investor.gov, *Stocks*: https://www.investor.gov/introduction-investing/investing-basics/investment-products/stocks
- FINRA, *Options* investor page (liquidity and suitability): https://www.finra.org/investors/investing/investment-products/options
