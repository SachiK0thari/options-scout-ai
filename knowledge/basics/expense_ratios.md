---
id: expense-ratios
title: "Expense ratios: what a fund charges each year and how it compounds"
source: "SEC investor.gov, Mutual Funds and Exchange-Traded Funds (ETFs), fees and expenses; SPDR S&P 500 ETF Trust and Invesco QQQ Trust fund documents"
url: https://www.investor.gov/introduction-investing/investing-basics/investment-products/mutual-funds-and-exchange-traded-funds-etfs
kind: basics
level: beginner
as_of: 2026-11-04
---

# Expense ratios

An **expense ratio** is the annual cost of running a mutual fund or exchange-traded fund (ETF), expressed as a percentage of the money invested in it. It covers the manager's fee, administration, custody, legal and accounting costs, and index licensing. The fund does not send a bill. It deducts the cost a little each day from the fund's assets, so the price of a share already reflects it. An investor holding $10,000 in a fund with a 0.20% expense ratio pays about $20 a year without ever seeing a line item.

## Where the number comes from

Every fund publishes its expense ratio in its prospectus and fact sheet, and the SEC's investor.gov pages on mutual funds and ETFs explain how to read the fee table. Two of the ETFs in this app's universe illustrate the range among large index funds. The SPDR S&P 500 ETF Trust (SPY) reports an expense ratio of about 0.09%, and the Invesco QQQ Trust (QQQ) about 0.20%, according to the fund documents as of this writing. The word "about" matters: sponsors change fees, and the current figure is the one in the latest prospectus, not the one in a knowledge document.

## Why a small number matters over time

Fees compound in reverse. A fund that earns the index return minus 0.20% every year falls a little further behind the index each year, and the gap grows with the balance. Suppose an investor puts $10,000 into two funds that both track an index assumed to return 7% a year for 30 years. With a 0.09% expense ratio the balance grows at 6.91% to roughly $74,200. With a 1.00% expense ratio it grows at 6.00% to roughly $57,400. The 0.91 percentage point difference in fees cost about $16,800, or more than one and a half times the original investment. These figures are arithmetic on stated assumptions, not a forecast of any fund's return.

## What the expense ratio does not include

The expense ratio is not the whole cost of owning a fund. It excludes brokerage commissions, the bid-ask spread paid when buying or selling ETF shares, and the taxes an investor owes on distributions and gains. Actively managed funds also carry trading costs inside the portfolio that are not in the ratio. Two funds with the same expense ratio can therefore have different all-in costs. The ratio is also a poor way to compare funds that hold different things: a 0.20% fee on a concentrated technology index and a 0.09% fee on a broad market index buy different exposures, and the fee is the smaller of the two differences.

## Risks and limitations

A low expense ratio does not make a fund low risk. SPY and QQQ fell by roughly a third and more during past bear markets regardless of their fees. The ratio is also a snapshot: a sponsor can raise it, a fund can close or merge, and the figure in a third-party screener can lag the prospectus. Finally, the ratio says nothing about tracking error, the gap between a fund's return and its index after costs, which can be larger than the fee itself in thinly traded funds.

## Where this shows up in OptionsScout

The holdings section of the Portfolio & Risk tab computes a **weighted expense ratio** for the ETFs a user enters: each ETF's expense ratio from `config/etf_expense_ratios.yaml`, weighted by its share of the portfolio's market value. A portfolio that is 60% SPY and 40% QQQ would show about 0.13% at the ratios above. The number is deterministic Python, the Portfolio agent only describes it, and individual stocks contribute zero because they carry no fund fee. The figure is shown so the user can see the annual drag on the part of the account that a cash-secured put's collateral or a LEAPS position would sit alongside.

## Sources

- SEC investor.gov, Mutual Funds and Exchange-Traded Funds (ETFs), including the section on fees and expenses: https://www.investor.gov/introduction-investing/investing-basics/investment-products/mutual-funds-and-exchange-traded-funds-etfs
- SEC investor.gov, Compound Interest Calculator, for reproducing the fee-drag example: https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator
- SEC investor.gov, Glossary (expense ratio, prospectus): https://www.investor.gov/introduction-investing/investing-basics/glossary
