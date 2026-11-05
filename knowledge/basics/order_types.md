---
id: order-types
title: "Order types: market, limit, stop, day and good-til-cancelled, and why options are traded with limit orders"
source: "SEC investor.gov, Glossary (market order, limit order, stop order); FINRA, Options investor page"
url: https://www.investor.gov/introduction-investing/investing-basics/glossary
kind: basics
level: beginner
as_of: 2026-11-04
---

# Order types: market, limit, stop, day and good-til-cancelled, and why options are traded with limit orders

An **order** is an instruction to a broker to buy or sell a security. Every order states a security, a direction (buy or sell), a quantity, and two further choices that beginners often overlook: how the price is to be determined, and how long the instruction stays alive.

## Price instructions

- A **market order** says "fill this now at whatever price is available." It almost always executes, but the price is not known until it does. For an option, or in a fast market, it can be far worse.
- A **limit order** says "buy at this price or lower" or "sell at this price or higher." The price is controlled; the fill is not. If the market never reaches the limit, the order sits unfilled.
- A **stop order** (or stop-loss) becomes a market order once the security trades at or through a trigger price. It is often used to exit a losing position automatically. Because it turns into a market order, the fill after a gap can be well past the trigger. A **stop-limit order** turns into a limit order instead, which controls price but may not fill at all.

## Time instructions

- A **day order** expires at the close of the trading day if it has not filled. This is the default at most brokers.
- A **good-til-cancelled (GTC)** order stays open until it fills or the investor cancels it; brokers usually impose a maximum of 60 to 90 days. GTC orders are easy to forget, and a forgotten sell-to-open order can fill weeks later under conditions the investor no longer wants.

## Why options should be traded with limit orders

The case for limit orders on options rests on the bid-ask spread, covered in the *Bid and ask* document. Suppose a put is quoted $1.10 bid, $1.30 ask. A market order to sell it receives $1.10, the bid, and sometimes less if the quote moves between the click and the fill. A limit order to sell at $1.20, the mid, often fills when a market maker is willing to improve on their quote, and if it does not fill, the writer has lost nothing but time. On a contract with a 10% spread, that difference is around 8% of the premium.

Options quotes are also less reliable than stock quotes. Many strikes trade only a few times a day, so the "last" price can be hours old, and a market order fills against the current quote, not the last print. Opening a short put with a market order in a fast-moving market is one of the common ways beginners receive far less premium than they expected. For the same reason, a stop order on an option is a weak protection: a thin contract can gap past the stop and fill at a price that bears little relation to it. Stops on the underlying stock, or simply closing the option with a limit order when a rule is hit, are more predictable.

## What can go wrong

A limit order that is too aggressive never fills, and a position the investor meant to close stays open into expiry. A GTC order fills on a day the investor was not watching. Market orders on illiquid options can fill at prices that look like errors but are entirely valid. Brokers also differ on which order types they offer for options and on whether complex orders, such as the two legs of a PMCC, can be entered as one ticket.

## Where this shows up in OptionsScout

This app **never places orders** and never connects to a brokerage; it has no order ticket of any kind. The Candidates tab shows bid, ask and mid for each contract so a user understands what a limit at the mid would mean, and the Scout chat cites this document when asked how a candidate would be traded. Every price on screen is delayed free-tier data from MarketData.app or Tradier, so a user who proceeds at their broker will see a different, live quote and must decide their own limit.

## Sources

- SEC investor.gov, *Glossary* (market order, limit order, stop order, good-til-cancelled): https://www.investor.gov/introduction-investing/investing-basics/glossary
- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
- OCC, *Characteristics and Risks of Standardized Options* (liquidity and execution risks): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
