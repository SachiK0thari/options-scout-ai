---
id: iv-skew-and-term-structure
title: "Implied volatility skew and term structure: why OTM puts carry more IV and what it means for a put seller"
source: "Cboe Options Institute (volatility education); Cboe VIX index; OCC, Characteristics and Risks of Standardized Options"
url: https://www.cboe.com/education/
kind: concepts
level: advanced
as_of: 2026-11-04
---

# Implied volatility skew and term structure

**Implied volatility** (IV) is the volatility number that, put into an option pricing model such as Black-Scholes-Merton with the known strike, time, stock price and interest rate, reproduces the option's market price. If every option on a stock were priced from one view of the future, IV would be the same across strikes and expirations. It is not, and the two ways it varies are called **skew** (across strikes) and **term structure** (across expirations).

## Put skew

For equity and equity-index options, IV is higher for lower strikes. Suppose a stock trades at $100 with 40 days to expiration, and the at-the-money option has an IV of 25%. A $90 put might show 30% and a $110 call 22%. Plotted against strike the curve slopes down to the right, and the pattern is called **put skew** or, from its shape, the smirk. Three explanations are usually given:

- **Demand for protection.** Holders of stock buy out-of-the-money puts as insurance and are less interested in selling them, so put prices, and therefore put IV, are bid up.
- **Jump risk.** Stock prices fall faster than they rise. A pricing model that assumes smooth, symmetric moves underprices the chance of a sudden large drop, and the market corrects that by paying more for low strikes.
- **The leverage effect.** When a stock falls, the firm's debt is a larger fraction of its value and realised volatility tends to rise, so a lower price and higher volatility arrive together.

Index skew has been steep since the 1987 crash; single-stock skew is flatter but present.

## Term structure

Plotting at-the-money IV against expiration gives the **term structure**. In calm markets it slopes upward, with near-dated options showing lower IV than far-dated ones; by analogy with futures this is called **contango**. In stressed markets the curve inverts, near-dated IV exceeding far-dated, called **backwardation**: the market expects the current turbulence to fade. The Cboe VIX index, which measures 30-day S&P 500 implied volatility, makes this visible for the index. For individual stocks the curve also carries a bump at the expiration containing the next earnings date, because a known announcement concentrates uncertainty into a single day.

## What it means for a put seller

A cash-secured put at 0.15-0.30 delta is an out-of-the-money put, which is exactly where skew raises IV above the at-the-money figure. The premium a writer collects is therefore richer than a flat-volatility model would suggest. That is not a gift. Skew exists because the left tail is fatter than the model assumes, and the put seller is being paid for carrying that tail, which is the same scenario the app's realistic-loss figure (a 30% drop at expiry) measures. First, the IV rank the app reports is based on at-the-money IV and does not show how steep the skew is on a given day; two stocks with the same ATM IV can price their 0.20-delta puts quite differently. Second, in a selloff skew typically steepens as well as shifting up, so the cost to buy back a short put rises by more than the ATM move suggests.

Term structure matters at entry. In backwardation the near-dated premium looks unusually rich, but the reason is that the market expects large moves soon. The screener's rule excluding expirations that contain an earnings date removes the most predictable term-structure bump.

## What can go wrong

Skew and term structure are read from quoted prices, and delayed or wide quotes make the curves noisy, especially for far-out-of-the-money strikes. The explanations above are descriptive, not predictive: a steep skew says protection is expensive, not that a drop is coming. IV is also model-dependent; two vendors can quote different IVs for the same option.

## Where this shows up in OptionsScout

The quality gate's rule that at-the-money IV must be at most 45% and the CSP screener's soft preference for an IV rank above 30% both use ATM IV, so the app does not compute or display skew directly; the delta column is the closest proxy, since the same delta on a steeper skew yields a larger premium. The *Volatility regime* document explains how the VIX percentile tilts the allocation between CSPs and LEAPS, which is a term-structure-adjacent signal.

## Sources

- Cboe Options Institute, volatility, skew and term structure education: https://www.cboe.com/education/
- Cboe VIX index: https://www.cboe.com/tradable_products/vix/
- OCC, *Characteristics and Risks of Standardized Options*, chapter X: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
