---
id: emergency-fund-first
title: "An emergency fund comes before any options position"
source: "SEC investor.gov, Introduction to Investing (define your goals, pay off debt, build an emergency fund)"
url: https://www.investor.gov/introduction-investing
kind: basics
level: beginner
as_of: 2026-11-04
---

# An emergency fund comes before any options position

An **emergency fund** is cash set aside to cover living expenses when income stops or a large unplanned bill arrives: a job loss, a medical cost, a car or home repair. The SEC's investor.gov introduction to investing lists building one, alongside paying down high-interest debt, as a step that comes before putting money into the markets. The usual rule of thumb is three to six months of essential expenses, held somewhere it can be withdrawn within a day or two without a loss of principal, such as a bank savings account or a money market fund.

## Why the order matters

Investments are meant to be left alone long enough to recover from declines. An emergency forces a sale at whatever the market price happens to be that week. Suppose an investor holds $12,000 of a stock fund and no cash, and loses a job during a month when the fund is down 25%. Covering $9,000 of expenses means selling at the low and turning a temporary decline into a permanent one. The same emergency with $9,000 in a savings account leaves the fund untouched to recover. The emergency fund is not an investment with a return; its job is to keep the real investments from being sold at the wrong time.

## Why a short put is a poor place for emergency cash

The collateral behind a cash-secured put looks like cash but does not behave like it. When a put writer sells one contract at a $50 strike, the broker holds about $5,000 (strike times 100, less the premium) for the life of the trade. That cash cannot be withdrawn without first buying the put back, which costs whatever the option is worth that day. In a market decline, the moment an emergency is most likely to coincide with a market shock, the put is worth more than the premium received, and closing it locks in a loss. If the put is instead assigned, the collateral has become 100 shares, which must be sold, possibly well below the strike, to raise cash. In both branches the "cash" was never truly liquid.

## What can go wrong without one

Options positions are also the ones most likely to demand cash unexpectedly. Assignment on a put uses the collateral; in a margin account a decline can trigger a margin call that must be met in days. An investor who meets those demands from an emergency fund has spent the emergency fund on a trade. An investor without one may be forced to close other positions. The limitation of any rule of thumb is that three to six months is a range, not a formula: a two-income household with stable jobs may sit at the low end, a self-employed person at the high end or beyond.

## Where this shows up in OptionsScout

The app does not ask about a user's emergency fund, because it cannot verify one, but a related idea is built into the Setup tab and the Compliance agent. `config/compliance.yaml` sets **minimum buying power** before a strategy is even described: $2,500 for cash-secured puts, $1,000 for LEAPS calls and $2,500 for a poor man's covered call. Below those amounts the app explains the strategy's mechanics but does not present sized candidates, on the reasoning that an account too small to secure one put at a $25 strike should not be told how many to write. Every risk profile also keeps a cash reserve (20% to 35% of buying power) that the sizing engine never allocates to options. Neither rule replaces an emergency fund held outside the brokerage account; they are floors inside it.

## Sources

- SEC investor.gov, Introduction to Investing, including the steps to take before investing: https://www.investor.gov/introduction-investing
- SEC investor.gov, Glossary (emergency fund, liquidity, money market fund): https://www.investor.gov/introduction-investing/investing-basics/glossary
- OCC, Characteristics and Risks of Standardized Options, chapter X, on the obligations of a put writer: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
