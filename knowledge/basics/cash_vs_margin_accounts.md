---
id: cash-vs-margin-accounts
title: "Cash versus margin accounts: borrowing, Regulation T, and why the app asks which one you have"
source: "FINRA, Margin Accounts (investor page); Regulation T, 12 CFR Part 220; FINRA Rule 4210"
url: https://www.finra.org/investors/investing/investment-accounts/margin-accounts
kind: basics
level: beginner
as_of: 2026-11-13
---

# Cash versus margin accounts: borrowing, Regulation T, and why the app asks which one you have

A brokerage account comes in two basic forms. In a **cash account**, every purchase is paid for in full with money already in the account, and every short option is backed by cash or shares already held. In a **margin account**, the broker extends a line of credit secured by the securities in the account, so an investor can buy more than their cash would allow and can take on obligations, such as short puts, that are backed only partly by cash.

## Borrowing on margin

**Margin** is a loan from the broker, with the account's holdings as collateral. Suppose an investor has $10,000 and buys $20,000 of stock on margin; the broker lends the other $10,000 and charges interest on it daily. If the stock rises 10%, the investor's equity rises from $10,000 to $12,000, a 20% gain. If the stock falls 10%, equity falls to $8,000, a 20% loss. Margin magnifies both outcomes. If equity falls below the broker's **maintenance requirement**, the investor receives a **margin call** and must deposit cash or the broker sells holdings, at a time of the broker's choosing, to restore it. The broker may also sell without notice, choosing what to sell, and a loss can exceed the deposit; the investor owes the difference. FINRA's investor page on margin accounts sets out these risks.

## Regulation T in one paragraph

**Regulation T** is the Federal Reserve Board rule, codified at 12 CFR Part 220, that governs how much credit a broker may extend to a customer. Its best-known provision sets the **initial margin** on a stock purchase at 50%: an investor must put up at least half the purchase price in cash. Reg T also defines the cash account and its payment rules, which is where the T+1 settlement and good-faith rules described in the *Settlement* document come from. FINRA Rule 4210 adds the ongoing **maintenance margin**, generally 25% of the market value of long stock, and sets the margin for short options, which for an uncovered equity put is typically 20% of the stock price plus the premium, less any out-of-the-money amount, with a minimum of 10% of the strike. Brokers may and often do require more than these minimums.

## Short puts in each account type

In a cash account a short put must be **cash-secured**: the broker holds strike times 100, less the premium, for the life of the trade. In a margin account the same put can be written against the much smaller Reg T and FINRA requirement, leaving the rest of the account free. The second arrangement is often called a **naked put**. When the Setup tab records a margin account, this app sizes its short puts on that Reg T requirement, so they are naked puts and the report labels them that way; it also shows the cash every put would need if all were assigned, which a portfolio limit caps at the account's buying power. A $120 premium on a $50 strike put is 2.4% of $4,880 of cash collateral, but around 12% of a $1,000 margin requirement. The higher figure is not extra return; it is the same return with the risk of owing $5,000 on assignment against a far smaller reserve.

## What can go wrong

Margin interest is a steady cost that continues in flat markets. A margin call in a falling market forces sales at the worst moment, and a broker can raise maintenance requirements with little notice, particularly on volatile stocks. In a cash account the risks are different: assignment with unsettled funds, or a short put whose collateral has been quietly consumed by another purchase, can produce violations and restrictions. Neither account type changes the fact that a put writer can lose the full strike value if the stock goes to zero.

## Where this shows up in OptionsScout

The Setup tab asks for the account type because the arithmetic depends on it. For a cash account the Candidates tab reports **return on collateral** using the full cash-secured amount; for a margin account it adds **return on margin** using the Reg T and FINRA requirement, and the Portfolio & Risk tab applies a **max margin usage** constraint ({{risk.conservative.max_margin_usage}}, {{risk.balanced.max_margin_usage}} or {{risk.aggressive.max_margin_usage}} of buying power by profile). "Cash-secured" in the Scout chat means the full purchase price is treated as tied up. The Tax & Accounts page in Learn covers account types in more depth.

## Sources

- FINRA, *Margin Accounts* investor page: https://www.finra.org/investors/investing/investment-accounts/margin-accounts
- Regulation T, 12 CFR Part 220 (Credit by Brokers and Dealers): https://www.ecfr.gov/current/title-12/chapter-II/subchapter-A/part-220
- FINRA Rule 4210, Margin Requirements: https://www.finra.org/rules-guidance/rulebook/finra-rules/4210
- OCC, *Characteristics and Risks of Standardized Options*: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
