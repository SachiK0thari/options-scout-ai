---
id: pmcc
title: "Poor man's covered call (PMCC): a short near-term call written against a LEAPS call"
source: "Cboe Options Institute (diagonal spreads); OCC disclosure document chapter X; PRD.md section 3.5"
url: https://www.cboe.com/education/
kind: concepts
as_of: 2026-11-03
---

# Poor man's covered call (PMCC)

A **poor man's covered call** is a two-leg position: a long, deep in-the-money LEAPS call (expiring a year or more out) and a short, near-term, out-of-the-money call on the same stock. Formally it is a **long call diagonal spread**: different strikes and different expirations. The name comes from the resemblance to a covered call, where an investor who owns 100 shares sells a call against them; here the LEAPS stands in for the shares at a fraction of the capital.

## How the two legs work together

The LEAPS provides the long exposure. The short call collects premium every month or so and caps the position's upside at its strike until it expires. If the stock stays below the short strike, the short call expires worthless, the writer keeps the premium, and a new one can be sold. If the stock rises above the short strike, the short call is assigned: the writer must deliver 100 shares, which they obtain by exercising the LEAPS or, more commonly, by closing both legs at a profit that is bounded by the strike difference.

Each short call sold reduces the net cost of the LEAPS. Over a year of monthly sales the collected premium can offset a large share of the extrinsic value paid for the long leg, which is the whole point of the structure.

## The safety rule and why it exists

A diagonal is only "covered" in a meaningful sense when the short strike is high enough that assignment cannot lock in a loss. If the short call strike were below the LEAPS strike plus the net debit paid, a rally through the short strike would force delivery of shares at a price lower than the position's effective cost. This app therefore rejects any pairing that fails the rule **short strike ≥ LEAPS strike + net debit paid for the LEAPS**. A pair that passes has a worst case on a rally of still being profitable, and the usual worst case on a decline of losing the LEAPS premium less the short premiums collected.

## Net delta

The pair's directional exposure is the LEAPS delta minus the short call delta. A 0.80 delta LEAPS against a 0.25 delta short call leaves 0.55 of stock-like exposure, so the position participates in moderate rallies while the short premium cushions small declines. The risk engine uses this net delta when it adds up the portfolio's total dollar delta against the per-profile cap.

## The screener rules in force

Short calls in this app are chosen 30–45 days to expiration (falling back to 21–60 days only when the strict window has no liquid candidate), with a delta between 0.20 and 0.30, expiring before the LEAPS, and always subject to the safety rule above. The LEAPS leg must itself have passed the LEAPS screener.

## Risks specific to the structure

The short call can be assigned early, most often the day before an ex-dividend date when the call is in the money and its remaining extrinsic value is less than the dividend. The LEAPS does not deliver shares by itself, so an assigned PMCC writer briefly holds a short stock position that must be closed or covered by exercising the LEAPS. Earnings releases inside the short call's life can move the stock through the short strike in one session. And because the two legs have different expirations, their values respond differently to changes in implied volatility; a sharp volatility collapse hurts the long leg more than it helps the short one.

## Sources

- Cboe Options Institute, diagonal and covered call education: https://www.cboe.com/education/
- OCC, *Characteristics and Risks of Standardized Options*, chapter X, including the discussion of spread positions and early assignment: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Rule in force in this app: PRD.md section 3.5 and `config/screener_rules.yaml` (generated document *Rule 3.5: PMCC short call rules*).
