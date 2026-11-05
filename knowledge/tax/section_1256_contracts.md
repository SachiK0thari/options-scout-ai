---
id: section-1256-contracts
title: "Section 1256 contracts: 60/40 treatment, mark-to-market, and why SPY and QQQ options are not included"
source: "26 U.S.C. §1256 (Section 1256 contracts marked to market); IRS Form 6781; IRS Publication 550, chapter 4, Section 1256 Contracts Marked to Market"
url: https://www.law.cornell.edu/uscode/text/26/1256
kind: tax
level: advanced
as_of: 2026-11-04
---

# Section 1256 contracts: 60/40 treatment, mark-to-market, and why SPY and QQQ options are not included

Section 1256 of the Internal Revenue Code gives a short list of derivative contracts a special tax regime that differs from the ordinary capital gain rules in two ways. It comes up often in options discussions and is often misapplied to products it does not cover. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## The two special rules

**Mark-to-market.** A Section 1256 contract still open on the last business day of the tax year is treated as sold at its fair market value on that day. The unrealised gain or loss is recognised, and the contract's basis is adjusted so the same gain is not counted again when it actually closes.

**The 60/40 rule.** Any gain or loss on a Section 1256 contract, whether from the year-end mark or from an actual close, is treated as 60 percent long-term capital gain or loss and 40 percent short-term, regardless of how long the contract was held. The results are reported on **Form 6781**, Part I, and flow to Schedule D. Publication 550 covers this under "Section 1256 Contracts Marked to Market". A separate election allows certain net losses on these contracts to be carried back to earlier years; the form instructions explain its conditions.

## Which products qualify

Section 1256(b) lists regulated futures contracts, foreign currency contracts, **nonequity options**, dealer equity options and dealer securities futures contracts. For an individual investor the relevant category is the nonequity option: a listed option that is not an **equity option**. An equity option is defined in section 1256(g)(6) as an option to buy or sell stock, or an option whose value is determined by reference to a narrow-based stock index. Options on a **broad-based** stock index are therefore nonequity options. Cash-settled index options such as those on the S&P 500 index (SPX) and the Nasdaq-100 index (NDX), and futures on those indices, are the standard examples of Section 1256 contracts.

## Why SPY and QQQ options are not Section 1256 contracts

SPY and QQQ are exchange-traded funds whose shares trade like stock. An option on SPY is an option to buy or sell 100 shares of the fund, which makes it an equity option under section 1256(g)(6), not a nonequity option. That the fund tracks a broad-based index does not change what the option delivers. Options on SPY and QQQ, the two ETFs in this app's universe, are taxed like any other equity option: a writer's gain is short-term under section 1234(b), a holder's gain or loss follows the ordinary holding period test, and nothing is marked to market at year-end. Nothing this app screens, on any of its roughly thirty stocks or the two ETFs, is a Section 1256 contract.

## A short illustration

Suppose an investor sold an SPX put and an SPY put on the same day in December, and both were still open at year-end with an unrealised gain. The SPX put would be marked to market and the gain split 60/40 on Form 6781 for that year. The SPY put would be ignored until it expires or is closed, and then produce a short-term gain in the year it closes.

## What can go wrong

The frequent error is assuming an ETF option "counts" as an index option, which misstates both the timing and the character of the gain. The opposite error is holding an SPX position across year-end without expecting the mark-to-market gain. Broker 1099-B forms generally separate Section 1256 contracts into their own box, which helps, but the taxpayer remains responsible for classifying each product correctly.

## Where this shows up in OptionsScout

The quality universe in `config/quality_universe.yaml` contains only individual stocks plus SPY and QQQ, so the Candidates tab never shows a Section 1256 contract. The Tax & Accounts page in Learn links here so a user who asks the Scout chat about "60/40 treatment" gets the reason it does not apply to the app's candidates rather than a rate.

## Sources

- 26 U.S.C. Section 1256, Section 1256 contracts marked to market: https://www.law.cornell.edu/uscode/text/26/1256
- IRS Form 6781, Gains and Losses From Section 1256 Contracts and Straddles: https://www.irs.gov/forms-pubs/about-form-6781
- IRS Publication 550, *Investment Income and Expenses*, chapter 4, "Section 1256 Contracts Marked to Market": https://www.irs.gov/publications/p550
