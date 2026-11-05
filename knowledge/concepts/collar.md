---
id: collar
title: "Collar: long stock, a protective put and a short call"
source: "OCC, Characteristics and Risks of Standardized Options, chapter X; Cboe Options Institute"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: intermediate
as_of: 2026-11-04
---

# Collar: long stock, a protective put and a short call

A **collar** is a three-part position: 100 shares of stock, a long **protective put** below the current price, and a short **call** above it, both options on the same expiry. The put sets a floor under the shares; the short call pays for some or all of the put and sets a ceiling. The result is a stock position whose outcomes are confined to a band, hence the name. The collar is **not screened by this app**.

## The three legs

- **Long stock**: the position being protected, usually held already.
- **Long put**: the right to sell the shares at the put strike. This is insurance; its premium is the cost.
- **Short call**: an obligation to sell the shares at the call strike. Its premium offsets the put's cost in exchange for giving up gains above the strike.

## Cost and payoff

Suppose a stock trades at $100, a $90 put is bought for $2.50 and a $110 call is sold for $2.50, both expiring in 90 days. The net premium is zero, so this is a **zero-cost collar**. At expiration:

- Below $90: the put is exercised and the shares are sold at $90. The worst case is a $10 per share loss, 10% of the position.
- Between $90 and $110: both options expire worthless; the holder keeps the shares and participates in the move.
- Above $110: the call is assigned and the shares are sold at $110. The best case is a $10 gain.

Moving the strikes changes the trade-off. A put closer to the money costs more and needs a lower call strike to stay zero-cost, which narrows the band.

## When hedgers use it

Collars are a tool of people who already own stock and want to limit the damage from a decline for a defined period without selling. Common cases are a concentrated position such as employee stock, a holding that cannot be sold yet because of a lock-up, a planned expense a few months away that the shares will fund, and a wish to defer a sale for tax reasons while removing most of the downside.

## What can go wrong

The protection begins only at the put strike; in the example, the first 10% of a decline is unhedged. The upside is capped, so a strongly rising stock is sold at the call strike. The short call can be assigned early, most often just before an ex-dividend date, removing the shares and the dividend. When the options expire the collar must be rebuilt, and in a falling market the new put is more expensive. Finally, a collar whose strikes are set very close to the stock price can be treated for tax purposes as if the shares were sold; Publication 550 discusses constructive sales and straddle rules, and anyone collaring appreciated shares is squarely in that territory.

## Why this app does not screen it

The app's three strategies all begin with a view that a stock is worth owning: a cash-secured put to be paid while waiting to buy it, a LEAPS call as a leveraged substitute for owning it, and a PMCC that sells calls against the LEAPS. A collar starts from the opposite place, an existing holding that the owner wants to defend. It needs a stock leg the app does not have and a time horizon and tax picture it does not know. The PMCC is not a collar: it has no protective put and its long leg is a call, not shares.

## Where this shows up in OptionsScout

The collar is not screened by this app and does not appear in the Candidates tab. It is described in the Learn tab so that a user comparing the app's strategies with what a broker's platform offers can place it. The holdings section in Portfolio & Risk records shares a user owns, but the app does not build hedges around them.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter X: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute, collar and protective put education: https://www.cboe.com/education/
- IRS Publication 550, Investment Income and Expenses (straddles and constructive sales): https://www.irs.gov/publications/p550
