---
id: pattern-day-trading-rule
title: "The pattern day trading rule and its replacement: why a 30-45 DTE put seller rarely meets either"
source: "FINRA Regulatory Notice 26-10 (intraday margin rule replacing the day trading margin requirements); FINRA Rule 4210; Regulation T, 12 CFR Part 220"
url: https://www.finra.org/rules-guidance/notices/26-10
kind: tax
level: beginner
as_of: 2026-11-13
review_by: 2027-10-20
---

# The pattern day trading rule and its replacement: why a 30-45 DTE put seller rarely meets either

A **day trade** is the purchase and sale, or sale and purchase, of the same security on the same day in a margin account. Options count: selling a put to open and buying the same put back later the same day is one day trade. For many years FINRA's margin rule gave accounts that did this often a special status, the **pattern day trader**, with a $25,000 minimum equity requirement. That rule is being replaced. This is education, not tax advice; rules change and individual situations differ, so confirm with your broker and the FINRA notice cited.

## The rule that is being replaced

Under the old FINRA Rule 4210(f)(8)(B), a **pattern day trader** was a customer who made four or more day trades within five business days in a margin account, where those trades were more than six percent of the account's trades in the period. A pattern day trader had to keep at least $25,000 of equity in the account on any day they day traded, and could not day trade while equity was below it.

## What replaces it

The SEC approved FINRA's change on 14 April 2026, and FINRA announced it in Regulatory Notice 26-10. The change removes the day trading margin requirements in their entirety, including the pattern day trader designation and the $25,000 minimum, and replaces them with an **intraday margin** standard. The ordinary maintenance margin requirements stay in place; the new standard adds to them.

In plain terms: on any day with a trade that lowers the account's margin position (buying on margin or opening a short, for example), the broker works out the account's largest shortfall of equity against required margin at any point during that day, the **intraday margin deficit**. The customer must cover a deficit promptly, by depositing money or reducing positions. A customer who makes a practice of leaving deficits uncovered faces a 90-day restriction on new margin positions. Brokers may check in real time or at the close, and may set stricter house rules.

The rule took effect on **4 June 2026**, but firms that need more time may phase it in until **20 October 2027**. During that period some brokers still apply the old pattern day trader rule and the $25,000 minimum, so ask your broker which regime applies to your account.

## Why neither rule touches a 30-45 DTE put seller much

The cash-secured put screener in this app looks for puts with 30 to 45 days to expiration, opened once and then left to expire, bought back weeks later, or assigned. None of those is a day trade: four puts sold on a Monday and bought back on Friday are zero day trades. The old rule was reached only by opening and closing within one session, several times in a week. The new rule looks at intraday margin, not trade counts, so it matters mainly to a margin account already near its requirement.

## Cash accounts are governed by settlement instead

Both regimes apply to margin accounts. A **cash account** is subject to neither, but Regulation T requires its purchases to be paid with settled funds; since 2024 trades settle one business day later (**T+1**). Buying with unsettled sale proceeds and selling the new position before that sale settles is a **good-faith violation**, and repeated violations restrict the account to settled cash for a period.

## What can go wrong

At a broker still on the old rule, closing a put the same day it was written, several times in a volatile week, can bring the pattern day trader label and a day-trading freeze below $25,000 of equity. Under the new rule, a margin account that dips below its requirement during the day must cover the deficit even if it recovers by the close. And a cash account owner who assumes "no day trading rule" means "no settlement rule" will collect good-faith violations.

## Where this shows up in OptionsScout

The app's CSP screener only produces 30-45 DTE candidates and never places trades, so nothing in the Candidates tab is a day trade. The Setup tab asks for the account type, and the Portfolio & Risk tab applies a margin-usage constraint only to margin accounts; the app does not track day trades or intraday margin, so a user who also trades actively elsewhere has to watch that at the broker.

## Sources

- FINRA Regulatory Notice 26-10, intraday margin rule replacing the day trading margin requirements: https://www.finra.org/rules-guidance/notices/26-10
- FINRA Rule 4210, Margin Requirements: https://www.finra.org/rules-guidance/rulebook/finra-rules/4210
- Regulation T, 12 CFR Part 220, including section 220.8 on cash accounts: https://www.ecfr.gov/current/title-12/chapter-II/subchapter-A/part-220
- SEC press release 2023-29, adoption of T+1 settlement: https://www.sec.gov/news/press-release/2023-29
