---
id: naked-put-margin
title: "Naked put on margin: the same short put, secured by margin instead of cash"
source: "FINRA Rule 4210 (Margin Requirements); OCC disclosure document chapter X"
url: https://www.finra.org/rules-guidance/rulebooks/finra-rules/4210
kind: concepts
as_of: 2026-11-03
---

# Naked put on margin

A **naked put** (also *uncovered* or *short put on margin*) is the same contract as a cash-secured put: the writer sells a put, collects the premium and takes on the obligation to buy 100 shares at the strike if assigned. The difference is how the obligation is collateralised. In a cash account the broker holds the full purchase price. In a margin account the broker holds only a **margin requirement**, a fraction of the purchase price computed under exchange and FINRA minimum rules, and the writer keeps the rest of their buying power free for other positions.

## Why the same trade has a higher return and a higher risk

Because the denominator is smaller, the premium represents a much larger percentage of the capital tied up. A put that returns 1.7% on full cash collateral over 40 days may show a return of 10% or more on its Reg T margin requirement over the same period. Nothing about the stock or the contract changed; only the leverage did. The dollar loss if the stock falls is identical in both accounts, so expressed as a fraction of capital at risk the margin version is several times more volatile.

Two consequences follow. First, if the stock drops, the margin requirement itself rises (it is a function of the stock price and the distance out of the money), and the broker can issue a **margin call** demanding more cash or liquidating positions at the worst possible time. Second, the writer may have deployed the "freed" buying power into other short puts, so a broad market decline hits every position at once while the requirement on each one grows. The OCC disclosure document warns that writers of uncovered options may be required to meet margin calls on short notice and that losses can substantially exceed the premium received.

## The exchange minimum this app uses

The Reg T style minimum for an uncovered equity put, used by this app's `margin.py`, is the greater of two amounts, plus the premium: 20% of the stock price minus the amount the put is out of the money, or 10% of the strike price, in each case times 100 shares. For a $100 stock and a $90 put sold for $1.50, the out-of-the-money amount is $10, so 20% × 100 − 10 = $10 beats 10% × 90 = $9, and the requirement is ($1.50 + $10) × 100 = $1,150. The same put in a cash account would need ($90 − $1.50) × 100 = $8,850.

This is a **minimum**. Brokers set their own house requirements, which are often higher, change them without notice during volatile markets, and apply concentration add-ons to large positions. The report labels every margin figure as the exchange minimum for this reason.

## How this app treats margin accounts

When the user's account type is *margin*, the sizing engine uses the Reg T minimum as the capital consumed by each short put but applies additional portfolio-level caps: total margin usage is limited to a fraction of buying power (30%, 40% or 50% depending on risk profile), total short-put notional is capped relative to account value, and the **realistic loss** of each position at a 30% decline is shown next to its margin requirement so the leverage is visible. The report always reminds the reader that brokers can raise requirements. For *cash* accounts the margin constraints do not apply and every put is cash-secured in full.

## Sources

- FINRA Rule 4210, Margin Requirements, paragraph (f)(2)(D) for uncovered options: https://www.finra.org/rules-guidance/rulebooks/finra-rules/4210
- Federal Reserve Regulation T, 12 CFR Part 220: https://www.ecfr.gov/current/title-12/chapter-II/subchapter-A/part-220
- OCC, *Characteristics and Risks of Standardized Options*, chapter X: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
