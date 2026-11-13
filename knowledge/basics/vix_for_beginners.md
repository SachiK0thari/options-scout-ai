---
id: vix-for-beginners
title: "The VIX for beginners: what the volatility index measures and how the app uses it"
source: "Cboe, VIX Index (Cboe Volatility Index) product page and methodology"
url: https://www.cboe.com/tradable_products/vix/
kind: basics
level: beginner
as_of: 2026-11-13
---

# The VIX for beginners

The **VIX** is the Cboe Volatility Index. It measures the **implied volatility** of S&P 500 index options over the next 30 days: the size of the move the options market is pricing in, derived from the prices of a wide strip of SPX puts and calls. It is quoted as an annualised percentage. A VIX of 20 means option prices are consistent with the S&P 500 moving about 20% a year, which works out to roughly 5.8% over the next 30 days (20 divided by the square root of 12). The VIX is not a stock, and it is not the market's direction; it is the price of insurance against moves in either direction.

## Why option prices contain a volatility number

An option is worth more when the underlying is expected to move more, because a bigger move makes a larger payoff more likely. Given an option's market price, the Black-Scholes model can be solved backward for the volatility that justifies it. That solved-for number is implied volatility. The VIX measures the same thing without a pricing model: Cboe computes it from a weighted strip of out-of-the-money S&P 500 put and call prices across a range of strikes, scaled to a 30-day horizon, and publishes it every 15 seconds during trading hours.

## Levels in plain words

Cboe's historical data show the VIX spending most of its life between the low teens and the mid-twenties. Readings below about 15 have accompanied calm, slowly rising markets. Readings in the twenties have accompanied ordinary corrections and election seasons. Readings above 30 have accompanied sharp sell-offs, and readings above 50 have been rare and confined to crises such as 2008 and March 2020. These describe the past and have no predictive power. A high VIX says insurance is expensive now; it does not say when the storm ends.

## What it means for the three screened strategies

For a put writer the VIX is the price of what is being sold. When implied volatility is high, premiums are richer, breakevens sit further below the current price, and the same strike pays more. The cost is that the market is paying more because it expects larger moves, including the one that leads to assignment. For a LEAPS buyer the relationship reverses: a long-dated call costs more when volatility is high, and a later fall in volatility reduces its value even if the stock does not move. Neither strategy is helped by a high VIX in both directions at once.

## How the app's volatility regime tilts allocation

OptionsScout computes a **volatility regime** from the VIX's percentile over the past year, not its raw level, so "high" means high relative to recent history. The thresholds are in `config/risk_profiles.yaml`. When the percentile is 70 or above, the engine shifts 10 percentage points of buying power from LEAPS to cash-secured puts, favouring the strategy that sells expensive insurance. When it is 30 or below, the shift runs the other way, toward LEAPS, which are cheaper to buy. The tilt never touches the cash reserve, so a conservative profile keeps its 35% in cash regardless of regime. The regime is reported with the VIX level, its percentile and the data source.

## What can go wrong

The VIX can rise much further after it is already "high": in March 2020 it went from the thirties to above 80 in two weeks. A put written because premiums looked rich at a 70th-percentile reading can be deep in the money a month later. The percentile is also relative to one year of history, so a year of unusual calm makes an ordinary reading look extreme. The VIX describes the S&P 500; a single stock's implied volatility can diverge from it widely around earnings, which is one reason the CSP screener excludes expiries that cross an earnings date.

## Where this shows up in OptionsScout

The regime node fetches the VIX from the delayed MarketData.app or Tradier feed, computes the one-year percentile, and writes the tilt into the allocation before any sizing runs. The Portfolio & Risk tab shows the allocation after the tilt and which direction it moved. If the VIX feed is unavailable the engine falls back to the untilted profile allocation and says so, because the app never invents a market value.

## Sources

- Cboe, VIX Index product page and methodology: https://www.cboe.com/tradable_products/vix/
- Cboe Options Institute, education on implied volatility: https://www.cboe.com/education/
- OptionsScout rule in force: `config/risk_profiles.yaml`, `regime_tilt` section.
