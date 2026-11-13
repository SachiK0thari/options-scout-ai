---
id: assignment-cost-basis
title: "Assignment and cost basis: how the premium folds into the shares you receive"
source: "IRS Publication 550, Investment Income and Expenses, chapter 4, Writers of puts and calls (puts exercised); Holding period"
url: https://www.irs.gov/publications/p550
kind: tax
level: intermediate
as_of: 2026-11-13
---

# Assignment and cost basis: how the premium folds into the shares you receive

**Assignment** is what happens to a put writer when the put holder exercises: the writer is required to buy 100 shares per contract at the strike price. For a cash-secured put writer this is the second branch of the trade, the one where the investor ends up owning the stock. The tax treatment of that moment is simpler than many expect, but it has two consequences that follow the shares for as long as they are held. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## No gain or loss at assignment

IRS Publication 550, in "Writers of puts and calls", states that if a put you write is exercised and you buy the underlying stock, you decrease your **basis** in the stock by the amount you received for the put. Nothing about the option is reported as a separate gain or loss. The premium, which would have been a short-term gain had the put expired, instead becomes part of the stock's cost. The writer's tax year in which the put was sold does not matter; the premium simply travels with the shares.

## The basis arithmetic

Basis is the figure a future sale is measured against. Suppose an investor writes one put with a $50 strike and receives a $1.20 premium. The put is assigned. The investor pays $5,000 for 100 shares. The basis is not $5,000; it is the strike minus the premium, $48.80 per share, or $4,880 for the lot, plus any commission paid on the assignment. If the shares are later sold at $55.00, the gain is $6.20 per share ($620), not $5.00. If they are sold at $47.00, the loss is $1.80 per share ($180), not $3.00. The premium does not disappear; it lowers the cost and so raises any later gain or shrinks any later loss by the same amount.

## The holding period starts over

The shares acquired by assignment are new property. Publication 550's holding period rules say the clock for stock bought through an option begins on the day after the shares are acquired, which for an assigned put is the exercise date. The weeks the put was open do not count. An investor who wrote 30-45 day puts for a year and was finally assigned has shares with a holding period measured in days, and a sale within the next twelve months produces a short-term result under the more-than-one-year test described in Tax Topic 409. The document *Short-term vs long-term* covers that test.

## What can go wrong

Three things cause confusion. First, brokers report the adjusted basis for shares acquired through options granted or acquired after 2013 (these are "covered securities"), but a reader who keeps a separate spreadsheet may double count the premium as both a gain and a basis reduction. Second, the stock usually arrives below the strike, often well below it; the reduced basis is a tax fact, not a cushion against the market loss, and the app's realistic-loss figure (a 30% drop at expiry) is the number to keep in mind. Third, if the investor sold the same stock at a loss within 30 days before or after the assignment, the wash sale rule in section 1091 can disallow that loss and push it into the basis of the new shares; see *Wash sales and options*.

## Where this shows up in OptionsScout

The Candidates tab lists the breakeven of every CSP as strike minus premium, which happens to equal the tax basis per share an assigned writer would start with, before commissions. The holdings section in Portfolio & Risk lets a user record shares with a cost basis per share, such as this one, but not an acquisition date, so it cannot show how far a holding is from the one-year mark; it does not compute a tax figure either, because the broker's records are the ones that matter on Form 8949.

## Sources

- IRS Publication 550, *Investment Income and Expenses*, chapter 4, "Writers of puts and calls" and "Holding Period": https://www.irs.gov/publications/p550
- 26 U.S.C. Section 1234, options to buy or sell: https://www.law.cornell.edu/uscode/text/26/1234
- IRS Tax Topic 409, Capital gains and losses: https://www.irs.gov/taxtopics/tc409
