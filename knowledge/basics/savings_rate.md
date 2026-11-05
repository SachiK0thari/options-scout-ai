---
id: savings-rate
title: "Savings rate: the share of income saved and how it sets the years to independence"
source: "Bogleheads wiki (main page and savings articles); SEC investor.gov Compound Interest Calculator"
url: https://www.bogleheads.org/wiki/Main_Page
kind: basics
level: beginner
as_of: 2026-11-04
---

# Savings rate

The **savings rate** is the share of income that is saved rather than spent: savings divided by income, usually after tax. A household earning $60,000 after tax and spending $48,000 saves $12,000, a 20% savings rate. The Bogleheads wiki treats it as the first number a saver controls, because it does double duty. A higher rate puts more money to work each year, and it also means lower expenses, which means a smaller amount is needed to be financially independent.

## Why the rate, not the dollar amount, sets the timeline

The FIRE number is a multiple of expenses, commonly 25 times at a 4% withdrawal rate. Saving more out of a fixed income lowers expenses and raises contributions at the same time, so the target falls while the speed toward it rises. Suppose two households each earn $60,000. One saves 10%: it adds $6,000 a year toward a target of 25 x $54,000 = $1,350,000. The other saves 50%: it adds $30,000 a year toward a target of 25 x $30,000 = $750,000. The second household is saving five times as much toward a target barely half as large. The ratio of target to annual saving, 225 years of saving versus 25, is what the returns then have to compress.

## Years to independence by savings rate

The table below starts from a zero balance, assumes a constant 5% real annual return and a 4% withdrawal rate, and uses $60,000 of after-tax income so the dollar columns are concrete. It is an illustration of the arithmetic, not a forecast; a different return or income changes every cell.

| Savings rate | Saved per year | FIRE number | Years to FI |
|---|---|---|---|
| 10% | $6,000 | $1,350,000 | about 51 |
| 20% | $12,000 | $1,200,000 | about 37 |
| 30% | $18,000 | $1,050,000 | about 28 |
| 50% | $30,000 | $750,000 | about 17 |

Each row solves for the number of years at which annual saving compounded at 5% equals the FIRE number. The years column depends only on the savings rate and the return, not on income: a household earning $120,000 at a 20% rate reaches independence in the same 37 years, with every dollar figure doubled. The investor.gov compound interest calculator reproduces any row from a starting balance of zero and the stated monthly contribution.

## What the table hides

The return assumption does most of the work in the long rows: at a 3% real return the 10% row stretches past a working lifetime, at 7% it shortens by more than a decade. Income and expenses are not fixed for forty years. The table assumes retirement expenses equal working expenses, the regular FIRE variant; lean, fat and barista change the target column and the years. And it ignores sequence risk, the chance that poor returns arrive just before or just after independence.

## What can go wrong

A savings rate measured against gross income overstates what is saved once taxes are paid; the Bogleheads wiki notes that the definition must be consistent between the saving and the spending side. A high rate reached by deferring maintenance, insurance or an emergency fund is borrowed from the future rather than saved. And a savings rate feeding an options portfolio inherits the risks of that portfolio: contributions sized against a premium yield are sized against a number that falls in calm markets and is tested in falling ones.

## Where this shows up in OptionsScout

The FIRE card on the Goals tab computes the savings rate from the income and expenses the user enters and shows it beside the FIRE number and the years to independence at the profile's assumed return, using the same `savings_rate` and `years_to_fi` functions as the table above. Changing the variant selector moves the target lines on the projection chart; changing the monthly contribution moves the path. The card labels the years figure with the word "would" and the return it assumes, as the Compliance agent requires, and shows the stress path alongside the base path.

## Sources

- Bogleheads wiki, main page, with links to its articles on savings rate and the importance of saving early: https://www.bogleheads.org/wiki/Main_Page
- Bogleheads wiki, Safe withdrawal rates, for the 25x multiple used in the FIRE number column: https://www.bogleheads.org/wiki/Safe_withdrawal_rates
- SEC investor.gov, Compound Interest Calculator, for reproducing the table rows: https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator
