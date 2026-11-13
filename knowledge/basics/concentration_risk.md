---
id: concentration-risk
title: "Concentration risk: single names, sectors, and how assignment on a put quietly increases it"
source: "SEC investor.gov, Introduction to Investing (diversification); OCC, Characteristics and Risks of Standardized Options, chapter X"
url: https://www.investor.gov/introduction-investing
kind: basics
level: beginner
as_of: 2026-11-13
---

# Concentration risk: single names, sectors, and how assignment on a put quietly increases it

**Concentration risk** is the risk that too much of a portfolio depends on one outcome. It is the mirror image of diversification: where diversification spreads exposure across unrelated holdings, concentration piles it onto one company, one sector, one country or one theme. A concentrated portfolio can do very well when the bet is right; the risk is that a single piece of bad news decides the result.

## Single-name concentration

**Single-name** concentration is the share of a portfolio tied to one company. Suppose an account of $100,000 holds $35,000 of one stock. A 40% fall in that stock, which large companies do suffer in bad years, removes $14,000, or 14% of the account, regardless of what everything else does. Investors drift into single-name concentration in ordinary ways: a holding that has risen a great deal, shares received as employee compensation, or a stock that was bought several times because it felt familiar. The SEC's introduction to investing singles out employer stock as a common example.

## Sector concentration

**Sector** concentration is the same idea applied to a group of companies that share a business environment. Ten technology stocks are ten names but one sector exposure; the *Diversification* document explains why their outcomes are correlated. Sector concentration is harder to see than single-name concentration because each position looks small, and it is the form that index concentration takes: at times the largest handful of companies in the S&P 500 have accounted for a third of the index, so even a broad fund can carry a concentrated bet.

## How assignment on a cash-secured put increases concentration

A short put looks like a small position: a $120 premium against a $50 strike. But if the stock falls through the strike and the put is assigned, the writer buys 100 shares for $5,000. The position has changed in kind, from an option worth a few hundred dollars to $5,000 of stock, at a moment when the stock has already fallen.

Now suppose the writer already owns 200 shares of the same company, worth $10,000 before the fall, in a $100,000 account. Before assignment the name was 10% of the account. After the stock drops to $45 and the put is assigned, the writer owns 300 shares worth $13,500, or about 14% of a slightly smaller account, and the shares were bought at the worst moment. If the writer also sold puts on two other companies in the same sector, which tend to fall together, sector concentration jumps at the same time. The OCC disclosure document's warning that a put writer may be assigned when the stock has fallen sharply has this quieter consequence: assignment does not just create a loss, it reshapes the portfolio toward whatever just went down.

## What can go wrong

Concentration limits measured on today's holdings miss this effect, because a short put counts as a small option position until the day it becomes shares. A writer can be within every limit on Monday and far outside them on Friday after a market drop assigns several puts at once. Correlated assignments are the mechanism by which a "diversified" put-selling program turns into a concentrated stock portfolio during exactly the decline the writer most wanted to avoid.

## Where this shows up in OptionsScout

The Portfolio & Risk tab applies {{risk.constraints_margin}} constraints to the proposed positions on a margin account ({{risk.constraints_cash}} on a cash account, where margin usage does not apply), including **max exposure per ticker** ({{risk.conservative.max_exposure_per_ticker}}, {{risk.balanced.max_exposure_per_ticker}} or {{risk.aggressive.max_exposure_per_ticker}} of account value in realistic loss for the conservative, balanced and aggressive profiles) and **max per sector** ({{risk.conservative.max_per_sector}}, {{risk.balanced.max_per_sector}} or {{risk.aggressive.max_per_sector}}). When the user enters holdings, a further constraint, **max concentration after assignment**, applies: for each put, the app adds the shares an assignment would deliver to the shares already held and rejects sizes that would push one name past {{risk.conservative.max_ticker_concentration_after_assignment}}, {{risk.balanced.max_ticker_concentration_after_assignment}} or {{risk.aggressive.max_ticker_concentration_after_assignment}} of holdings plus buying power. It works per ticker, not per sector, and it cannot see shares held at other brokers that were not entered.

## Sources

- SEC investor.gov, *Introduction to Investing* (diversification, employer stock): https://www.investor.gov/introduction-investing
- OCC, *Characteristics and Risks of Standardized Options*, chapter X (risks of put writers): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
