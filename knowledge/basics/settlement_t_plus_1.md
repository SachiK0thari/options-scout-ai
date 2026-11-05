---
id: settlement-t-plus-1
title: "Settlement and T+1: when a trade becomes final, and why CSP cash must be there at assignment"
source: "SEC press release 2023-29, SEC Finalizes Rules to Reduce Risks in Clearance and Settlement (T+1); OCC, Characteristics and Risks of Standardized Options"
url: https://www.sec.gov/news/press-release/2023-29
kind: basics
level: beginner
as_of: 2026-11-04
---

# Settlement and T+1: when a trade becomes final, and why CSP cash must be there at assignment

When an investor buys a stock, two things happen at different times. The **trade** is the moment buyer and seller agree on a price; it is what the confirmation shows. **Settlement** is the later moment when the shares are actually delivered to the buyer's account and the cash to the seller's. Until settlement, each side has a promise rather than the asset. The gap between the two is written as "T plus" a number of business days: **T+1** means the trade settles on the business day after the trade date.

## Why there is a gap at all

Settlement is run centrally by clearing organisations, which net up the day's trades between brokers and move securities and cash in bulk. The U.S. moved from T+5 to T+3 in 1995 and to T+2 in 2017. On February 15, 2023 the SEC adopted rules shortening the standard cycle to T+1, and the change took effect on May 28, 2024. The SEC's stated reasons were to reduce the credit, market and liquidity risk that builds up while trades are unsettled, which became visible during the volatility of early 2021.

## What settles T+1 today

- **Stocks and ETFs**: T+1.
- **Listed options**: the premium on an option trade settles on the next business day through the OCC, so T+1 as well.
- **Exercise and assignment**: when a put is assigned, the resulting stock purchase is itself a stock trade and settles T+1 from the exercise date.

The practical effect is that money from a stock sale is usually available to withdraw the next business day.

## Why the cash for a cash-secured put must be available at assignment

A **cash-secured put** is a short put backed by enough cash to buy the shares at the strike. Suppose a writer sells one put with a $50 strike. If the holder exercises, the writer is assigned and buys 100 shares for $5,000, and that purchase settles the next business day. The broker must have $5,000 of settled cash in the account to deliver.

This is why "cash-secured" is a condition held for the whole life of the trade, not just at the start. In a cash account the broker reserves the collateral (strike times 100, less the premium received) the moment the put is sold and keeps it reserved until the put is closed, expires or is assigned. The writer cannot spend that cash on something else in the meantime. If the account holds a stock sale that has not yet settled, or a deposit still in transit, that money does not count as settled cash and assignment can leave the account short.

## What can go wrong

In a cash account, buying with unsettled funds and then selling before they settle is a **good-faith violation**, and repeated violations lead brokers to restrict the account to settled cash only for 90 days. Assignment can happen on any trading day for American-style options, not only at expiry, so the cash must be there every day. Brokers also differ in how they display settled versus unsettled balances, and a beginner reading "buying power" as "cash" can be caught out. Finally, T+1 is the U.S. standard; other markets settle on other schedules, and corporate actions such as dividends key off settlement dates, which is why the ex-dividend and record dates now usually coincide.

## Where this shows up in OptionsScout

The Setup tab asks for account value and account type, and the collateral column in the Candidates tab shows the cash a CSP would tie up: strike times 100 minus the premium, for a cash account. The Portfolio & Risk tab's six constraints include a cap on total short-put notional relative to account value, which is a way of making sure the shares could actually be paid for if every put were assigned at once. The planned Tax & Accounts page in Learn will link to this document when it explains settled cash. The app never places trades, so settlement itself happens entirely at the user's broker.

## Sources

- SEC press release 2023-29, *SEC Finalizes Rules to Reduce Risks in Clearance and Settlement* (T+1 adopted February 15, 2023; compliance date May 28, 2024): https://www.sec.gov/news/press-release/2023-29
- OCC, *Characteristics and Risks of Standardized Options* (exercise, assignment and settlement): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- SEC investor.gov, *Glossary* (settlement date): https://www.investor.gov/introduction-investing/investing-basics/glossary
