---
id: rolling
title: "Rolling and closing: the management rules this app flags for short puts and LEAPS"
source: "OCC disclosure document chapter X; Cboe Options Institute; PRD.md section 3.4 and stretch goals"
url: https://www.cboe.com/education/
kind: concepts
level: intermediate
as_of: 2026-11-13
---

# Rolling and closing an option position

**Rolling** means closing an existing option position and opening a similar one in a different series at the same time, usually in a single order. A short put can be rolled **out** to a later expiration, **down** to a lower strike, or both; a short call can be rolled **up** and out. A long LEAPS can be rolled out to a later year to restore the time horizon. Rolling does not undo anything: the loss or gain on the closed contract is realised, and the new contract is a new trade that happens to be opened at the same moment. Its usefulness is that the new contract's premium can offset the cost of closing the old one.

## Why premium sellers roll

A short put that has moved against the writer can be rolled out and down for a net credit when the later, lower put is worth more than it costs to buy back the current one. The writer lowers the strike at which they would be assigned and extends the time for the stock to recover, in exchange for staying exposed longer. A roll for a net debit, paying to extend, is usually a sign that the position has become a different trade than the one intended.

## Common management rules

These rules are widely taught and are the ones this app's report will flag in its "management mode" stretch goal. They are heuristics, not promises.

- **Take profit at 50%.** When a short put can be bought back for half the premium received, most of the expected gain has been earned while a large share of the gamma risk remains; many writers close and redeploy rather than wait for the last cents.
- **Close or roll at 21 days to expiration.** The last three weeks hold the fastest time decay but also the highest gamma; a put that is still comfortably out of the money at 21 days has little left to give relative to what a sudden move could take.
- **Rolling a LEAPS below 240 days.** A common rule of thumb is to roll or close a LEAPS once it falls below about 240 days to expiration. At that point the option is leaving the flat part of the time-decay curve and its extrinsic value starts to erode faster; a deep in-the-money call still tracks the stock closely (more so as delta nears 1), but the horizon left for the thesis is short. The app screens new LEAPS only and does not track ones already held, so the warning is the reader's to apply. The LEAPS screener prefers series with 540 or more days for the same reason.
- **Rolling the PMCC short call before an ex-dividend date** when it is in the money and its extrinsic value is below the dividend, to avoid early assignment.

## Costs and limits of rolling

Every roll pays two bid-ask spreads and two commissions. A roll out to a later date keeps collateral or margin tied up for longer, which lowers the annualised return the position was selected for. A roll down to a lower strike accepts a lower premium for the extended period. And a short put can only be rolled while there is a later series with enough liquidity to trade; after a large decline the lower strikes may be too far from the money to pay anything. The OCC disclosure document notes that there is no assurance that a liquid secondary market will exist when a holder or writer wants to close a position, and rolling depends on one.

## What this app does today

The current screening report selects new positions and does not track existing ones, so it shows the roll-or-close flag for LEAPS candidates whose days to expiration fall below the threshold and otherwise describes the rules above as education. Management of open positions, with roll suggestions based on the user's entries, is listed as a stretch goal in the product requirements.

## Sources

- Cboe Options Institute, position management education: https://www.cboe.com/education/
- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on closing transactions and secondary-market risk: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- The 240-day threshold and the LEAPS screen rules: PRD.md section 3.4 and `config/screener_rules.yaml`.
