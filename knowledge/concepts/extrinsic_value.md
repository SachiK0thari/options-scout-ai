---
id: extrinsic-value
title: "Intrinsic and extrinsic value: what a LEAPS buyer actually pays for"
source: "OCC disclosure document chapter II (Options Nomenclature); PRD.md section 3.6"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
as_of: 2026-11-03
---

# Intrinsic and extrinsic value

Every option premium can be split into two parts. **Intrinsic value** is the amount by which the option is in the money: for a call, the stock price minus the strike when positive, otherwise zero; for a put, the strike minus the stock price when positive, otherwise zero. **Extrinsic value**, also called time value, is everything else: premium minus intrinsic value. An out-of-the-money option is pure extrinsic value. At expiration extrinsic value is always zero and the option is worth exactly its intrinsic value.

## Why extrinsic value exists

Extrinsic value is the price of possibility. A call that is out of the money today is worth something because the stock may rise above the strike before expiration; a call that is deep in the money carries extrinsic value because there is still a chance the stock falls through the strike and the holder is protected from losses below it. Extrinsic value therefore grows with time to expiration and with implied volatility, is largest for at-the-money options, and shrinks toward zero as an option moves deep into or far out of the money. Interest rates and expected dividends shift it slightly: higher rates add extrinsic value to calls and subtract from puts; dividends do the reverse.

## The LEAPS buyer's cost

For a deep in-the-money LEAPS call, extrinsic value is the true cost of the position. The intrinsic part is simply stock exposure bought at a discount to the share price; it rises and falls with the stock and is returned at expiration if the stock has not fallen through the strike. The extrinsic part is spent. A $100 stock, a $70 strike and a $33 price mean $30 of intrinsic value and $3 of extrinsic value, with a breakeven at expiration of $103: the stock must rise 3% over the option's life just to cover the time value paid.

This app normalises that cost by time so options of different lengths can be compared. **Extrinsic value per year** is (extrinsic / stock price) / (DTE / 365). The LEAPS screener accepts candidates only when this figure is at most 5% of the stock price per year, and scores lower values higher, because every point of extrinsic value is a point the stock has to climb before the position beats owning the shares outright.

## The premium seller's income

For the writer of a cash-secured put the same quantity is the income. A 0.25 delta put is out of the money, so its whole premium is extrinsic value, and all of it accrues to the writer if the stock stays above the strike. The CSP screener's bid above $0.10 and its 30 to 45 day window exist to make sure that extrinsic value is worth collecting after spreads and commissions and decays quickly while it is held.

## Extrinsic value and early exercise

An option is exercised early only when its extrinsic value has fallen below what the holder gains by exercising: the dividend for a call before an ex-date, or the interest on the strike for a deep put. Watching the extrinsic value of a short option is therefore the simplest early-assignment warning. When it approaches zero, assignment can come any day.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter II, definitions of intrinsic value and time value: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Formulas in force in this app (intrinsic, extrinsic, extrinsic per year, breakeven): PRD.md section 3.6.
