---
id: what-is-an-etf
title: "What is an ETF: exchange-traded funds, SPY and QQQ, and why their options are liquid"
source: "SEC investor.gov, Mutual Funds and Exchange-Traded Funds (ETFs); OCC, Characteristics and Risks of Standardized Options, chapter III"
url: https://www.investor.gov/introduction-investing/investing-basics/investment-products/mutual-funds-and-exchange-traded-funds-etfs
kind: basics
level: beginner
as_of: 2026-11-13
---

# What is an ETF: exchange-traded funds, SPY and QQQ, and why their options are liquid

An **exchange-traded fund (ETF)** is a pooled investment that holds a basket of securities and whose shares trade on a stock exchange throughout the day, exactly like a stock. One ETF share is a slice of the whole basket. Most ETFs are **index funds**: they aim to hold the same securities, in the same proportions, as a published index such as the S&P 500, rather than trying to pick winners.

## ETFs versus mutual funds

A **mutual fund** is also a pooled basket, but its shares are bought from and sold back to the fund company itself, once per day, at the **net asset value (NAV)** computed after the close. An ETF differs in three practical ways. First, it trades on an exchange at a market price that can be a few cents above or below NAV, and it can be bought or sold at any moment the market is open. Second, because ETF shares trade between investors rather than with the fund, the fund rarely has to sell holdings to meet redemptions, which tends to make index ETFs more tax-efficient in a taxable account. Third, and most relevant here, listed **options** exist on many ETFs, whereas no options exist on mutual funds. The SEC's investor page covers the fee and structural differences in more detail.

## How ETF shares are created and redeemed

ETF shares come into existence through a mechanism called **creation and redemption**. Large institutions known as **authorized participants** deliver a basket of the underlying securities to the fund and receive a block of new ETF shares in return (creation), or deliver ETF shares and receive the basket back (redemption). Because an authorized participant can arbitrage any gap between the ETF's price and the value of its holdings, the market price is kept close to NAV, and the supply of ETF shares expands or contracts with demand instead of being fixed.

## SPY and QQQ

The two ETFs in this app's universe are **SPY**, the SPDR S&P 500 ETF, which holds the roughly 500 large U.S. companies in the S&P 500 index, and **QQQ**, the Invesco Nasdaq-100 ETF, which holds the 100 largest non-financial companies listed on the Nasdaq exchange. Both are weighted by market capitalisation, so the largest companies are the largest holdings. Owning one share of either gives a beginner exposure to hundreds of companies in one trade, which is why both carry the `diversified` tag in `config/quality_universe.yaml`.

## Why ETF options are liquid

**Liquidity** means a security can be bought or sold quickly, in size, without moving the price. SPY and QQQ options are among the most actively traded contracts in the world. Several features cause this: the underlying ETFs themselves trade tens of billions of dollars a day; thousands of institutions use the options to hedge whole portfolios; and strikes and expiries are listed densely, including multiple expiries per week. The result is tight bid-ask spreads and deep open interest, so a retail order to open or close a position fills near the quoted mid price. Options on a single large stock are usually liquid too, but seldom to the same degree.

## What can go wrong

An ETF is not immune to loss: if the S&P 500 falls 30%, SPY falls about 30%. Diversification across companies removes single-company risk, not market risk. Leveraged and inverse ETFs, which aim to deliver a multiple of a daily index move, behave very differently from SPY and QQQ and are not in this app's universe. Finally, a few ETFs trade thinly, with wide spreads and prices that drift from NAV during stress; the liquidity described above belongs to the largest funds, not to the category.

## Where this shows up in OptionsScout

SPY and QQQ appear in the Quality Screen tab with sector `ETF` and pass the same deterministic quality gate as every stock. In the Candidates tab they often show the tightest bid-ask spreads relative to the screener's cap of 10% of mid, and the Portfolio & Risk tab treats a short put on either as broad-market exposure when it totals dollar delta. The Learn tab's beta document uses SPY as the benchmark against which every other holding is measured.

## Sources

- SEC investor.gov, *Mutual Funds and Exchange-Traded Funds (ETFs)*: https://www.investor.gov/introduction-investing/investing-basics/investment-products/mutual-funds-and-exchange-traded-funds-etfs
- OCC, *Characteristics and Risks of Standardized Options*, chapter III (options on equity securities, including ETFs): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute education: https://www.cboe.com/education/
