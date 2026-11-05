---
id: beta
title: "Beta: sensitivity to SPY, what 1.2 means, beta-weighted exposure, and the limits of the number"
source: "SEC investor.gov, Glossary (beta); Cboe Options Institute education"
url: https://www.investor.gov/introduction-investing/investing-basics/glossary
kind: basics
level: intermediate
as_of: 2026-11-04
---

# Beta: sensitivity to SPY, what 1.2 means, beta-weighted exposure, and the limits of the number

**Beta** measures how much a stock has tended to move when the overall market moves. It is estimated from history by regressing the stock's daily or weekly returns on the returns of a benchmark index; in U.S. practice the benchmark is the S&P 500, and because SPY tracks that index, "beta to SPY" and "beta to the S&P 500" are used interchangeably. The benchmark has a beta of exactly 1 by definition.

## What a beta of 1.2 means

A beta of 1.2 says that, over the estimation period, the stock on average moved 1.2% for every 1% move in SPY, in the same direction. A beta of 0.7 describes a stock that moved about 0.7% for each 1% market move, typical of consumer staples and utilities. A beta near zero means little relation to the market, and a negative beta, which is rare among stocks, means the holding tended to move opposite to it. Beta describes the market-related part of a stock's movement only; a 1.2-beta stock also has its own idiosyncratic moves that beta says nothing about.

## Beta-weighted exposure of a holdings list

Beta lets positions in different stocks be expressed in one common unit: the equivalent number of dollars of SPY. Multiply each position's market value by its beta and sum. Suppose a holdings list contains $20,000 of a 1.2-beta stock, $15,000 of a 0.8-beta stock and $10,000 of SPY. The beta-weighted exposure is 20,000 x 1.2 + 15,000 x 0.8 + 10,000 x 1.0 = $46,000, against $45,000 of actual holdings: the portfolio behaves roughly like $46,000 of the index when the market moves.

For options the same idea uses **dollar delta**, the option's delta times 100 times the stock price, as the position value. A short put with a -0.25 delta on a $50 stock has a dollar delta of about +$1,250 (the short put gains as the stock rises), and on a 1.2-beta stock contributes about $1,500 of beta-weighted exposure. Summing across a whole account gives a single figure: how much the account would be expected to gain or lose, in dollars, for a 1% market move. A portfolio of $45,000 with a beta-weighted exposure of $46,000 would be expected to lose roughly $4,600 in a 10% market decline, before any idiosyncratic moves.

## Limitations of beta

Beta is a historical average, and it is unstable. Estimated over two years of daily data it can differ materially from the same stock's beta over five years of monthly data. It tends to rise in a crisis, when correlations across stocks increase, so a portfolio built to a target beta in calm markets often turns out to be more exposed than planned when a decline arrives. Beta also captures only the linear, market-related component of risk; a stock can have a beta of 1.0 and still fall 40% on its own news. For options the problem compounds: delta itself changes as the stock moves, so the dollar delta of a short put grows as the stock falls toward the strike, and the beta-weighted figure computed today understates exposure after a drop. Finally, beta against SPY says little about a holding whose risk is driven by something other than the U.S. stock market, such as a foreign stock or a commodity producer.

## What can go wrong

Treating beta-weighted exposure as a precise forecast is the main error. The number is an estimate of an average relationship and carries wide uncertainty; the realised loss in any particular decline can be well above or below it.

## Where this shows up in OptionsScout

The Portfolio & Risk tab reports total dollar delta of the proposed positions and applies the **max dollar delta** constraint (0.8x, 1.0x or 1.5x account value for the conservative, balanced and aggressive profiles). The planned holdings section adds beta-weighted exposure of the user's existing shares against SPY, so the combined figure shows how much of the account's result depends on a single market move; the -10/-20/-30% stress test is the same question asked three ways. The Scout chat cites this document when explaining why two accounts of equal size can have very different stress-test losses.

## Sources

- SEC investor.gov, *Glossary* (beta): https://www.investor.gov/introduction-investing/investing-basics/glossary
- Cboe Options Institute education (delta and portfolio hedging): https://www.cboe.com/education/
- OCC, *Characteristics and Risks of Standardized Options* (risk of short option positions): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
