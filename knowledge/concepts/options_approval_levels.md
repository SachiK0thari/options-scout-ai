---
id: options-approval-levels
title: "Options approval levels: what brokers permit at each tier and why a cash account cannot write naked puts"
source: "FINRA Rule 2360 (Options), especially paragraph (b)(16) on opening accounts and (b)(19) on suitability; Regulation T"
url: https://www.finra.org/rules-guidance/rulebook/finra-rules/2360
kind: concepts
level: beginner
as_of: 2026-11-04
---

# Options approval levels

Before a brokerage account can trade options at all, the broker must approve it for options trading, and most brokers approve it for a **level** or **tier** that decides which strategies are allowed. The names and numbers differ from firm to firm, but the ladder is similar everywhere: strategies are ranked by how much the account could lose and how complicated the obligations are.

## A typical ladder in plain words

- **Lowest tier**: covered calls and protective puts. These need shares already in the account, and the worst case is already the worst case of owning the stock.
- **Next tier**: buying calls and puts, and writing cash-secured puts. A buyer can lose only the premium; a cash-secured put writer has set aside the full purchase price, so the broker is never short of collateral. LEAPS calls are simply long calls and sit here.
- **Higher tier**: spreads, where one option is bought against another. These require a margin account and the ability to assess paired positions.
- **Highest tier**: naked (uncovered) writing of puts and calls, where the obligation is backed by margin rather than by cash or shares, and uncovered calls can lose without limit.

A poor man's covered call is a long LEAPS plus a short call against it, which brokers usually classify as a diagonal spread and place in the spread tier even though its risk is defined.

## What FINRA Rule 2360 requires

FINRA Rule 2360 is the options rule for broker-dealers. Among other things it requires that a firm approve an account for options before the first trade, that a registered options principal make that approval, that the firm gather the customer's investment objectives, experience, income, net worth and other facts in the account application, and that the firm deliver the OCC's *Characteristics and Risks of Standardized Options* document at or before approval. Its suitability paragraph says a firm may recommend an option transaction only when it has reasonable grounds to believe the customer can evaluate the risk and bear the financial loss. The tiers are the industry's way of organising that obligation; a customer can apply to move up, and the broker can decline.

## Why a cash account cannot write naked puts

A **cash account** under Regulation T can hold only positions that are fully paid for. A short put is permitted there only when the full exercise value, strike times 100 less the premium received, is held in cash and set aside, which is the definition of a cash-secured put. A **naked put** is the same contract without the cash set aside; the broker instead requires a margin deposit under FINRA Rule 4210, typically a fraction of the strike value, and lends against the rest. That borrowing is what a cash account does not allow. The same contract is therefore "cash-secured" in a cash account and "naked" in a margin account, and only the margin account carries the leverage, and the risk of a margin call, that puts naked writing in the top tier.

## What can go wrong

An approval level is a permission, not an assessment of any particular trade; a tier that permits cash-secured puts does not mean every cash-secured put suits the account. Brokers differ in how they classify the same strategy, and an account approved for spreads at one firm can be refused them at another. Approval does not change what a position can lose.

## Where this shows up in OptionsScout

The Setup tab asks whether the account is cash or margin, which changes how collateral is computed (full cash for a CSP, the Reg T requirement for a naked put on margin) and whether margin constraints apply in Portfolio & Risk. The app does not know or check the user's approval level and never connects to a brokerage; the Risk agent's suitability facts are general statements about each strategy's risk, and the Compliance agent ensures no sentence tells a user which tier to request.

## Sources

- FINRA Rule 2360, Options: https://www.finra.org/rules-guidance/rulebook/finra-rules/2360
- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
- Regulation T, 12 CFR Part 220 (cash and margin accounts): https://www.ecfr.gov/current/title-12/chapter-II/subchapter-A/part-220
- FINRA Rule 4210, Margin Requirements: https://www.finra.org/rules-guidance/rulebook/finra-rules/4210
