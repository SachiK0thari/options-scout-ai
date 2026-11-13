---
id: iv-rank
title: "IV rank and IV percentile: is implied volatility high or low for this stock?"
source: "Cboe Options Institute (implied volatility); PRD.md section 3.6"
url: https://www.cboe.com/education/
kind: concepts
level: advanced
as_of: 2026-11-12
---

# IV rank and IV percentile

An implied volatility of 30% is high for a utility and low for a small biotech. To decide whether options on a particular stock are expensive or cheap *for that stock*, traders compare today's implied volatility with its own history over the past year. Two related measures do this.

## IV rank

**IV rank** places today's IV on the scale between the lowest and highest readings of the past 52 weeks: (IV now − IV 52-week low) / (IV 52-week high − IV 52-week low). A rank of 0% means IV is at its one-year low, 100% means it is at its one-year high, and 50% means it is halfway between. IV rank is simple and widely quoted, but a single extreme reading, for instance one day of panic a few months ago, stretches the range and makes every subsequent reading look low.

## IV percentile

**IV percentile** is the share of trading days in the past year on which IV was *below* today's level. A percentile of 80% means IV has been lower than today on four days out of five. Percentile is robust to a single outlier: one spike day only moves it by one day's worth. The two measures often agree in direction but can differ a lot in level after a volatility shock.

## Why premium sellers and option buyers care

Option strategies are, in part, trades on volatility. A cash-secured put writer is selling implied volatility and prefers to do so when it is high relative to the stock's norm, because the premium is larger for the same distance out of the money and because volatility tends to revert toward its average, which lowers the put's price while it is held. A LEAPS buyer is buying implied volatility and prefers to do so when it is low, because the extrinsic value paid is smaller. This app encodes those preferences as soft scores, not hard filters: the CSP screener prefers an IV rank at or above 30% and the LEAPS screener prefers one at or below 40%. A candidate outside the preferred range still appears but ranks lower. Both preferences apply only to a true rank computed from stored history (see below).

## The data problem, and what this app does about it

Computing either measure requires a year of daily implied volatility history for each stock, which free and low-cost market data feeds generally do not provide. This app therefore records its own history: a scheduled job stores the at-the-money implied volatility of every watchlist ticker once a day. Until at least 30 snapshots exist for a ticker, the report has no rank to show. It shows instead the ratio of current implied volatility to 30-day realised volatility (IV / HV30), labelled "IV/HV", and marks the field `iv_rank_source="hv_proxy"`. The ratio is usually above one because options carry a volatility premium: buyers pay for protection against moves larger than the recent past, so most stocks and index ETFs show 1.1 to 1.8 on an ordinary day. It is shown for context and does not affect the score or set an IV-rank flag.

## Limits

Neither measure says anything about whether volatility is high in absolute terms, which is why the quality gate separately rejects any stock whose at-the-money IV exceeds 45% regardless of rank. Nor does a high rank mean IV must fall: the past year may simply have been quiet before a genuine change in the business. Rank and percentile are context for a premium, not a forecast.

## Sources

- Cboe Options Institute, implied volatility education: https://www.cboe.com/education/
- Definitions and the HV-proxy fallback in force in this app: PRD.md section 3.6.
