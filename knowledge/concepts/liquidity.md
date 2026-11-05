---
id: liquidity
title: "Liquidity: bid-ask spread, open interest and volume, and why they are filters"
source: "OCC disclosure document chapter X (risks of illiquid markets); FINRA options investor page; PRD.md sections 3.3–3.4"
url: https://www.finra.org/investors/investing/investment-products/options
kind: concepts
level: intermediate
as_of: 2026-11-03
---

# Liquidity: spread, open interest and volume

An option strategy is only as good as the prices at which it can be opened and closed. Three numbers describe how easily that can be done.

## Bid-ask spread

The **bid** is the highest price a buyer is currently willing to pay; the **ask** is the lowest price a seller will accept. Their midpoint, the **mid**, is the usual estimate of fair value, and the spread as a fraction of the mid, (ask − bid) / mid, is the round-trip cost of trading at the quoted prices. A put quoted $1.40 bid / $1.60 ask has a mid of $1.50 and a spread of 13%: a writer who sells at the bid and later buys back at the ask has given up 13% of the premium before the stock moves at all. Spreads widen when volume is thin, when the underlying is volatile, in the first and last minutes of the session, and in series far from the money or far from expiration.

## Open interest

**Open interest** is the number of contracts in a series that are currently open, that is, written and not yet closed, exercised or expired. It is published once a day by the OCC. High open interest signals an established market with many participants who will want to trade the series again, which usually means tighter spreads and the ability to exit a position of ordinary size without moving the price. Open interest of a few dozen contracts means the writer may be the only seller when they want to close.

## Volume

**Volume** is the number of contracts traded today. It confirms that a series is active right now rather than merely having been active in the past. The underlying stock's **average daily share volume** matters as well: options on thinly traded stocks are thinly traded themselves, and market makers quote them wide because hedging in the stock is costly.

## Why these are hard filters in this app

Illiquidity is not a risk that can be priced; it is a cost that is paid for certain and an exit that may not exist when it is needed. The screeners therefore apply liquidity rules as filters rather than scores:

- Cash-secured puts: open interest of at least 500 contracts, bid-ask spread at most 10% of mid, bid above $0.10, and an underlying with average volume of at least one million shares per day and a price of at least $10.
- LEAPS calls: open interest of at least 100 contracts and spread at most 5% of mid, the tighter spread limit because LEAPS are large-dollar contracts where a wide spread is a large absolute cost.
- The quality gate separately requires at least one million shares of average daily volume and a price of at least $20 for every stock in the universe.

Within the surviving candidates, liquidity also contributes 20% of the option-quality score, so a tighter spread and deeper open interest rank higher among otherwise similar puts.

## Reading the numbers in the report

The report shows bid, ask, mid, spread percentage and open interest for every candidate. All computations (premium, return, margin) use the **mid**, which is the standard convention but is optimistic for a seller, who will often be filled closer to the bid. The difference matters most for small premiums, which is one reason the CSP screener demands a bid above $0.10. Data from free or delayed feeds may show stale quotes; a spread that looks unusually wide or a bid of zero is often a sign of a stale snapshot rather than a genuinely dead market.

## Sources

- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on the risk that a secondary market may not exist or may be illiquid: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Rules in force in this app: PRD.md sections 3.3 and 3.4 and `config/screener_rules.yaml`.
