---
id: cash-secured-put
title: "Cash-secured put (CSP): selling a put while holding the cash to buy the shares"
source: "OCC, Characteristics and Risks of Standardized Options, chapter X (Principal Risks of Options Positions); PRD.md section 3.3"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: intermediate
as_of: 2026-11-03
---

# Cash-secured put (CSP)

A **cash-secured put** is a short put position in which the writer sets aside enough cash to buy the shares at the strike price if the put is assigned. The writer sells the put, collects the premium up front, and accepts the obligation to buy 100 shares per contract at the strike any time before expiration. The word *secured* refers to the cash: in a cash account the broker holds the full purchase price (strike × 100, less the premium received) as collateral for the whole life of the trade.

## What the position is really saying

Selling a cash-secured put is an agreement to buy a stock at a price below where it trades today, and to be paid for making that agreement. If the stock stays above the strike through expiration, the put expires worthless and the premium is the whole return. If the stock falls below the strike, the writer is **assigned** and owns the shares at the strike price, with an effective cost of strike minus premium. The product promise of this app follows from that second branch: it only screens puts on companies the user would be willing to own if assigned, so assignment is an acceptable outcome rather than a disaster.

## Payoff at expiration

- Maximum gain: the premium received, realised if the stock closes at or above the strike.
- Breakeven: strike − premium.
- Maximum loss: strike − premium, multiplied by 100 per contract, if the stock goes to zero. Unlike a long stock position bought today, the loss starts only below the breakeven, but it is otherwise the same downside as owning the shares from the strike.

The OCC disclosure document states the risk directly: the writer of a put bears the risk of a decline in the price of the underlying to zero, and may be assigned at any time when the option is in the money. A short put is therefore not an "income" position in the sense of a bond coupon; it is a conditional purchase of stock.

## The return measures this app computes

Two numbers appear next to every CSP candidate. **Return on collateral** is premium divided by the cash tied up, (K − premium) × 100, annualised by 365 / DTE so a 40-day trade and a 400-day trade can be compared. In a margin account the position is secured by margin rather than full cash, and **return on margin** uses the Reg T requirement as the denominator instead; see *Naked put on margin* for the difference and the extra risk it brings.

## The screener rules in force

The CSP screener in this repository looks for 30–45 days to expiration, an absolute put delta between 0.15 and 0.30, open interest of at least 500 contracts, a bid-ask spread no wider than 10% of the mid price, a bid above $0.10, and no earnings release before expiry. An IV rank above 30% is preferred but only affects the score. These thresholds live in `config/screener_rules.yaml` and are reproduced in the *Rule 3.3* document so answers can cite the exact value in force.

## What can go wrong

The common failure is not assignment itself but assignment in a stock that has fallen much further than the strike. A put sold at a 0.20 delta on a stock that then drops 30% leaves the writer holding shares worth 30% less than they paid, minus a small premium. That is why the risk engine reports the **realistic loss** of each CSP as the loss at a 30% decline, not the premium at risk, and why the quality gate excludes names whose price action or implied volatility suggests such a drop is being priced in.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter X, "Risks of Option Writers": https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute, cash-secured put education: https://www.cboe.com/education/
- This app's rule in force: PRD.md section 3.3 and `config/screener_rules.yaml` (see the generated document *Rule 3.3: CSP screener rules*).
