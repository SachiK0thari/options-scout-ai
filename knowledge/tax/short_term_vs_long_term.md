---
id: short-term-vs-long-term
title: "Short-term vs long-term: the more-than-one-year test for shares and LEAPS"
source: "IRS Tax Topic 409, Capital gains and losses; IRS Publication 550, chapter 4, Holding Period; Rev. Rul. 66-7, 1966-1 C.B. 188"
url: https://www.irs.gov/taxtopics/tc409
kind: tax
level: beginner
as_of: 2026-11-13
---

# Short-term vs long-term: the more-than-one-year test for shares and LEAPS

When a capital asset such as a share or an option is sold, the gain or loss is labelled **short-term** or **long-term**. IRS Tax Topic 409 gives the test in one sentence: if the asset was held for more than one year before it was sold, the result is long-term; if it was held one year or less, it is short-term. The two kinds are netted separately and taxed under different rules. The label matters for anyone who ends up owning shares through a put assignment or who holds a long-dated call. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## Counting the days

IRS Publication 550's "Holding Period" section explains how to count. The holding period begins on the day **after** the asset is acquired and includes the day it is sold. To be long-term, the sale must occur after the same calendar date in the following year. Suppose shares were acquired on 10 March; a sale on 10 March of the next year is still one year, so short-term, while a sale on 11 March is more than one year, so long-term. There is no rounding; one day decides the label. The count is in calendar months, so an asset acquired on the last day of a month is long-term from the first day of the month after the twelfth: bought on 28 February 2023, it is long-term from 1 March 2024, not from 29 February (Revenue Ruling 66-7).

## Shares acquired by assignment

A cash-secured put writer who is assigned buys shares at the strike. Publication 550 treats those shares as acquired on the exercise date, so the holding period starts the day after assignment. The weeks or months the put was open beforehand do not count, and a chain of earlier puts on the same stock does not count either. The basis of the shares is the strike minus the premium received (see *Assignment and cost basis*). Shares sold within a year of assignment produce a short-term gain or loss.

## LEAPS calls

A **LEAPS call** is a long-dated call option, the kind this app screens at a 0.70-0.85 delta. Because it is itself a capital asset, the one-year test applies to the option. Sold after more than a year, it produces a long-term result; sold at one year or less, short-term. If it expires worthless, the loss is treated as realised on the expiration date and labelled by the time held up to then. If the holder exercises, the holding period of the shares received starts fresh the day after exercise and the option's time is not added; see *LEAPS and the holding period*.

## Written options are always short-term

The writer of a put or call, as opposed to the holder, cannot have a long-term result on the option. Section 1234(b) treats gain on expiry or from a closing purchase as short-term regardless of how long the option was open. For the 30-45 day puts in this app's CSP screener the point is academic, but it applies equally to a put written a year and a half out.

## What can go wrong

The one-year boundary is sharp, and nothing in a brokerage quote shows it, so sales a few days early are a common and avoidable mistake. Netting also surprises people: short-term losses first offset short-term gains and long-term losses offset long-term gains before any remaining loss crosses over, and an annual limit applies to losses deducted against other income with the excess carried forward. Tax Topic 409 explains the netting and states the current brackets and limits; this document does not, because they change and depend on the reader's own return.

## Where this shows up in OptionsScout

The holdings section in Portfolio & Risk records shares and cost basis but no acquisition dates, so the app cannot say whether a lot has crossed the one-year mark; the broker's lot detail shows it. Asked "is this long-term yet?", the Scout chat explains the test and the Compliance agent requires the answer to point to Tax Topic 409 for what the label means rather than to state a rate.

## Sources

- IRS Tax Topic 409, Capital gains and losses: https://www.irs.gov/taxtopics/tc409
- IRS Publication 550, *Investment Income and Expenses*, chapter 4, "Holding Period": https://www.irs.gov/publications/p550
- 26 U.S.C. Section 1234, options to buy or sell: https://www.law.cornell.edu/uscode/text/26/1234
