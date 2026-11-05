---
id: hv-vs-iv
title: "Historical versus implied volatility: the variance risk premium and the two limits in the quality gate"
source: "Cboe Options Institute (volatility education); Cboe VIX index; config/quality_universe.yaml"
url: https://www.cboe.com/education/
kind: concepts
level: intermediate
as_of: 2026-11-04
---

# Historical versus implied volatility

Volatility is a measure of how much a stock's price moves. There are two ways to get a number for it, and they answer different questions. **Historical volatility** (HV), also called realised volatility, measures how much the stock did move over a past window. **Implied volatility** (IV) is the volatility the market is currently pricing into the stock's options, which is a statement about how much it is expected to move.

## Historical volatility

HV is the standard deviation of the stock's daily returns, usually log returns, over a chosen window, scaled to an annual figure by multiplying by the square root of the number of trading days in a year (about 252). **HV30** uses the last 30 trading days. Suppose a stock's daily returns over those 30 days have a standard deviation of 1.3%; the annualised HV30 is about 1.3% x 15.9, or roughly 21%. The number is entirely backward-looking.

## Implied volatility

IV is found by taking an option's market price and solving a pricing model backwards for the volatility that reproduces it. **ATM IV** is the figure for the at-the-money strike at a chosen expiration, usually around 30 days. It is forward-looking in the sense that it reflects what buyers and sellers will pay now, including their knowledge of scheduled events.

## The variance risk premium

Across most stocks and most periods, IV has tended to be higher than the volatility that was subsequently realised. The gap is called the **variance risk premium**. It is the compensation option buyers pay sellers for the risk that volatility will spike. Suppose a stock shows HV30 of 20% and ATM IV of 26%; the six-point gap is the premium a put writer is paid for insuring against moves the market considers more likely than the recent past suggests. The premium is an average, not a promise: in a crash, realised volatility exceeds what was implied by a wide margin, and sellers lose much more than they had been collecting.

## Why the gate uses both limits

The quality gate requires HV30 to be at most 35% and ATM IV to be at most 45%. Each limit catches something the other misses.

- A stock with low IV but high HV has been moving violently while its options are cheap, which usually means the market expects the turbulence to end, or that the option market is thin.
- A stock with low HV but high IV has been calm while its options are expensive, which almost always means a known event, an earnings date, a regulatory decision, a deal, is pending.
- A stock passing both has been calm and is expected to stay calm. The 35% and 45% ceilings are set well above the long-run figures for large, profitable companies, so they remove outliers rather than select the quietest names.

The gap between the two limits also allows for a normal variance risk premium: a stock at HV30 of 30% and IV of 40% passes, while a stock at 30% and 60% does not.

## What can go wrong

Thirty trading days is a short window; a single large move inflates HV30 for six weeks and then drops out of the window abruptly. HV is computed from closing prices and ignores intraday ranges. IV from delayed quotes can be stale, and for thinly traded options the ATM IV is sensitive to a wide spread. Both measures describe magnitude without direction.

## Where this shows up in OptionsScout

The Quality Screen tab lists HV30 and ATM IV for every stock in `config/quality_universe.yaml` alongside the other gate rules (price at least $20, average volume at least one million shares, no more than 20% below the 90-day high), and marks which rule failed when a name is excluded. The Scout chat cites the two thresholds rather than characterising a stock as calm or risky.

## Sources

- Cboe Options Institute, historical and implied volatility education: https://www.cboe.com/education/
- Cboe VIX index (the index-level implied volatility reference): https://www.cboe.com/tradable_products/vix/
- OCC, *Characteristics and Risks of Standardized Options*, chapter X: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
