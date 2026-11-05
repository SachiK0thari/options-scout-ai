---
id: compound-growth
title: "Compound growth: the rule of 72, regular contributions, and why option premium is not a bond coupon"
source: "SEC investor.gov, Compound Interest Calculator; SEC investor.gov, Bonds"
url: https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator
kind: basics
level: beginner
as_of: 2026-11-04
---

# Compound growth: the rule of 72, regular contributions, and why option premium is not a bond coupon

**Compounding** is growth on growth. When an investment earns a return and that return is left invested, the next period's return is earned on a larger base. Over a few years the effect is modest; over decades it dominates everything else, including the size of the original deposit. The SEC's investor.gov site provides a free compound interest calculator, and every figure below can be reproduced in it.

## A worked example with explicit assumptions

Assume an investor starts with $10,000, adds $6,000 at the end of every year, and earns a constant 7% per year compounded annually for 30 years. These are assumptions for illustration, not a forecast; real returns vary year to year and can be negative.

- The initial $10,000 alone grows to $10,000 x 1.07^30, about $76,100.
- The thirty annual contributions of $6,000, totalling $180,000, grow to roughly $566,800.
- The combined ending balance is about $642,900, of which $190,000 was deposited and about $452,900 came from compounding.

Change the rate to 4% and the ending balance falls to roughly $369,000; change it to 10% and it rises to about $1.16 million. The sensitivity to the assumed rate is the point: small differences in annual return, including the drag of fees and taxes, become very large differences over long horizons.

## The rule of 72

The **rule of 72** is a mental shortcut: dividing 72 by the annual return gives the approximate number of years for money to double. At 7% a year, 72 / 7 is about 10.3 years; over 30 years that is nearly three doublings, or close to eight times the starting amount, which matches the $76,100 figure above (1.07^30 is 7.6). At 3% the doubling time is 24 years; at 12% it is six.

## Why contributions matter as much as the rate

In the example, the regular contributions produced far more than the lump sum because each one has its own compounding clock. For a goal-planning exercise, the contribution schedule is usually the variable an investor can control; the return is not.

## Why reinvested premium is not a bond coupon

A **bond coupon** is a contractual interest payment: the issuer owes it on fixed dates, and the principal is returned at maturity unless the issuer defaults. It is natural to look at a short put's premium, annualised, and treat it the same way. Suppose a put yields a $120 premium on $4,880 of collateral over 40 days: about 2.5% for the period, or roughly 22% if repeated for a year. That annualised figure is not a coupon, for three reasons. First, it assumes the trade can be repeated nine times with the same economics, which depends on volatility staying where it is. Second, it ignores the losses: a single assignment in a stock that falls 30% can erase a year or more of premiums, and the realistic loss on each trade is far larger than the premium. Third, the premium is payment for taking on equity risk, so the "yield" is really a conditional return on a stock position, not interest. Projecting premium forward at a fixed compounding rate overstates both the return and its reliability.

## What can go wrong

Compounding works in reverse: a 30% loss requires a 43% gain to recover, and a sequence of poor early years can leave a goal unreachable even if the long-run average is met. Inflation reduces what an ending balance buys; the example's dollars are nominal. Taxes on premium and dividends in a taxable account reduce the amount actually reinvested each year.

## Where this shows up in OptionsScout

The planned Goals tab and its Goal Planning agent cite this document when they show a projection. Every projection states its assumptions (starting balance, contribution, assumed return, horizon) next to the result, is computed by tested Python code rather than by the language model, and shows a range of rates rather than a single figure. The agent treats premium from the Candidates tab as a conditional return with a realistic loss attached, never as a coupon, and the Compliance agent rejects any sentence that presents a projected figure as a prediction.

## Sources

- SEC investor.gov, *Compound Interest Calculator*: https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator
- SEC investor.gov, *Bonds* (how coupons work): https://www.investor.gov/introduction-investing/investing-basics/investment-products/bonds-or-fixed-income-products/bonds
- SEC investor.gov, *Introduction to Investing*: https://www.investor.gov/introduction-investing
