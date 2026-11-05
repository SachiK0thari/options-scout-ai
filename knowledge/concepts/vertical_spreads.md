---
id: vertical-spreads
title: "Vertical spreads: the bull put spread and the bear call spread"
source: "OCC, Characteristics and Risks of Standardized Options, chapters VIII and X; FINRA Rule 4210 (margin on spreads)"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: intermediate
as_of: 2026-11-04
---

# Vertical spreads: the bull put spread and the bear call spread

A **vertical spread** is a pair of options of the same type (both puts or both calls) on the same underlying and expiry but with different strikes, one bought and one sold. When the option sold is worth more than the option bought, the spread is opened for a **credit**, and the two credit spreads below are the ones most often compared with a cash-secured put. **Neither is screened by this app**.

## Bull put spread

Suppose a stock trades at $54. A writer sells a $50 put for $1.20 and buys a $45 put for $0.20, both 40 days out, for a net credit of $1.00. At expiration:

- Stock at or above $50: both puts expire worthless; the gain is the $1.00 credit, $100 per spread.
- Stock at or below $45: both puts are in the money and the spread is worth its full $5 width. The loss is $5 - $1 = $4, or $400 per spread, and it cannot grow further.
- Breakeven: $50 - $1.00 = $49.

The long $45 put is what caps the loss. The cash-secured put alone would have collected $1.20 but would be exposed all the way to zero.

## Bear call spread

The mirror image: a call is sold below a bought call, for example the $60 call sold for $1.10 and the $65 call bought for $0.30, an $0.80 credit. Maximum gain $80 if the stock stays at or below $60; maximum loss $5 - $0.80 = $4.20, or $420, at or above $65. It profits when the stock does not rise.

## Defined risk against assignment risk

A credit spread has **defined risk**: the worst case is known when the trade is opened. A cash-secured put has **assignment risk**: the worst case is owning the shares at the strike while they trade far lower. The spread's loss is realised as cash when the spread is closed or expires; the put writer's loss is unrealised and attached to shares that may or may not recover. Spreads also carry a risk of their own at expiry. If the stock finishes between the strikes, the short leg is assigned while the long leg expires worthless, leaving an unplanned stock position over the weekend; in the bull put example, a close at $47 means buying 100 shares at $50 with no protection left.

## Margin treatment

Under FINRA Rule 4210 and Regulation T, the requirement for a credit spread is the maximum loss, the width of the strikes minus the credit, because the long option limits what the writer can owe. In the bull put example that is $400 per spread, against roughly $4,880 of cash for the cash-secured put. That difference is the attraction and the danger: the same collateral carries about ten spreads, and ten spreads at maximum loss is a larger loss than one assigned put. Spreads generally need a margin account and a broker approval level above the one that permits cash-secured puts; see *Options approval levels*.

## Why this app does not screen them

The app's thesis is that the stocks in its universe are worth owning if assigned, which turns assignment from a failure into an acceptable branch. A credit spread rejects that branch by design: it limits the loss but also forecloses owning the shares, and its return comes from the stock staying in a range rather than from buying a good company below today's price. The app also could not compute a spread's realistic loss the way it does for a put, because the 30% drop scenario would always produce the full width.

## Where this shows up in OptionsScout

Vertical spreads are not screened by this app and do not appear in the Candidates tab. The *Under the hood* tab and Learn explain that the Portfolio & Risk constraints, especially the realistic-loss cap and the short-put notional cap, are built around the single short put and would not transfer to spreads.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter VIII (Options Spreads and Combinations) and chapter X: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- FINRA Rule 4210, Margin Requirements: https://www.finra.org/rules-guidance/rulebook/finra-rules/4210
- Cboe Options Institute, vertical spread education: https://www.cboe.com/education/
