---
id: reg-t-vs-portfolio-margin
title: "Reg T vs portfolio margin: strategy-based and risk-based requirements, and what this app computes"
source: "Regulation T, 12 CFR Part 220; FINRA Rule 4210 (Margin Requirements), including paragraph (g) portfolio margin"
url: https://www.finra.org/rules-guidance/rulebook/finra-rules/4210
kind: tax
level: advanced
as_of: 2026-11-13
---

# Reg T vs portfolio margin: strategy-based and risk-based requirements, and what this app computes

**Margin** is the collateral a broker requires an investor to hold against a position that could lose more than the cash paid for it. Two different systems decide how much collateral that is: the **strategy-based** rules that descend from Regulation T and FINRA Rule 4210, and **portfolio margin**, a risk-based system available to accounts the broker approves under Rule 4210(g). This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## Regulation T and strategy-based margin

**Regulation T** (12 CFR Part 220) is the Federal Reserve Board rule that governs how much credit a broker may extend when a customer buys securities. It sets the initial margin for stock purchases. FINRA Rule 4210 then fills in the maintenance requirements and the option-specific rules. Under this system each position, or each recognised pairing of positions, has its own formula. For an uncovered short equity put the requirement is the greater of two figures: a percentage of the underlying's value minus the amount the put is out of the money, plus the premium, or a smaller percentage of the strike plus the premium. A long option bought outright is paid in full. A spread is margined by its maximum loss when the broker recognises the pairing.

The system is called strategy-based because it looks at each named strategy in isolation and adds up the results. It does not ask whether a long put elsewhere in the account offsets the short put; unless the two form a recognised spread, both are margined separately.

## Portfolio margin

**Portfolio margin**, under FINRA Rule 4210(g), replaces the per-strategy formulas with a risk-based calculation. All positions in the same underlying are grouped, the group is revalued under a set of hypothetical price moves up and down, and the requirement is the largest loss across those scenarios. Offsetting positions reduce the requirement because they reduce the loss in the stress scenarios. For hedged positions the requirement is usually far lower than under strategy-based rules, which also means the account can hold far more exposure per dollar of equity.

Eligibility is not automatic. Rule 4210(g) requires the broker to have a FINRA-approved portfolio margin program, to approve each customer, to maintain a minimum equity level, and to monitor the account daily, and brokers set their own eligibility thresholds and house requirements above the rule's floor. The FINRA margin page describes margin calls, the broker's right to liquidate without notice, and house requirements that can change at any time.

## What this app computes, and what it does not

This app computes the **Reg T strategy-based minimum** for a short put using the Rule 4210 formula, and uses it as the denominator of return on margin. It states next to the figure that the actual broker requirement differs: brokers add house requirements, raise margin on concentrated or volatile names, and may be using portfolio margin for an eligible account. Computing a portfolio margin figure would require the broker's own scenario set and the whole account, neither of which the app has, since it never connects to a brokerage.

## What can go wrong

Lower margin is not lower risk. A naked put under portfolio margin can be written with a fraction of the collateral a cash-secured put needs, so a 30% decline in the stock, the app's realistic-loss scenario, can wipe out the account's equity and trigger a margin call that is met by forced sales at the worst time. House requirements can rise during the trade. Under either system the maximum loss of a short put is the same: strike minus premium, times 100.

## Where this shows up in OptionsScout

The Candidates tab shows return on margin for CSP candidates when the Setup tab records a margin account, computed from the Reg T minimum, with a note that broker margin differs. Return on collateral, which assumes the full strike is set aside, is shown for cash accounts, which is how an IRA is entered. On a margin account the app's short puts are sized on the Reg T requirement, which makes them naked puts, and the report says so. A portfolio margin account is sized with the same Reg T rules: the app does not model a broker's risk-based requirement, so the margin figure shown will differ from the broker's.

## Sources

- FINRA Rule 4210, Margin Requirements, including paragraph (g) on portfolio margin: https://www.finra.org/rules-guidance/rulebook/finra-rules/4210
- Regulation T, 12 CFR Part 220, Credit by Brokers and Dealers: https://www.ecfr.gov/current/title-12/chapter-II/subchapter-A/part-220
- FINRA, Margin Accounts investor page: https://www.finra.org/investors/investing/investment-accounts/margin-accounts
