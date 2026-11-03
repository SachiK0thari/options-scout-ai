---
id: volatility-regime
title: "The VIX and the volatility regime: how market-wide implied volatility tilts the allocation"
source: "Cboe, VIX Index overview and methodology; PRD.md section 3.1"
url: https://www.cboe.com/tradable_products/vix/
kind: concepts
as_of: 2026-11-03
---

# The VIX and the volatility regime

The **Cboe Volatility Index (VIX)** measures the market's expectation of 30-day volatility in the S&P 500, derived from the prices of a wide strip of S&P 500 index options. It is quoted as an annualised percentage: a VIX of 20 implies an expected one-month move of roughly ±5.8% in the index (20% divided by the square root of 12). Because it is computed from option prices rather than from past returns, the VIX moves with fear and relief in real time, rising sharply in sell-offs and drifting down in calm markets, which earned it the nickname "fear gauge".

## Why a single-stock option trader watches an index measure

Implied volatility in individual stocks is strongly correlated with the market-wide level. When the VIX is high, puts on almost every large company are expensive relative to their own history; when it is low, calls, including long-dated LEAPS, are cheap. A strategy that sells puts and buys LEAPS is therefore facing the same question on both sides: is premium rich or thin right now? The VIX answers it for the market as a whole, and this app uses the answer to decide how much buying power each strategy bucket receives.

## The regime definition in force

The app does not use the VIX level directly, because 20 was high in 2017 and low in 2020. It uses the **VIX one-year percentile**: the share of trading days in the past 252 on which the VIX closed below today's value.

- **High-IV regime**: percentile at or above 70. The allocation shifts **10 points of the account from the LEAPS/PMCC bucket to the cash-secured-put bucket**: sell expensive premium, do not pay up for long options.
- **Low-IV regime**: percentile at or below 30. The allocation shifts **10 points from cash-secured puts to LEAPS**: long options are cheap and put premium is thin.
- **Normal regime**: anything in between leaves the base allocation unchanged.

The cash reserve is never touched by the tilt. For a balanced profile the base split is 45% cash-secured puts, 25% LEAPS/PMCC and 30% cash; in a high-IV regime that becomes 55% / 15% / 30%, and in a low-IV regime 35% / 35% / 30%. The thresholds and the size of the shift live in `config/risk_profiles.yaml` and are reproduced in the generated *Rule 3.1* document.

## What the regime is not

The tilt is an allocation rule, not a market forecast. A high VIX percentile says premium is rich relative to the past year; it does not say the market will fall, and periods of high implied volatility are exactly the periods in which short puts suffer their largest losses. The per-position limits, the realistic-loss cap and the stress test apply unchanged in every regime, and the quality gate's own implied-volatility limit (45% at the money) rejects single names whose options have become expensive for reasons of their own. The report states the current VIX, its percentile and the regime label so the reader can see which allocation was used and why.

## Sources

- Cboe, VIX Index overview, methodology and historical data: https://www.cboe.com/tradable_products/vix/
- Rule in force in this app: PRD.md section 3.1 and `config/risk_profiles.yaml` (generated document *Rule 3.1: Allocation of buying power*).
