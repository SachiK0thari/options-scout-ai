---
id: fill-quality-and-limit-orders
title: "Fill quality and limit orders: mid, natural, and what a 10% spread means for slippage"
source: "FINRA, Options investor page; OCC, Characteristics and Risks of Standardized Options, chapter X; config/screener_rules.yaml"
url: https://www.finra.org/investors/investing/investment-products/options
kind: concepts
level: beginner
as_of: 2026-11-04
---

# Fill quality and limit orders: mid, natural, and what a 10% spread means for slippage

A **fill** is the price at which an order is actually executed. For options, the gap between the price a screener shows and the price received is often larger than the difference between two candidates.

## Bid, ask, mid and natural

Every option series has a **bid**, the highest price anyone is currently willing to pay, and an **ask**, the lowest price anyone will sell at. The **mid** is their average and is the usual estimate of the contract's fair value. The **natural** price is the side of the quote that fills immediately: for a seller the natural is the bid, for a buyer it is the ask. Suppose a put is quoted $1.43 bid and $1.57 ask. The mid is $1.50, the spread is $0.14, and a put writer's natural price is $1.43.

## Limit orders and market orders

A **limit order** names the worst price the trader will accept; it fills at that price or better, or not at all. A **market order** asks to be filled immediately at whatever price the market provides. On a liquid stock the two behave similarly because the spread is a cent or two. Options are different: each contract covers 100 shares, spreads are often several percent of the price, and the displayed quote can change in the time it takes an order to arrive. A market order to sell a put can fill at the bid, or below it if the bid was for fewer contracts than the order, and the trader has no way to object afterwards. For that reason FINRA and exchange education describe limit orders as the standard tool for options.

A common practice is to place a limit order at the mid and move toward the natural price a cent or two at a time if it does not fill. Whether a mid-price order fills depends on a market maker being willing to trade inside the quote, which is more likely in deep series.

## Slippage and the 10% spread cap

**Slippage** is the difference between the price a model assumed and the price received. This app computes every return, premium and collateral figure at the mid, which is the standard convention but is optimistic for a seller. The screener's rule that the spread may be no more than 10% of the mid bounds how optimistic. If the spread is exactly 10% of mid, the bid sits 5% below mid; a writer filled at the natural gives up 5% of the premium, and one who later closes at the ask gives up another 5%. On the $1.50 example above the spread is 9.3% of mid, so selling at the natural rather than the mid costs $7 per contract, and the round trip at the quote costs $14, out of $150 of premium. The 10% cap therefore bounds the worst-case round-trip cost at the quotes to about a tenth of the premium. A series quoted $0.90 by $1.10, a 20% spread, fails the filter.

## What can go wrong

Quotes from a delayed free-tier feed can be minutes old, so the mid on screen may not be the mid at the moment of trading. Spreads widen at the open and close, around news, and when the underlying moves quickly, so a 9% spread at screening time can be 15% at order entry. A limit order protects the price but not the fill: a writer who insists on the mid may simply not trade, and an order left unfilled while the stock moves can later fill at a price that is no longer attractive. Small premiums suffer most, which is one reason the screener also requires a bid above $0.10.

## Where this shows up in OptionsScout

The Candidates tab shows bid, ask, mid and spread percentage for every option, with the spread cap `max_spread_pct: 0.10` from `config/screener_rules.yaml` applied as a hard filter. All returns are labelled as computed at the mid. The app never places orders, so order type and final fill are the user's decision at their broker.

## Sources

- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on secondary market risk and the possibility that a position cannot be closed: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute, order types and bid-ask education: https://www.cboe.com/education/
