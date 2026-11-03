---
id: probability-otm
title: "Probability of expiring out of the money: what N(d2) does and does not tell you"
source: "OCC disclosure document chapter X; PRD.md section 3.6 (Black-Scholes-Merton formulas)"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
as_of: 2026-11-03
---

# Probability of expiring out of the money

Next to every short put this app shows a **probability OTM**: the model's estimate of the chance that the option finishes out of the money at expiration and therefore expires worthless, which for a cash-secured put writer is the outcome in which the whole premium is kept and no shares are bought.

## Where the number comes from

In the Black-Scholes-Merton framework, the risk-neutral probability that a put expires out of the money is N(d2), where d2 = d1 − σ√T and N() is the standard normal cumulative distribution. For a call it is N(−d2). The inputs are the stock price, the strike, the implied volatility, the risk-free rate, the dividend yield and the time to expiration. This repository implements the formula in `core/pricing.py` and checks it against golden values; the explanation text may quote the result but never recomputes it.

## Why it is not the same as delta

Traders often use the absolute value of delta as a shorthand for the probability of finishing in the money. Delta is e^(−qT) × N(d1) for a call, and d1 is larger than d2 by σ√T, so delta always overstates the probability of finishing in the money a little, and the gap grows with volatility and time. For a 40-day put at 0.25 delta the difference is a couple of percentage points; for a two-year LEAPS it is substantial. This app shows both numbers because they answer different questions: delta is exposure, probability OTM is a model odds estimate.

## What "risk-neutral" means for a reader

The probability is computed under the assumption that the stock drifts at the risk-free rate minus the dividend yield, not at whatever return an investor expects. It is the probability embedded in option prices, which is what makes it consistent with the premium being quoted, but it is not a forecast of the stock. If the market's implied volatility is wrong, the probability is wrong in the same direction. Implied volatility also assumes returns are approximately normally distributed, while real stock returns have fatter tails: large drops happen more often than the model says. A 75% probability OTM should be read as "roughly three times out of four under the market's own assumptions", not as a measured frequency.

## Probability of touching versus probability at expiration

N(d2) is the probability that the stock is below the strike **at expiration**. The probability that the stock trades below the strike **at some point** before expiration is considerably higher, close to twice as high for options that are not far from the money. A put writer who intends to hold to expiration cares about the first number; a writer who will close or roll if the strike is breached cares about the second. The report uses the expiration figure and says so.

## How it is used in ranking

The CSP screener scores candidates on four components: annualised return on collateral, probability OTM, liquidity and fit of IV rank to the preferred range. Probability OTM carries 30% of that option-quality score, which itself is half of the final ranking alongside the stock's quality score and the consumer-trend signal. A put with a very high probability OTM but almost no premium does not rank well, and neither does a fat premium with a coin-flip chance of assignment; the ranking rewards the balance.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on the limits of pricing models: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Formulas and golden values in force in this app: PRD.md section 3.6.
