---
id: inflation-and-real-return
title: "Inflation and real return: why a goal ten years out should be stated in today's dollars"
source: "SEC investor.gov, Introduction to Investing (inflation risk); investor.gov Compound Interest Calculator"
url: https://www.investor.gov/introduction-investing
kind: basics
level: beginner
as_of: 2026-11-04
---

# Inflation and real return

**Inflation** is the rate at which the general level of prices rises, so that a dollar buys less over time. A **nominal return** is the percentage change in the dollar value of an investment. A **real return** is the nominal return after removing inflation: the change in what the investment can actually buy. The SEC's investor.gov introduction lists inflation risk alongside market risk because an account that grows in dollars can still shrink in purchasing power.

## The Fisher approximation

The exact relationship is (1 + nominal) = (1 + real) x (1 + inflation). For everyday rates the **Fisher approximation** is close enough: real return is roughly nominal return minus inflation. Suppose an account earns 7% in a year when inflation is 3%. The approximation gives a 4% real return; the exact figure is 1.07 / 1.03 - 1, or 3.88%. The gap between the two grows with the size of the rates, so at 20% inflation the shortcut is noticeably off, but at the levels most investors plan around it is fine for a first pass.

## Why a distant goal belongs in today's dollars

A goal stated as "$1,000,000 in 25 years" is ambiguous until the planner says whether that is a million of today's dollars or a million of 2051 dollars. At 3% inflation, $1,000,000 in 25 years buys what about $478,000 buys today, because 1.03 to the 25th power is about 2.09. An investor who reaches the nominal target would have less than half the purchasing power they pictured. The clean way to plan is to state the goal in today's dollars and then project with a real return, which handles inflation automatically. The alternative is to inflate the target every year and project with a nominal return; both methods agree if applied consistently, and mixing them is the common mistake.

## A worked projection

Suppose an investor wants the equivalent of $40,000 a year of today's spending in 20 years and assumes a 7% nominal return with 3% inflation. Using the real rate of about 3.9%, a balance today grows by a factor of 1.039 to the 20th power, about 2.15, so $100,000 today would be worth about $215,000 in today's dollars after 20 years. Using the nominal rate instead, the same $100,000 grows to about $387,000 in 2046 dollars, which is the same purchasing power once those dollars are deflated by 1.03 to the 20th power, about 1.81. The two paths describe one outcome. Every figure here is arithmetic on stated assumptions, not a forecast.

## What can go wrong

Inflation is not constant, and the long-run average hides years when it was far higher. A plan built on 2% inflation that meets 5% for several years loses ground even if the nominal return arrives exactly as assumed. Inflation also differs by what is bought: housing, education and health care have at times risen faster than the headline index, so a goal tied to those costs needs its own assumption. Finally, premium received from a short put is a nominal dollar amount set at the time of the trade, and a cash reserve earning the Treasury bill rate can have a negative real return when inflation exceeds that rate.

## Where this shows up in OptionsScout

The Goals tab asks for a target in today's dollars and an assumed return, and the Goal Planning agent projects the balance along a base path and a stress path at that return. The feasibility card states the assumed return and the profile's cap beside the result, and the Compliance agent requires the word "would" next to any future figure. The cash reserve in each projection grows at the Treasury bill rate, which is the one input most likely to sit below inflation, so the Goals narrative notes when the reserve's real return is likely negative at the stated assumptions. The app does not forecast inflation; the user's assumption is the only one in the calculation.

## Sources

- SEC investor.gov, Introduction to Investing, on inflation risk: https://www.investor.gov/introduction-investing
- SEC investor.gov, Compound Interest Calculator, for reproducing the projections above: https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator
- Bogleheads wiki, main page, with links to its articles on inflation-indexed securities and real return: https://www.bogleheads.org/wiki/Main_Page
