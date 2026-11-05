---
id: covered-call
title: "Covered call: selling a call against 100 shares you already own"
source: "OCC, Characteristics and Risks of Standardized Options, chapter X (Risks of Option Writers); Cboe Options Institute"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: intermediate
as_of: 2026-11-04
---

# Covered call: selling a call against 100 shares you already own

A **covered call** is a short call written by an investor who already owns at least 100 shares of the underlying for each contract sold. The shares "cover" the obligation: if the call is assigned, the writer delivers shares already held instead of buying them in the market. The writer collects the premium up front and, in exchange, gives up any gain in the stock above the strike for the life of the contract. The covered call is **not screened on its own by this app**, but it is one half of the poor man's covered call (PMCC) that the app does screen.

## The pieces

- **Long stock**: 100 shares per contract.
- **Short call**: an obligation to sell those shares at the strike if the holder exercises. Equity calls are American style, so assignment can arrive on any trading day.
- **Premium**: the cash received when the call is sold. It is the writer's to keep whatever happens next.

## Payoff at expiration

Suppose shares were bought at $48, a $50 call is sold for $1.20, and the position is held to expiry.

- Stock at or below $50: the call expires worthless. The writer keeps the shares and the $1.20, so the effective cost basis falls to $46.80 per share.
- Stock above $50: the call is assigned and the shares are sold at $50. The total received is $50 + $1.20 = $51.20 no matter how high the stock went. The maximum gain is $3.20 per share, or $320 per contract.
- Breakeven: $48 - $1.20 = $46.80. Below that the position loses money just as the shares alone would, less the premium.

The downside is therefore the full downside of stock ownership minus a small cushion. The OCC disclosure document describes the covered call writer as giving up the opportunity to benefit from a rise in the underlying above the strike while remaining exposed to its decline.

## Opportunity cost, the quiet risk

The cost that is easy to overlook is the **opportunity cost**: the upside surrendered when a stock rallies through the strike. On a stock that rises 20% in a month, a writer who capped the position 4% above the purchase price keeps the premium and misses the other 16%. Over many cycles on a trending stock, that forgone gain can exceed every premium collected. Assignment also removes the shares from the account, which is a taxable sale in a brokerage account.

## What can go wrong

First, the stock falls far more than the premium offsets; the call is a cushion, not a hedge. Second, early assignment just before an ex-dividend date takes the shares away right before the dividend is paid, which is why *Early assignment and dividends* is its own document. Third, a writer who no longer wants to deliver the shares can only avoid assignment by buying the call back, possibly at a price well above what was received.

## Relationship to the PMCC short call

In a **poor man's covered call** the 100 shares are replaced by a deep in-the-money LEAPS call (0.70-0.85 delta), and a shorter-dated call is sold against it in exactly the same way. The short call carries the same capped-upside trade-off, but the cover is another option rather than stock, which brings one rule a stock-covered call never needs: the short strike must sit at or above the LEAPS strike plus the LEAPS net debit, so that assignment can never lock in a loss on the pair. The app's PMCC screener enforces that rule and looks for the short leg at 30-45 DTE and 0.20-0.30 delta.

## Where this shows up in OptionsScout

The covered call is not screened by this app: the app's thesis is reaching good-to-own stocks through a cash-secured put, or stock-like exposure through a LEAPS, so there is no owned-share leg to write against. It appears in the Candidates tab only as the short-call leg of a PMCC, where the strike-safety rule above is shown as a check, and in the Learn tab as background. The holdings section in Portfolio & Risk records shares a user owns, but the app does not screen calls against them.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter X, "Risks of Option Writers": https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute, covered call education: https://www.cboe.com/education/
- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
