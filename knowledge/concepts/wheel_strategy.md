---
id: wheel-strategy
title: "The wheel: cash-secured put, assignment, covered call, repeat"
source: "OCC, Characteristics and Risks of Standardized Options, chapter X; Cboe Options Institute; PRD.md section 3.3"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: intermediate
as_of: 2026-11-13
---

# The wheel: cash-secured put, assignment, covered call, repeat

The **wheel** is a cycle of three steps. An investor sells a **cash-secured put** on a stock they are willing to own. If the put expires worthless, they keep the premium and sell another. If the put is assigned, they now own 100 shares at the strike and begin selling **covered calls** against them. If a call is assigned, the shares are sold at the call strike and the cycle returns to the start. The name comes from the way the position turns from cash to stock and back again. This app screens only the first step.

## Step one: the put

A cash-secured put is a short put with the full purchase price held as collateral. Suppose a stock trades at $54 and a $50 put with 40 days to expiration is sold for $1.20. If the stock finishes above $50, the $120 per contract is the whole return. If it finishes below, the writer buys 100 shares at $50 with an effective cost of $48.80 per share.

## Step two: the shares and the call

Once assigned, the holder owns a stock that has fallen below the strike. The wheel says to sell a call at or above the cost basis. Continuing the example, with the stock at $47 a $50 call might fetch $0.60. If that call is assigned, the whole cycle returned $1.20 + $0.60 + ($50 - $50) = $1.80 per share before costs. If the stock keeps falling, the holder keeps collecting small call premiums while sitting on a larger unrealised loss in the shares.

## Why it appeals and where it misleads

Each step looks like collecting a fee for a promise. The weak point is step two. Assignment usually happens because the stock dropped, often well past the strike, and the calls that pay anything meaningful are then struck below the cost basis. Selling those locks in a loss if assigned; selling calls above the basis pays almost nothing. The wheel earns small premiums in calm markets and takes a stock-sized loss in a bad one. That is not a flaw in the mechanics; it is what owning stock means, dressed in a sequence of trades.

## What this app screens and what it leaves out

The app screens the first leg only, with a 30-45 DTE window, |delta| 0.15-0.30, open interest of at least 500, a spread no wider than 10% of mid, and no earnings before expiry. The reason is the thesis behind the universe: every name has passed a quality gate, so being assigned means owning a company the user already judged worth owning. What happens after assignment depends on facts the app does not have, such as the holder's cost basis, tax situation and view of the stock, so the app does not model:

- **Exit liquidity for the call leg.** After a sharp drop the only liquid call series may be those below the cost basis, and the spread on far-out-of-the-money calls can be a large fraction of a small premium.
- **Tax of repeated assignment.** Each put assignment folds the premium into the share basis; each call assignment is a sale, usually short-term, and a put sold soon after a loss can trigger the wash-sale rule. The Tax & Accounts page in Learn covers these mechanics separately.
- **Dividends and early assignment** on the call leg, and the plain possibility that a stock keeps falling through several cycles.

## Where this shows up in OptionsScout

The Candidates tab shows cash-secured puts, which is the wheel's first spoke, and the Portfolio & Risk tab reports each put's **realistic loss**, the loss if the stock drops 30% at expiry, which is the number that matters if the wheel turns to step two. The holdings section lets a user record assigned shares, but the app does not screen covered calls against them and never suggests when to turn the wheel.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter X, "Risks of Option Writers": https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute, cash-secured put and covered call education: https://www.cboe.com/education/
- IRS Publication 550, Investment Income and Expenses (basis adjustments on assigned options, wash sales): https://www.irs.gov/publications/p550
