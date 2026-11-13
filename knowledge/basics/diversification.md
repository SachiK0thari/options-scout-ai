---
id: diversification
title: "Diversification: idiosyncratic versus market risk, and why five tech puts are one bet"
source: "SEC investor.gov, Introduction to Investing (diversification); Bogleheads wiki"
url: https://www.investor.gov/introduction-investing
kind: basics
level: beginner
as_of: 2026-11-13
---

# Diversification: idiosyncratic versus market risk, and why five tech puts are one bet

**Diversification** means holding investments whose outcomes do not all depend on the same thing, so that one bad result does not decide the whole portfolio. The SEC's introduction to investing describes it as the main tool an individual has for managing risk without giving up expected return. It works because the losses of one holding can be offset by the unaffected or rising value of others, but only when the holdings genuinely differ.

## Two kinds of risk

Investment risk divides into two parts. **Idiosyncratic risk** (also called specific or unsystematic risk) is the risk particular to one company or one industry: a failed product, a lawsuit, an accounting problem, a regulatory change aimed at one sector. **Market risk** (systematic risk) is the risk shared by all stocks: recessions, interest rate changes, wars, pandemics. Diversification can shrink the first kind almost to nothing, because the specific troubles of different companies are largely unrelated. It cannot remove the second. A portfolio of 500 stocks still falls when the whole market falls, which is what happened to the S&P 500 in 2008 and again in 2020 and 2022.

## How many holdings, and which ones

The count matters less than the correlation between the holdings. Two companies that sell the same thing to the same customers will tend to rise and fall together, so owning both removes little risk. Academic studies suggest that a few dozen stocks drawn from different sectors remove most idiosyncratic risk, while a hundred stocks from one sector do not. The usual dimensions along which investors diversify are sector (technology, healthcare, consumer staples and so on), company size, geography, and asset class (stocks, bonds, cash). An index fund such as SPY handles the first two within U.S. stocks in a single holding, which is why the Bogleheads approach treats a broad index fund as the starting point.

## Why five short puts on five tech names is not diversified

Suppose an investor sells cash-secured puts on five large technology companies, each at a 0.20 delta, each sized at 10% of the account. On paper there are five positions. In practice there is one bet: that large-cap technology does not fall 15% or more in the next 40 days. A sector-wide sell-off, a change in interest rate expectations that hits long-duration growth stocks, or a regulatory action against the industry would push all five puts into the money at once. The probability figures beside each candidate are computed one contract at a time and assume nothing about the others; the chance that all five are assigned together is far higher than the product of five independent probabilities would suggest, because the outcomes are correlated. The same five contracts spread across technology, healthcare, consumer staples, a retailer and an index ETF would still carry market risk, but far less sector risk.

## What can go wrong

In a severe market decline, correlations rise and almost everything falls together, so diversification offers the least protection exactly when it is most wanted. Diversification across many names also dilutes the effect of any one good decision, which is the price paid for the protection. An investor can also be diversified in name only: a dozen holdings that all depend on consumer spending, or on cheap credit, share a hidden common factor that only shows up in a downturn.

## Where this shows up in OptionsScout

Every ticker in `config/quality_universe.yaml` carries a **sector** field (Technology, Healthcare, Consumer Defensive, Consumer Cyclical, Communication Services, Financials, ETF and so on), and the Portfolio & Risk tab groups the realistic loss of the proposed positions by that field. One of the portfolio constraints, **max per sector**, caps the realistic loss in any single sector at 25%, 30% or 35% of account value for the conservative, balanced and aggressive profiles, and a separate **max exposure per ticker** constraint caps any one name. The holdings section of the same tab applies the same grouping to shares the user already owns, so the screen can show whether a new put would add to an existing sector tilt. The -10/-20/-30% stress test applies a single market-wide shock to every position, which is the market risk that no sector mix removes.

## Sources

- SEC investor.gov, *Introduction to Investing* (diversification and asset allocation): https://www.investor.gov/introduction-investing
- Bogleheads wiki, main page (index funds and diversification): https://www.bogleheads.org/wiki/Main_Page
- SEC investor.gov, *Mutual Funds and Exchange-Traded Funds (ETFs)*: https://www.investor.gov/introduction-investing/investing-basics/investment-products/mutual-funds-and-exchange-traded-funds-etfs
