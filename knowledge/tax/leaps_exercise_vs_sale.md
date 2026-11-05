---
id: leaps-exercise-vs-sale
title: "LEAPS: exercise versus sale, and why a roll warning is not a tax signal"
source: "IRS Publication 550, Investment Income and Expenses, chapter 4, Holders of puts and calls; Holding period"
url: https://www.irs.gov/publications/p550
kind: tax
level: advanced
as_of: 2026-11-04
---

# LEAPS: exercise versus sale, and why a roll warning is not a tax signal

A holder of a profitable **LEAPS call** (a long-dated call, screened by this app at 0.70-0.85 delta) eventually faces a choice: sell the option, exercise it into shares, or roll it into a later expiry. Each has a different tax shape. IRS Publication 550's section "Holders of puts and calls" sets out the mechanics; this document lines them up side by side. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## Selling: a realised gain or loss now

Selling the call closes the position and realises a capital gain or loss equal to proceeds minus the premium paid. The character depends only on how long the option was held: more than one year is long-term, one year or less is short-term (Tax Topic 409). Suppose a LEAPS with a $100 strike was bought for $25.00 per share and is sold after thirteen months for $40.00. The holder reports a $1,500 long-term capital gain for the year of sale and has no further position.

## Exercising: no gain yet, a new clock

Exercising realises nothing. Publication 550 says the cost of the call is added to the basis of the shares, so the shares in the example have a basis of $125 per share (strike plus premium), and the holder pays $10,000 in cash to take delivery. The holding period of the shares begins the day after exercise; the thirteen months do not carry over. Any gain in the option is deferred until the shares are sold, which may be years later, but if the shares are sold within a year of exercise the entire gain, including the part earned while holding the option, is short-term. Exercise also forfeits the remaining time value: the holder could have sold the option for $40.00 but receives shares worth, say, $138, so $2.00 per share of extrinsic value is given up.

## Rolling: a sale in disguise

A **roll** means selling the current LEAPS and buying another with a later expiration. For tax purposes it is simply a sale followed by a purchase. The sale realises the gain or loss on the old contract exactly as in the first section, and the new contract starts its own holding period from the day after purchase. The word "roll" describes the trade, not a tax deferral.

## Why the roll warning is a trading signal

This app warns when a held LEAPS is approaching the window in which time decay accelerates and the delta no longer tracks the stock the way the screener intended. That warning is derived from the option's remaining days to expiration and its Greeks. It says nothing about the holder's purchase date, tax year or holding period, and acting on it may realise a short-term gain a few weeks before it would have turned long-term, or realise a gain in a year when the holder would rather not. The app informs the first decision only.

## What can go wrong

The common errors are treating a roll as tax-neutral, assuming the LEAPS holding period transfers to shares on exercise, and exercising without the cash to pay for the shares, which in a margin account creates a loan and in a cash account can fail. There is also a straddle angle: if the LEAPS is the long leg of a poor man's covered call, section 1092 may defer losses and suspend holding periods, so the clean picture above should be checked against Publication 550's "Straddles" section before relying on it.

## Where this shows up in OptionsScout

The Portfolio & Risk tab's roll warning for LEAPS and PMCC positions is labelled as a trading signal, and the Compliance agent requires any Scout chat answer that touches on exercising or selling to include the tax disclaimer and a pointer to this document rather than a recommendation.

## Sources

- IRS Publication 550, *Investment Income and Expenses*, chapter 4, "Holders of puts and calls": https://www.irs.gov/publications/p550
- IRS Tax Topic 409, Capital gains and losses: https://www.irs.gov/taxtopics/tc409
- 26 U.S.C. Section 1092, straddles: https://www.law.cornell.edu/uscode/text/26/1092
