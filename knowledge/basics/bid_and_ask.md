---
id: bid-and-ask
title: "Bid and ask: the spread, the mid, market makers, and why a wide spread is a hidden cost"
source: "SEC investor.gov, Glossary (bid, ask, spread); FINRA, Options investor page"
url: https://www.investor.gov/introduction-investing/investing-basics/glossary
kind: basics
level: beginner
as_of: 2026-11-04
---

# Bid and ask: the spread, the mid, market makers, and why a wide spread is a hidden cost

Every quote for a stock or an option has two prices, not one. The **bid** is the highest price anyone is currently willing to pay; the **ask** (or **offer**) is the lowest price anyone is currently willing to sell at. A seller who wants to trade immediately receives the bid; a buyer who wants to trade immediately pays the ask. The difference between them is the **bid-ask spread**, and the **mid** (midpoint) is the average of the two.

## A worked quote

Suppose a put option is quoted at a bid of $1.10 and an ask of $1.30. The spread is $0.20 and the mid is $1.20. Since one contract covers 100 shares, those figures are $20 and $120 per contract. A put writer who hits the bid collects $110; one who places an order at the mid and waits may collect $120, or may not be filled at all. The quoted "price" of an option that appears on a chart is usually the last trade or the mid, and neither is a price anyone is obliged to deal at.

## Who sits on the other side

The bid and ask are mostly posted by **market makers**: firms that quote both sides of a contract continuously and earn the spread as compensation for standing ready to trade. They hedge their inventory in the underlying stock, so they do not need an opinion on direction, but they widen their quotes when risk rises, for instance before an earnings report, when the stock is moving fast, or in a strike few people trade. Other investors' limit orders also appear in the quote when they improve on it. In liquid contracts, such as near-the-money options on SPY, many market makers compete and the spread is a cent or two. In a far-from-the-money strike on a smaller stock there may be one quoting firm and a spread of a dollar.

## Why a wide spread is a hidden cost

The spread is a cost paid twice: once to open and once to close. Suppose a put is quoted $0.90 bid, $1.50 ask, so the mid is $1.20 and the spread is $0.60, half the mid. A writer who sells at the bid and later buys back at the ask gives up $0.60 of a $1.20 premium to the market, before any move in the stock. Expressed another way, a spread of 50% of mid can turn a trade that looked like a 2% return on collateral into roughly 1%. Unlike a commission, the spread never appears on a statement, which is why it is called hidden. A spread of 2% of mid, by contrast, costs a few cents per contract and barely changes the outcome.

A wide spread is also a warning sign about liquidity. If a position must be closed quickly, say to avoid assignment, the writer pays whatever the ask is at that moment, and in a thin contract the ask may be far above the last trade.

## What can go wrong

Quotes change constantly, and the spread shown on a screen can be stale by the time an order arrives, particularly with delayed data. Spreads widen sharply in the first minutes after the open and during fast markets, so a cap measured at one moment does not describe the cost at another. A tight spread also does not mean a good trade; it only means a cheap one to enter and exit.

## Where this shows up in OptionsScout

The CSP screener requires that the bid-ask spread be no wider than 10% of the mid, and that the bid itself be above $0.10, so a quote of $1.10 by $1.30 (spread $0.20, mid $1.20, ratio 16.7%) would fail while $1.15 by $1.25 (ratio 8.3%) would pass. The Candidates tab shows bid, ask, mid and the spread ratio for every candidate, and the premium used in return on collateral is computed from the quoted prices by tested Python code, never typed in by the explanation text. The Under the hood tab points to the rule in `config/screener_rules.yaml`. Because the app's market data is delayed free-tier data, the spread a user sees at their broker will differ from the one on screen.

## Sources

- SEC investor.gov, *Glossary* (bid, ask, spread, market maker): https://www.investor.gov/introduction-investing/investing-basics/glossary
- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
- Cboe Options Institute education: https://www.cboe.com/education/
