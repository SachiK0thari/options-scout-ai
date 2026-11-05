---
id: qualified-covered-calls
title: "Qualified covered calls and the straddle rules: when a short call touches the shares' holding period"
source: "26 U.S.C. §1092 (straddles), including §1092(c)(4) qualified covered call options and §1092(f); IRS Publication 550, chapter 4, Straddles"
url: https://www.law.cornell.edu/uscode/text/26/1092
kind: tax
level: advanced
as_of: 2026-11-04
---

# Qualified covered calls and the straddle rules: when a short call touches the shares' holding period

Writing a call against shares you own looks like one position, but the tax code sees two that offset each other. Offsetting positions are the subject of the **straddle rules** in section 1092 of the Internal Revenue Code. Those rules can defer losses and suspend holding periods. An exception exists for ordinary covered calls, the **qualified covered call** (QCC), but it has conditions and does not fit every structure this app screens. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## What the straddle rules do

A **straddle**, in the section 1092 sense, is a set of offsetting positions in actively traded personal property, where holding one position substantially reduces the risk of loss on the other. The **loss deferral rule** says a loss realised on one leg can be deducted only to the extent it exceeds the unrecognised gain in the offsetting leg; the excess is carried to the next year. The **holding period rule** says the holding period of a position does not begin, or is suspended, while it is part of a straddle, unless the position was already held for more than one year when the straddle was created. Publication 550 explains both under "Straddles"; deferred losses are reported on Form 6781, Part II.

## The qualified covered call exception

Section 1092(c)(4) says a covered call is not a straddle if the call is a qualified covered call: it is traded on a national securities exchange, has more than 30 days to expiration when written, is not "deep in the money" as the statute defines it using a schedule of benchmark strikes relative to the stock price, is written by someone who is not an options dealer, and is not part of a larger straddle. Most out-of-the-money calls written 30 to 45 days out on owned shares meet these tests. The deep-in-the-money benchmark depends on the stock price and the strikes available; Publication 550 reproduces the schedule under "Qualified covered call options and optioned stock" and should be consulted rather than guessed.

## In-the-money qualified covered calls and the holding period

Even a qualified covered call is not entirely outside the rules. Section 1092(f) and Publication 550 say that if the stock has been held for one year or less and the writer sells an **in-the-money** qualified covered call, the holding period of the stock is suspended for as long as the call is outstanding. In-the-money calls written against newly assigned shares can therefore keep those shares short-term longer than the calendar suggests.

## Relevance to a poor man's covered call

A **poor man's covered call** (PMCC) pairs a long LEAPS call with a short call at a higher strike. The qualified covered call exception is written for calls covered by **stock**. In a PMCC the "stock" is itself an option, so the exception generally does not apply and the long LEAPS and short call are offsetting positions in the plain section 1092 sense. The loss deferral rule can then catch a loss on a short call bought back while the LEAPS carries an unrecognised gain, and the LEAPS holding period may be suspended while the short call is open. These are mechanisms, not conclusions; Publication 550's "Straddles" section and the Form 6781 instructions should be checked before filing.

## What can go wrong

The traps are writing a call with 30 or fewer days to expiry (it fails the QCC test), writing a call deeper in the money than the benchmark allows, and assuming a PMCC is a covered call for tax purposes. Each can turn an expected long-term gain short-term or defer a loss the writer planned to use.

## Where this shows up in OptionsScout

The PMCC screener in this app pairs each LEAPS with a 30-45 DTE short call, which keeps the short leg above the 30-day line, but the app does not test the deep-in-the-money benchmark and does not model straddle deferral. The Tax & Accounts page in Learn links to this document for any PMCC candidate.

## Sources

- 26 U.S.C. Section 1092, straddles, including section 1092(c)(4) and section 1092(f): https://www.law.cornell.edu/uscode/text/26/1092
- IRS Publication 550, *Investment Income and Expenses*, chapter 4, "Straddles" and "Qualified covered call options and optioned stock": https://www.irs.gov/publications/p550
- IRS Form 6781, Gains and Losses From Section 1256 Contracts and Straddles: https://www.irs.gov/forms-pubs/about-form-6781
