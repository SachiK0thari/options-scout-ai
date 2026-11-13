---
id: options-in-an-ira
title: "Options in an IRA: no margin, cash-secured strategies, and why holding periods stop mattering inside"
source: "IRS, Individual Retirement Arrangements (IRAs); FINRA, Margin Accounts investor page; FINRA Rule 2360"
url: https://www.irs.gov/retirement-plans/individual-retirement-arrangements-iras
kind: tax
level: intermediate
as_of: 2026-11-13
---

# Options in an IRA: no margin, cash-secured strategies, and why holding periods stop mattering inside

An **individual retirement arrangement (IRA)** is a tax-advantaged account for retirement savings. Many brokers allow options inside one, within limits that follow from how the tax code treats the account. The two strategies this app screens most often, cash-secured puts and covered calls on shares already owned, are the ones most commonly permitted. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## Why there is no margin lending in an IRA

A **margin loan** is money a broker lends against securities in the account, which is what allows a short put to be secured by a fraction of the strike. The Internal Revenue Code treats any part of an IRA that is pledged as security for a loan as distributed, which would make it taxable and, before age 59 1/2, subject to the additional tax described in Tax Topic 557. Brokers therefore do not extend margin loans in IRAs. Every short put must be fully secured by cash, every stock purchase paid in full, and every short call covered by shares or by a long call. Some brokers offer "limited margin" in an IRA, which means trading on unsettled funds without a loan, not borrowing.

## What brokers typically allow

With options approval under FINRA Rule 2360, many brokers permit **cash-secured puts** and **covered calls** in an IRA, and some permit defined-risk spreads, including the diagonal spread that makes up a **poor man's covered call** (a LEAPS plus a short call). Long calls such as LEAPS are allowed where the account is approved for buying options. Naked puts and short stock are not available, because both require borrowing. The permissions are set broker by broker; the FINRA margin page explains the lending side and why it is absent here.

## Gains inside the account

Inside a **traditional IRA**, gains, dividends and option premiums are not taxed when earned; tax is deferred until money is withdrawn, when it is generally taxed as ordinary income. Inside a **Roth IRA**, contributions are made with after-tax money and qualified withdrawals, including all the growth, are tax-free. In both cases the distinction between short-term and long-term gain that governs a taxable account does not apply inside the IRA: a put written and expired in 40 days and a LEAPS held for two years are treated the same, because neither produces a current tax event. Wash sale bookkeeping within the IRA is likewise irrelevant, with one important exception: a loss in a taxable account can be permanently disallowed if the replacement shares are bought in an IRA (see *Wash sales and options*).

## Contribution limits and cash

An IRA can only be funded up to an annual contribution limit, which the IRS IRA page states for the current year and which this document does not repeat because it changes. The practical consequence for an options writer is that cash consumed by an assignment cannot be topped up freely. Suppose an IRA holds $12,000 and the owner writes two $50 puts; assignment on both would require $10,000, leaving little room for anything else until shares are sold.

## What can go wrong

The tax shelter does not change the market risk: an assigned put in an IRA loses value with the stock exactly as it would elsewhere, and the loss cannot be deducted against other income because nothing inside the IRA is deductible. Early withdrawal to meet a goal outside retirement triggers tax and, usually, an additional tax (see *Early withdrawal from an IRA*). Finally, an IRA with options approval can still be restricted by the broker after a good-faith violation on unsettled funds.

## Where this shows up in OptionsScout

The Setup tab offers cash, margin and portfolio margin accounts; it has no separate IRA type. An IRA should be entered as a **cash** account (a request that says "IRA" or "Roth" is read that way), which gives the IRA treatment: return on collateral rather than return on margin, no Reg T sizing, and the account's cash as the hard ceiling. The Goals tab does not know which account funds a goal, so it does not hold IRA balances back for goals that fall before age 59 1/2; that judgment is the reader's.

## Sources

- IRS, Individual Retirement Arrangements (IRAs): https://www.irs.gov/retirement-plans/individual-retirement-arrangements-iras
- FINRA, Margin Accounts investor page: https://www.finra.org/investors/investing/investment-accounts/margin-accounts
- FINRA Rule 2360, Options: https://www.finra.org/rules-guidance/rulebook/finra-rules/2360
- IRS Tax Topic 557, Additional tax on early distributions from traditional and Roth IRAs: https://www.irs.gov/taxtopics/tc557
