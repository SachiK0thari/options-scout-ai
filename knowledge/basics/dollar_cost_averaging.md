---
id: dollar-cost-averaging
title: "Dollar-cost averaging: investing a fixed amount on a schedule"
source: "SEC investor.gov, Introduction to Investing; investor.gov Compound Interest Calculator (monthly contributions)"
url: https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator
kind: basics
level: beginner
as_of: 2026-11-04
---

# Dollar-cost averaging

**Dollar-cost averaging** (DCA) is the practice of investing a fixed dollar amount at regular intervals, such as $500 on the first of every month, regardless of the price that day. Because the amount is fixed, the investor buys more shares when the price is low and fewer when it is high. Most people who contribute to a workplace retirement plan are dollar-cost averaging without using the term, since a fixed percentage of each paycheck goes in on payday.

## The arithmetic

Suppose an investor puts $300 into a fund on each of four months when the price is $30, $20, $25 and $30. The purchases are 10, 15, 12 and 10 shares, 47 shares in total for $1,200, an average cost of $25.53 per share. The simple average of the four prices is $26.25. The average cost is lower because more shares were bought at the low price. This is a mechanical property of fixed-dollar buying, not a market insight, and it holds whatever the sequence of prices.

## What DCA does

DCA removes the decision of when to invest, which is the decision investors most often get wrong by waiting. It converts a lump of savings into a habit that does not depend on a view of the market. It also spreads the entry over time, so an investor who starts the month before a 20% decline has bought only one twelfth of a year's contributions at the high price. For money that arrives over time, such as salary, DCA is simply the only option; the question of lump sum versus schedule does not arise.

## What DCA does not do

DCA does not raise expected return. For money already in hand, investing it all at once has historically produced a higher ending balance more often than spreading it over a year, because markets rise more years than they fall and the un-invested portion sits in cash. DCA trades some expected return for a smaller chance of a bad entry. It does not protect against a long decline: an investor who averages into a fund that falls for three years has a lower average cost and a loss. And it does not substitute for diversification; averaging into one stock concentrates risk at a lower average price.

## DCA and the three screened strategies

A cash-secured put is not a dollar-cost-averaging tool, though it is sometimes described as one. The writer is paid to buy at the strike if the price falls, which is a single conditional purchase, not a schedule. A LEAPS call, likewise, is a single purchase of long-dated upside. What can be averaged is the contribution of new cash to the account that funds them: an investor who adds $500 a month raises buying power steadily, and the sizing engine re-runs with the larger figure. The options positions are sized on each run; the contributions are what grow the base.

## What can go wrong

The chief risk is treating DCA as a promise of a good average price. In a market that rises steadily for years, the averaging investor pays more than the lump-sum investor would have. In a market that falls and stays down, both lose. Transaction costs matter too: on a brokerage that charges per trade, small frequent purchases can cost more in commissions than the smoothing is worth, which is one reason commission-free fund purchases made DCA practical for small accounts.

## Where this shows up in OptionsScout

The Goals tab takes an optional **monthly contribution**, and the Goal Planning agent's `project_balance` function adds it to the account at the end of each month before applying the assumed return, so the projection chart shows a balance that rises from both growth and savings. The feasibility verdict's levers include "more contribution" alongside more time and a smaller target, and the lever table shows how many extra dollars a month would close the gap at the stated return. The projection assumes a constant return; it is an illustration of compounding with contributions, not a forecast of the path.

## Sources

- SEC investor.gov, Compound Interest Calculator, which models a starting balance plus fixed monthly contributions: https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator
- SEC investor.gov, Introduction to Investing: https://www.investor.gov/introduction-investing
- Bogleheads wiki, main page, with links to its articles on dollar cost averaging and lump sum investing: https://www.bogleheads.org/wiki/Main_Page
