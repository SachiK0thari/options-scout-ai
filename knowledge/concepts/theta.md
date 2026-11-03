---
id: theta
title: "Theta: time decay, the daily cost of holding an option and the income of writing one"
source: "Cboe Options Institute (the Greeks); OCC disclosure document chapter X"
url: https://www.cboe.com/education/
kind: concepts
as_of: 2026-11-03
---

# Theta (time decay)

**Theta** is the expected change in an option's price for the passage of one day with the stock price, volatility and interest rates unchanged. It is almost always negative for long options: each day that passes removes a little of the time remaining for the option to become more valuable, so a little of its extrinsic value disappears. For the writer of an option the same quantity is positive: the option they are short becomes cheaper to buy back every day, which is the mechanism by which premium-selling strategies earn their return.

## Only extrinsic value decays

Intrinsic value does not decay; a put that is $5 in the money is worth at least $5 at any time. Theta acts only on **extrinsic value**, the part of the premium above intrinsic value. That is why deep in-the-money LEAPS, which carry little extrinsic value relative to their price, lose little to theta each day, while at-the-money options with months to run lose the most in absolute terms.

## Decay is not linear

For an at-the-money option the extrinsic value falls roughly with the square root of time remaining, which means decay is slow when expiration is distant and accelerates sharply in the final weeks. Half of a nine-month option's time value is gone only after about six and a half months; a 45-day option loses half of its time value in its last 11 or 12 days. Out-of-the-money options behave somewhat differently, losing value fastest a bit earlier because they also lose their chance of ever finishing in the money, but the broad pattern is the same: the last month is where most of the decay happens.

## Why the screeners pick the windows they do

The cash-secured put screener looks 30 to 45 days out. That window sits in the steep part of the decay curve, so the writer collects a disproportionate share of the option's total time value for the time they are exposed, while still receiving a premium large enough to matter after transaction costs. Shorter expiries decay even faster per day but offer less premium and more gamma risk; longer expiries pay more total premium but tie up collateral through the slow part of the curve.

The LEAPS screener does the opposite, buying a year or more of time so that the position sits on the flat part of the curve and the daily decay is small relative to the stock exposure. The "roll or close" flag at 240 days to expiration exists because a LEAPS that has decayed into the final eight months is approaching the steep section and will start to behave less like stock.

## Theta is a model estimate

Theta, like the other Greeks in this app, comes from the Black-Scholes-Merton model evaluated with the implied volatility quoted by the market data provider. Real one-day price changes also reflect moves in the stock and in implied volatility, which usually dominate theta on any single day; theta describes the drift, not the noise. Weekends and holidays count as calendar time for decay, which is why option prices on Friday afternoon often already reflect the weekend.

## Sources

- Cboe Options Institute, option Greeks education: https://www.cboe.com/education/
- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on the erosion of time value: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
