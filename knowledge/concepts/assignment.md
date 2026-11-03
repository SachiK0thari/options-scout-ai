---
id: assignment
title: "Assignment: what happens when a short option is exercised against you"
source: "OCC, Characteristics and Risks of Standardized Options, chapter VIII (Exercise and Assignment)"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
as_of: 2026-11-03
---

# Assignment

**Assignment** is the process by which an option writer is selected to fulfil the obligation of a contract that a holder has exercised. When a put holder exercises, some put writer is obliged to take the shares at the strike; when a call holder exercises, some call writer must deliver them. The Options Clearing Corporation (OCC) receives exercise notices from clearing members, assigns them at random to clearing members with short positions in the same series, and each clearing member then assigns its own customers by a method approved by the exchanges, usually random selection or first-in first-out.

## What the writer experiences

A writer learns of an assignment after the fact, normally the next morning. For a short put the account now holds 100 long shares per contract bought at the strike price, and the cash or margin that secured the put has been used to pay for them. For a short call the account has delivered 100 shares per contract (or is short them, if it did not own shares). There is no way to refuse an assignment, and no way to know in advance which writer the random process will select.

## When assignment happens

Options that finish **in the money at expiration** are exercised automatically by the OCC under its exercise-by-exception rule, currently for any amount in the money, unless the holder instructs otherwise. A short put that is one cent in the money at the close on expiration Friday should therefore be expected to result in share ownership on Monday. Because American-style equity options can be exercised on any trading day, assignment can also happen **early**, before expiration. Early exercise of a put is rational when the put is deep in the money and the interest earned on the strike cash outweighs the remaining extrinsic value; early exercise of a call is most common just before an ex-dividend date. Both cases are discussed in *Early assignment and dividends*.

## Why this app treats assignment as the base case

The cash-secured put is an agreement to buy a stock at the strike, so this app's design assumes the writer may end up owning it. The universe is restricted to a curated list of large, profitable companies and broad ETFs, and each name must pass a quality gate on the day of the run, precisely so that being assigned is an acceptable outcome rather than something to be avoided at any cost. The **realistic loss** figure shown for each CSP is the loss on those assigned shares if the stock falls 30% by expiration. Writers who would not want to own the shares at the strike should not be selling the put, whatever the premium.

## Practical consequences

Pin risk: when the stock closes at or within a few cents of the strike on expiration day, the writer cannot know until the next morning whether they were assigned, and the stock may move in after-hours trading. Many traders close short options on expiration day to avoid this uncertainty.

Cash accounts: an assigned put must be paid for in full, which is why the broker held the entire purchase price as collateral.

Margin accounts: an assigned put becomes a long stock position subject to the account's ordinary stock margin requirement, which can be considerably higher than the uncovered option requirement that applied to the short put. Brokers may liquidate the position if the account cannot meet the new requirement.

Tax and cost basis: an assigned put's premium is folded into the cost basis of the shares; an assigned call's premium is added to the proceeds. Rules differ by jurisdiction and are outside the scope of this tool.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter VIII, "Exercise and Assignment": https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- OCC, exercise and assignment overview for market participants: https://www.theocc.com/clearance-and-settlement/clearing/exercise-and-assignment
