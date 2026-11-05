---
id: early-assignment-dividends
title: "Early assignment and dividends: when American-style options are exercised before expiration"
source: "OCC disclosure document chapter VIII; SEC, 'Ex-Dividend Dates: When Are You Entitled to Stock and Cash Dividends'"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: advanced
as_of: 2026-11-03
---

# Early assignment and dividends

Listed equity and ETF options in the United States are **American style**: the holder can exercise on any business day up to expiration. In practice early exercise is uncommon, because exercising throws away the option's remaining extrinsic value, but there are two situations where it is rational, and a short-option writer should expect to be assigned early in both.

## Calls before an ex-dividend date

A shareholder on the record date receives the dividend; a call holder does not. The **ex-dividend date** is the first day the stock trades without the right to the upcoming dividend, so anyone who wants the dividend must own the shares by the close of the previous trading day. A call holder whose option is in the money can exercise the day before the ex-date, become a shareholder, and collect the dividend. Doing so is worthwhile when the dividend is larger than the extrinsic value they would be giving up. Deep in-the-money calls with little time value on high-dividend stocks are the classic case.

For a **PMCC** writer this means the short call is at risk of assignment the evening before every ex-dividend date on which it is in the money, which would leave the account short 100 shares and liable for the dividend. The usual responses are closing the short call before the ex-date, rolling it to a later expiry, or to let it be assigned and exercise the LEAPS to deliver the shares. Neither is automatic; the writer has to watch the calendar.

## Puts when interest and depth make waiting pointless

A put holder who is deep in the money receives the strike price in cash on exercise. If the put has almost no extrinsic value left, holding it earns nothing, while exercising converts it to cash that can earn interest. Early exercise of puts therefore becomes more likely as the put moves deeper in the money, as expiration approaches, and when interest rates are higher. A cash-secured put that is far in the money after a sharp decline should be treated as likely to be assigned at any time, not only at expiration.

## Dividends and option prices

Option prices incorporate expected dividends before the fact. A stock is expected to fall by the dividend amount on the ex-date, so calls on dividend-paying stocks are cheaper and puts are more expensive than they would be otherwise, all else equal. The pricing model used in this app includes a continuous dividend yield for this reason. A surprise change in a dividend, a special dividend, or a cut, changes option prices without any change in the stock's prospects.

## What this app does about it

The market data layer fetches each ticker's next ex-dividend date. The report shows it alongside the candidate, flags any short call whose life spans an ex-dividend date, and reminds PMCC holders of the assignment risk described above. The app does not try to predict early assignment; it only makes the dates visible so the user can plan. Early exercise, dividends and the detailed settlement mechanics are simplified in this tool and are listed among its known limitations.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter VIII, "Exercise and Assignment", and the discussion of dividends in chapter III: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- U.S. Securities and Exchange Commission, "Ex-Dividend Dates: When Are You Entitled to Stock and Cash Dividends": https://www.sec.gov/fast-answers/answersdividenhtm.html
