---
id: drawdown
title: "Drawdown: measuring a decline from peak to trough"
source: "SEC investor.gov, Introduction to Investing (understanding risk); OCC, Characteristics and Risks of Standardized Options, chapter X"
url: https://www.investor.gov/introduction-investing
kind: basics
level: beginner
as_of: 2026-11-04
---

# Drawdown

A **drawdown** is the decline in the value of an investment or account from its most recent high point (the **peak**) to its subsequent low point (the **trough**), expressed as a percentage of the peak. If an account rises to $100,000 and later falls to $80,000 before recovering, it experienced a 20% drawdown. The **maximum drawdown** over a period is the largest such decline, and it is a common way to describe how bad the worst stretch was, as opposed to the average return, which hides it.

## Why the arithmetic is unforgiving

A drawdown and the gain needed to recover from it are not symmetric. A 20% decline needs a 25% gain to get back to the peak; a 30% decline needs about 43%; a 50% decline needs 100%. Suppose a $10,000 position falls 30% to $7,000. To return to $10,000 it must rise $3,000, which is 42.9% of $7,000. This is why large drawdowns dominate long-run results, and why investor.gov's introduction stresses that an investor's ability to sit through declines, rather than expected return, is the first thing to settle.

## Drawdown for a put writer

A cash-secured put has a drawdown profile like owning the stock from the strike downward. Suppose a writer sells a put at a $50 strike for a $1.20 premium and the stock falls to $35 at expiry. The writer is assigned 100 shares worth $3,500 against $5,000 of collateral, a loss of $1,500 minus the $120 premium, or $1,380, which is 27.6% of the collateral. The premium softened the first 2.4% of the fall and nothing after. A drawdown that would have been uncomfortable in the stock is just as uncomfortable in the put, with the added feature that the writer did not choose the moment of purchase.

## The quality gate and the 90-day high

A stock that has already fallen a long way from its recent high is in a drawdown whose cause may not yet be visible in the financial statements. OptionsScout's deterministic **quality gate** therefore drops any name trading more than 20% below its 90-day high, alongside its checks on price, volume, realised and implied volatility. The rule is not a prediction that the decline will continue. It encodes a preference: the app's product promise is to screen puts only on companies the user would be willing to own if assigned, and a name in a sharp, unexplained drawdown fails that test until it stabilises. The exact threshold lives in `config/quality_universe.yaml` and is reproduced in the generated rules documents.

## The -10 / -20 / -30% stress test

Every sized portfolio is run through a **stress test** that assumes every underlying falls 10%, 20% and 30% at once and reports the resulting loss as dollars and as a share of account value. The 30% case is also the definition of each CSP's **realistic loss**, the number the six portfolio constraints are measured against. The stress test is a drawdown shown in advance: it lets a user see what a 30% market decline would do to the account before the market shows them.

## What can go wrong

Historical drawdowns understate future ones whenever the future is worse than the sample. Broad indexes have fallen more than 30% several times, and single stocks have fallen 50% or more while still passing every quality check the week before. The 90-day high rule looks backward and will admit a stock the day before its decline starts. The stress test also assumes all names fall by the same percentage, which hides the case where one sector falls far more than the rest.

## Where this shows up in OptionsScout

The Quality Screen tab lists each name's distance from its 90-day high and marks the ones that fail the 20% rule with the reason. The Portfolio & Risk tab shows the -10/-20/-30% stress table and each position's realistic loss against the profile's cap. The Goal Planning agent must show the stress path whenever it shows a base projection, a rule enforced by the Compliance agent.

## Sources

- SEC investor.gov, Introduction to Investing, on risk and the ability to withstand declines: https://www.investor.gov/introduction-investing
- OCC, Characteristics and Risks of Standardized Options, chapter X, on the put writer's exposure to a decline in the underlying: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- OptionsScout rule in force: `config/quality_universe.yaml` and `config/risk_profiles.yaml` (`realistic_loss_drop`).
