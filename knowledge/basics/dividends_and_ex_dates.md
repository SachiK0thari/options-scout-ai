---
id: dividends-and-ex-dates
title: "Dividends and ex-dividend dates: the four dates, the price drop, and why they matter for a short call"
source: "SEC investor.gov, Ex-Dividend Dates (glossary); OCC, Characteristics and Risks of Standardized Options, chapter X"
url: https://www.investor.gov/introduction-investing/investing-basics/glossary/ex-dividend-dates
kind: basics
level: beginner
as_of: 2026-11-13
---

# Dividends and ex-dividend dates: the four dates, the price drop, and why they matter for a short call

A **dividend** is a cash payment a company makes to its shareholders, usually quarterly, expressed per share. A holder of 100 shares of a company paying $0.60 per share receives $60. Dividends are declared by the board of directors and are never promised in advance; a company can raise, cut or suspend them.

## The four dates

Every dividend passes through four dates, and the SEC's glossary entry describes them.

- **Declaration date**: the board announces the amount and the other three dates.
- **Ex-dividend date** (the **ex-date**): the first trading day on which a buyer of the stock does **not** receive the upcoming dividend. To be paid, an investor must own the shares before the market opens on this day.
- **Record date**: the day the company checks its shareholder list. Since U.S. stock trades settle one business day after the trade (T+1), the ex-date and record date now usually fall on the same day.
- **Payment date**: the day the cash arrives in the shareholder's account, often two to four weeks after the record date.

## The price drop on the ex-date

A dividend is not a bonus. On the ex-date, all else equal, the share price opens lower by roughly the dividend amount, because the cash is leaving the company and new buyers no longer receive it. Suppose a stock closes at $100.00 the day before the ex-date with a $0.60 dividend; it would be expected to open near $99.40. Market movements usually swamp this adjustment, so the drop is rarely visible to the eye, but exchanges and option pricing models account for it precisely. Buying a stock just to collect a dividend and selling afterwards does not create value by itself, and in a taxable account it can create a tax bill.

## Why an ex-date before expiry matters for a short call

In a **poor man's covered call (PMCC)**, an investor holds a long-dated call (a LEAPS) and sells a shorter-dated call against it. The short call's holder has the right to exercise and take delivery of 100 shares. Option holders do not receive dividends; shareholders do. So on the day before an ex-date, a holder of an in-the-money call with very little time value left has a reason to exercise early: by converting the call into shares that evening, they collect the dividend the next morning.

For the PMCC writer this means **early assignment risk** concentrates on the day before the ex-date. If assigned, the writer must deliver 100 shares they do not own (the long LEAPS is a right, not shares), which the broker resolves by creating a short stock position or by requiring the LEAPS to be exercised, giving up all of its remaining time value. Either outcome is a loss relative to simply holding the spread. The practical rule the OCC disclosure document implies is that a short call that is in the money, with time value smaller than the pending dividend, is a candidate for early exercise on the day before the ex-date.

## What can go wrong

Dividends can be cut with no notice, and a cut often arrives alongside a large price fall. Special dividends can trigger adjustments to option contract terms. For a cash-secured put writer, an ex-date is less dangerous than for a call writer, but a put holder has no dividend reason to exercise early, so the risk there comes from a deep in-the-money put instead. None of this is predictable to the day, which is why it is handled as a date check rather than a forecast.

## Where this shows up in OptionsScout

The screeners price every option with the stock's dividend yield but do not check the calendar for ex-dividend dates: none of the app's data providers supplies them, so no short call is flagged for spanning one. Check the next ex-dividend date with the broker before writing a short call, the PMCC short leg in particular. The CSP screener uses a different calendar check, excluding expiries that span an earnings date, which the *P/E and earnings* document explains. The app's market data is delayed free-tier data, so dividend dates are only as current as the feed that supplies them.

## Sources

- SEC investor.gov, *Ex-Dividend Dates*: https://www.investor.gov/introduction-investing/investing-basics/glossary/ex-dividend-dates
- SEC investor.gov, *Stocks* (dividends and shareholder rights): https://www.investor.gov/introduction-investing/investing-basics/investment-products/stocks
- OCC, *Characteristics and Risks of Standardized Options*, chapter X (early exercise and assignment risk): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
