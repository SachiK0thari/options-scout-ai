---
id: rebalancing
title: "Rebalancing: restoring a target allocation after drift"
source: "SEC investor.gov, Introduction to Investing (asset allocation and rebalancing)"
url: https://www.investor.gov/introduction-investing
kind: basics
level: beginner
as_of: 2026-11-04
---

# Rebalancing

**Rebalancing** is the act of returning a portfolio to its target allocation after market movements have pushed it away. An investor who decided on 60% stocks and 40% bonds, and finds the mix has become 70/30 after a strong year for stocks, rebalances by selling some stock and buying bonds until the split is 60/40 again. The SEC's investor.gov introduction describes rebalancing as the maintenance step that keeps an allocation, once chosen for the investor's risk tolerance and horizon, from quietly becoming a different one.

## Drift

**Drift** is the gap between the target and the current allocation. It arises because assets do not move together. Suppose a $100,000 account is split $60,000 stocks and $40,000 bonds. If stocks rise 25% and bonds are flat, the account is $115,000 with stocks at $75,000, or 65%. Nothing was traded, yet the investor now holds more equity risk than they chose. Drift also happens inside the stock sleeve: one position that doubles while the rest are flat becomes a concentration the investor never decided on. The *Concentration risk* document covers that case.

## How and when to rebalance

The two common triggers are the calendar and a band. Calendar rebalancing checks the allocation on a fixed date, such as once a year. Band rebalancing acts whenever an asset class strays more than a set amount, say five percentage points, from its target. Either can be done by selling the overweight asset and buying the underweight one, or, in an account receiving contributions, by directing new money to whatever is underweight, which avoids selling and any tax on gains. Rebalancing in a taxable account can realise capital gains; in a retirement account it does not, which is one reason many investors do their rebalancing there.

## Assignment as an unplanned rebalance

A cash-secured put that is assigned is a rebalance the investor did not schedule. Before assignment, the collateral is cash: it sits in the cash bucket of the allocation and carries no equity risk. Afterward, it is 100 shares of one company. Suppose a $50,000 account on the conservative profile holds $17,500 in reserve and has written two puts at a $40 strike on one stock, securing $8,000 in collateral. If both are assigned, $8,000 of cash becomes 200 shares of a single name worth, at an assigned price of $34, $6,800. The account has drifted toward one stock by 16 percentage points of its value in one step, and toward a stock that has just fallen. The investor must then decide whether to hold, sell, or write covered calls against the shares, each of which is a rebalancing decision made under pressure.

## What can go wrong

Rebalancing sells what has done well and buys what has done poorly, which is uncomfortable and is the reason it is often skipped. It also incurs costs: commissions, bid-ask spreads and, in taxable accounts, realised gains. Rebalancing too often churns the account for little benefit; too rarely lets drift accumulate until a decline reveals how much risk crept in. For a put writer, the specific risk is that assignment arrives in several names at once during a broad decline, so the unplanned rebalance toward stock happens exactly when stock has fallen and the cash reserve is most valuable.

## Where this shows up in OptionsScout

The holdings section of the Portfolio & Risk tab shows the current allocation as a donut chart with a **post-assignment overlay**: toggling it redraws the allocation as if every screened cash-secured put were assigned at its strike, so the user sees the drift that assignment would cause before writing the put. The per-ticker and per-sector constraints in the risk profile act as drift bands measured in realistic loss, and the sizing engine will not add a candidate that pushes a sector past its cap. The app does not place trades and does not rebalance anything; it shows the allocation the user's own decisions would produce.

## Sources

- SEC investor.gov, Introduction to Investing, on asset allocation and rebalancing: https://www.investor.gov/introduction-investing
- Bogleheads wiki, main page, with links to its articles on rebalancing and asset allocation: https://www.bogleheads.org/wiki/Main_Page
- OCC, Characteristics and Risks of Standardized Options, chapter X, on assignment of a short put: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
