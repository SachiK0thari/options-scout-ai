---
id: gamma
title: "Gamma: how fast delta changes, and why short options get riskier near expiry"
source: "Cboe Options Institute (the Greeks); OCC disclosure document chapter X"
url: https://www.cboe.com/education/
kind: concepts
level: advanced
as_of: 2026-11-03
---

# Gamma

**Gamma** is the rate at which an option's delta changes for a one-dollar move in the underlying. If a put has a delta of −0.25 and a gamma of 0.03, a one-dollar fall in the stock pushes its delta to about −0.28; the option has become more sensitive to the next dollar. Gamma is the same sign for calls and puts and is always positive for the holder of an option and negative for its writer.

## What gamma means for the two sides

A **long** option has positive gamma: its exposure grows as the stock moves in its favour and shrinks as the stock moves against it, which is the asymmetric payoff that option buyers pay for. A **short** option has negative gamma: the writer's exposure grows exactly when the stock is moving against them. A cash-secured put writer who is comfortable with a 0.25 delta at the start of the trade may find themselves holding a 0.60 delta position after a sharp decline, with most of the downside of owning the shares but only the original small premium as cushion.

## Gamma concentrates near the money and near expiration

Gamma is highest for at-the-money options and increases as expiration approaches, because a small move near the strike can flip the option from worthless to fully in the money. A put that is three dollars out of the money with 40 days to run has a modest gamma; the same put with two days to run and the stock sitting at the strike has a very large one. This is the hidden cost of the fast time decay in the final weeks: theta and gamma are two views of the same thing, and the days that pay the most theta are the days with the most gamma risk.

## How this app accounts for it

The screeners do not filter on gamma directly, but several rules exist because of it. The cash-secured put window of 30 to 45 days to expiration stops short of the final two weeks where gamma spikes. The 0.15 to 0.30 delta band keeps initial positions well out of the money so an ordinary move does not put them at the strike. The risk engine does not rely on the starting delta at all for its loss estimate: the **realistic loss** of a CSP is computed as the loss if the stock falls 30% by expiration, which already assumes the put has gone deep in the money and its delta has gone to one. The portfolio's **dollar delta** cap is applied to the starting deltas, and the stress test shows how the portfolio value changes under −10%, −20% and −30% shocks with a 50% rise in implied volatility, which captures the gamma effect on the whole book without reporting gamma as a separate number.

## Gamma and management

Because negative gamma grows as a short option moves toward the money, many writers manage positions by rule rather than by forecast: closing when a target share of the premium has been collected, or rolling when the option reaches a delta or a days-to-expiration threshold. The *Rolling* document describes those rules as this app flags them. None of them changes the arithmetic; they only decide when the writer stops being exposed to it.

## Sources

- Cboe Options Institute, option Greeks education: https://www.cboe.com/education/
- OCC, *Characteristics and Risks of Standardized Options*, chapter X: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
