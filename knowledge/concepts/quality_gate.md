---
id: quality-gate
title: "How this app's good-to-own quality gate works"
source: "PRD.md section 3.7 and config/quality_universe.yaml; OCC disclosure document chapter X on assignment risk"
url: PRD.md#37-good-to-own-universe-quality-gate
kind: concepts
level: intermediate
as_of: 2026-11-03
---

# How this app's quality gate works

The product promise is "stocks you would be happy to own if assigned". The quality gate is the mechanism that enforces it. It is a **filter, not a discovery engine**: it decides which tickers are allowed into the option screeners at all, records a reason for every rejection, and produces a score for the survivors. Everything about it lives in `config/quality_universe.yaml` and `core/quality.py`, and the thresholds quoted below are the ones in force for every run.

## Step 1: the curated list

The universe starts from a list of about thirty names: large, profitable companies with long dividend records or dominant franchises (Apple, Microsoft, Costco, Procter & Gamble, Johnson & Johnson and the like) plus the SPY and QQQ index ETFs. Each entry carries a sector, tags and a one-line reason for its inclusion, all shown in the generated *Rule 3.7* document. Speculative and meme names are absent on purpose. A user may add tickers; they are flagged *user-added* and must pass the same numeric gate, and a configuration switch (`require_curated`) can reject them outright.

## Step 2: the numeric gate, evaluated on the day of the run

A curated name is not trusted blindly. On every run each ticker's latest snapshot is checked against seven gates:

| Gate | Threshold in force | Why |
|---|---|---|
| Price | at least $20 | low-priced names are easily manipulated |
| Average daily volume | at least 1,000,000 shares | liquidity for the stock and its options |
| 30-day realised volatility (HV30) | at most 35% | calm recent price action |
| At-the-money implied volatility | at most 45% | the market is not pricing a shock |
| Distance below the 90-day closing high | at most 20% | no falling knives |
| Price history | at least 31 closes | enough data to judge the above |
| `require_curated` | false | optional hard rejection of user-added names |

A ticker that fails any gate is listed in the report with the exact reason ("HV30 41% > 35%") and never reaches the screeners. **Missing data fails a gate; it does not pass it.** In fixture mode the bundled snapshots make AAPL, MSFT, COST, SBUX, NKE, SPY and QQQ pass while CMG, DECK and ELF fail, and the test suite asserts both lists.

## Step 3: the quality score

Survivors receive a score between 0 and 1: 0.4 × stability + 0.3 × trend + 0.3 × curated, where stability = 1 − HV30 / 35% and trend = 1 − drawdown / 20%, both clipped to the unit interval, and curated is 1 for a listed name and 0 for a user-added one. A curated stock with 17.5% realised volatility sitting at its 90-day high scores 0.80, the golden value in the test suite.

## Step 4: where the score goes

The final ranking of option candidates is 0.50 × option quality + 0.35 × quality score + 0.15 × consumer-trend score / 100. The stock's quality carries more than a third of the ranking so that, between two puts with similar premium and probability, the one on the steadier business ranks first. When more names qualify than the universe cap of 12 tickers, the order is: the user's own tickers, then curated names with a consumer-trend signal (highest first), then list order.

## What the gate is not

The gate looks at ninety days of prices and one day of option quotes. It cannot see a pending lawsuit, an accounting problem or a product failure that has not yet moved the stock; the Item 1A risk-factor excerpts indexed in this knowledge base are the company's own list of such things. "Good to own" means *less speculative*, not *safe*: a large company can still fall sharply, and a put writer assigned on one still owns the decline. The gate is a way of refusing the worst candidates, not a promise about the rest.

## Sources

- Specification and thresholds in force: PRD.md section 3.7 and `config/quality_universe.yaml` (generated document *Rule 3.7: Good-to-own universe (quality gate)*).
- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on the obligation of a put writer to purchase the underlying: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
