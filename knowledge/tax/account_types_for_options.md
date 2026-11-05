---
id: account-types-for-options
title: "Account types for options: cash, margin and IRA accounts for a CSP, LEAPS or PMCC writer"
source: "FINRA Rule 2360 (Options), including account approval requirements; FINRA, Margin Accounts investor page"
url: https://www.finra.org/rules-guidance/rulebook/finra-rules/2360
kind: tax
level: beginner
as_of: 2026-11-04
---

# Account types for options: cash, margin and IRA accounts for a CSP, LEAPS or PMCC writer

The same option trade can be allowed, restricted or impossible depending on the kind of account it is placed in. Three account types cover most individual investors: a **cash account**, a **margin account** and an **individual retirement arrangement (IRA)**. This document lines them up for the three strategies this app screens. The permissions described are typical; the actual rule is set by each broker within FINRA's framework. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## Options approval comes first

Before any options trade, FINRA Rule 2360 requires a broker to approve the account for options trading. The broker must collect information about the customer's finances, experience and objectives, deliver the OCC's options disclosure document, and obtain a signed options agreement. Brokers implement this as **approval levels** or tiers: covered calls and cash-secured puts at a low level, long calls and puts a step up, spreads higher, and uncovered (naked) writing at the top. The names and the number of levels vary by broker; the obligation to vet the customer does not.

## The three accounts

A **cash account** requires every purchase to be paid for in full and every short option to be fully secured by cash or by the underlying shares. There is no borrowing, so a cash-secured put ties up the strike times 100 minus the premium for the life of the trade. A **margin account** lets the broker lend against securities under Regulation T and FINRA Rule 4210, so a short put can be secured by a margin requirement smaller than the full strike; that is what a "naked" put is. An **IRA** is a tax-advantaged account in which the tax code effectively prevents margin lending (pledging IRA assets as loan security is treated as a distribution), so brokers run IRAs on a cash basis, though many allow a wider set of option strategies than a plain cash account once approved.

## Strategy by account

| Strategy | Cash account | Margin account | IRA |
|---|---|---|---|
| Cash-secured put | Generally allowed with approval | Allowed; may be held as a naked put instead | Allowed at many brokers with approval |
| LEAPS call (long) | Allowed with approval; paid in full | Allowed; may be marginable | Allowed at many brokers |
| PMCC (LEAPS plus short call) | Often not allowed; spreads need margin at most brokers | Allowed with spread-level approval | Allowed at some brokers as a defined-risk spread |

A **naked put**, a short put secured by margin rather than full cash, needs a margin account and the broker's highest approval level; it is not screened by this app. A **PMCC** is a diagonal spread, so it needs spread approval wherever it is placed.

## What can go wrong

An investor approved for cash-secured puts but not for spreads cannot place the short call of a PMCC and may be left with an unhedged LEAPS. A margin account makes it possible to write more puts than the cash would cover, and the FINRA margin page describes the margin call and forced liquidation that follow a decline. Assignment in an IRA consumes cash that can only be replaced within annual contribution limits. In any account, assignment of a cash-secured put requires the full purchase price to be available; the broker holds it for exactly that reason.

## Where this shows up in OptionsScout

The Setup tab asks which account type the user is working with and uses the answer to decide whether to show return on collateral (cash and IRA) or return on margin (margin account), and the Portfolio & Risk tab applies the matching constraint. The planned Tax & Accounts page in Learn reproduces the table above and reminds the user that the app never connects to a brokerage, so the broker's own approval level is the one that governs.

## Sources

- FINRA Rule 2360, Options, including paragraph (b)(16) on opening of accounts: https://www.finra.org/rules-guidance/rulebook/finra-rules/2360
- FINRA, Margin Accounts investor page: https://www.finra.org/investors/investing/investment-accounts/margin-accounts
- FINRA, Options investor page: https://www.finra.org/investors/investing/investment-products/options
- IRS, Individual Retirement Arrangements (IRAs): https://www.irs.gov/retirement-plans/individual-retirement-arrangements-iras
