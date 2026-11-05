---
id: vega
title: "Vega and implied volatility: why option prices move when the stock does not"
source: "Cboe Options Institute (the Greeks and implied volatility); OCC disclosure document chapter X"
url: https://www.cboe.com/education/
kind: concepts
level: advanced
as_of: 2026-11-03
---

# Vega and implied volatility

**Implied volatility (IV)** is the volatility number that, plugged into an option pricing model, reproduces the option's current market price. It is the market's consensus forecast of how much the stock will move over the option's life, expressed as an annualised standard deviation: an IV of 25% says the market is pricing a typical one-year move of roughly ±25%, or about ±1.6% per trading day. IV is not observed; it is backed out of prices, which is why it changes whenever option prices change for reasons other than the stock moving.

**Vega** is the sensitivity of an option's price to a one-percentage-point change in implied volatility. It is positive for both calls and puts: higher IV means a wider range of possible outcomes, which makes every option more valuable. Vega is largest for at-the-money options with a long time to expiration and shrinks as options move away from the money or approach expiry.

## Who is long and who is short volatility

A premium seller is **short vega**. A cash-secured put written when IV is 30% loses money, before any stock move, if IV rises to 40%, because the put now costs more to buy back. The same rise would help a LEAPS buyer, who is **long vega**. This is the structural reason the allocation in this app tilts between the two strategies with the volatility regime: when the VIX percentile is high, premiums are rich and the plan shifts buying power from LEAPS to cash-secured puts; when it is low, LEAPS are cheap and the plan shifts the other way.

## Volatility crush and volatility spikes

Implied volatility tends to rise into scheduled events and collapse once the uncertainty resolves. The sharpest version is the **earnings crush**: an option bought the day before an earnings release can lose a large share of its value the next morning even if the stock moves in the right direction, because IV falls back to normal. A seller of that option profits from the crush. The opposite, a **volatility spike**, happens when the stock drops sharply and the market reprices the risk of further declines; a short put then suffers from the stock move and from vega at the same time. The stress test in this app models exactly that combination, applying a 50% increase in implied volatility alongside each −10%, −20% and −30% price shock.

## Implied versus realised volatility

**Realised** (or historical) volatility is what the stock actually did, measured from past closing prices; this app computes a 30-day figure, HV30. Implied volatility is what the market expects. On average implied runs a little above realised, the so-called volatility risk premium, which is the systematic edge a disciplined premium seller is trying to collect. The relationship is not reliable for any single stock in any single month, and a gap in the other direction, realised volatility far above implied, is the signature of a stock that has just surprised everyone. The quality gate rejects names whose HV30 or ATM IV is above its limits for that reason.

## Sources

- Cboe Options Institute, implied volatility and Greeks education: https://www.cboe.com/education/
- Cboe, the VIX Index and volatility products: https://www.cboe.com/tradable_products/vix/
- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on the effect of volatility changes on option values: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
