---
id: delta
title: "Delta: price sensitivity to the underlying, and a rough probability proxy"
source: "OCC disclosure document chapter X; Cboe Options Institute (the Greeks); PRD.md section 3.6"
url: https://www.cboe.com/education/
kind: concepts
level: intermediate
as_of: 2026-11-13
---

# Delta

**Delta** measures how much an option's price is expected to change for a one-dollar change in the price of the underlying stock, with everything else held constant. Call deltas run from 0 to 1 and put deltas from −1 to 0. A call with a delta of 0.80 gains about 80 cents when the stock rises a dollar; a put with a delta of −0.25 loses about 25 cents on the same move. Because an option contract covers 100 shares, traders often quote delta in share-equivalent terms: that 0.80 call behaves like 80 shares.

## Where delta comes from

In the Black-Scholes-Merton model used by this app, call delta equals e^(−qT) × N(d1) and put delta equals e^(−qT) × (N(d1) − 1), where N() is the standard normal cumulative distribution, q the dividend yield, T the time to expiration in years and d1 a function of the stock price, strike, volatility, interest rate and time. The golden test in this repository checks that a one-year, at-the-money option on a $100 stock with 20% volatility and a 5% rate has a call delta near 0.637 and a put delta near −0.363. Delta is not fixed: it rises toward 1 (for calls) as the option goes deeper in the money, falls toward 0 as it goes further out of the money, and converges to those extremes faster as expiration approaches.

## Delta as a probability proxy

Delta is often read as the approximate probability that the option finishes **in the money**: a 0.25 delta put is loosely a "25% chance of being assigned" put. This is a convenience, not a theorem. The model probabilities are N(d2) that a put expires worthless and N(−d2) that it finishes in the money and is assigned (for a call, N(d2) that it finishes in the money); these are close to delta but not identical, and for a put the absolute delta slightly understates the chance of assignment; the gap widens with longer time to expiration, higher volatility and larger dividends. This app reports **probability OTM** separately using N(d2) so the two are not confused, and uses delta for what it is: a measure of exposure.

## How the screeners use delta

- **Cash-secured puts** are selected with an absolute delta between 0.15 and 0.30: far enough out of the money that most expire worthless, close enough that the premium is meaningful.
- **LEAPS calls** are selected with a delta between 0.70 and 0.85: deep enough in the money to behave like stock and carry little extrinsic value, not so deep that the leverage disappears.
- **PMCC short calls** use a delta between 0.20 and 0.30, and the pair's net delta is LEAPS delta minus short call delta.

## Dollar delta at the portfolio level

Summing the share-equivalent exposure of every position gives the portfolio's **dollar delta**: delta × 100 × stock price × contracts, with the sign flipped for short puts so that a short put shows up as the positive stock exposure it really is. The risk engine caps total dollar delta at a multiple of account value (0.8× conservative, 1.0× balanced, 1.5× aggressive) so that a portfolio of "small" short puts cannot quietly accumulate the exposure of a fully invested, leveraged stock portfolio.

## Sources

- Cboe Options Institute, option Greeks education: https://www.cboe.com/education/
- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on how option values respond to the underlying: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Formulas implemented and golden-tested in this app: PRD.md section 3.6.
