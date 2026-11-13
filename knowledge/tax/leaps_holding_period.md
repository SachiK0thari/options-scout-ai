---
id: leaps-holding-period
title: "LEAPS and the holding period: sale, expiry and exercise of a long-dated call"
source: "IRS Publication 550, Investment Income and Expenses, chapter 4, Holders of puts and calls; Holding period"
url: https://www.irs.gov/publications/p550
kind: tax
level: intermediate
as_of: 2026-11-13
---

# LEAPS and the holding period: sale, expiry and exercise of a long-dated call

A **LEAPS call** (Long-term Equity AnticiPation Securities) is a listed call option with a long time to expiration, typically more than a year when bought. This app screens LEAPS calls with a delta of 0.70-0.85, which behave much like owning the shares with less capital tied up. Because a LEAPS can be held for more than a year, it is one of the few option positions where the long-term holding period rule can apply to the option itself. IRS Publication 550 covers the holder's side in the section "Holders of puts and calls". This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## Selling the LEAPS

If the holder sells the call before expiration, the difference between the sale proceeds and the premium paid (the option's **basis**) is a capital gain or loss. Its character follows the ordinary test in Tax Topic 409: held more than one year, long-term; held one year or less, short-term. The holding period begins the day after the option is bought. Suppose an investor buys one LEAPS call with a $100 strike for $25.00 per share ($2,500) and sells it fourteen months later for $35.00 ($3,500). The result is a $1,000 long-term capital gain. Had the sale occurred after eleven months, the same $1,000 would be short-term.

## Letting it expire

If the call expires worthless, Publication 550 treats the holder as having sold it on the expiration date for nothing. The whole premium is a capital loss, long-term or short-term depending on how long the option was held up to that date. In the example above, a $2,500 loss realised on expiry after more than a year is a long-term capital loss. A LEAPS bought in the app's delta range is deep in the money, so a total loss requires a large decline in the stock, but it is the maximum loss and it is realised only when the option is sold or expires.

## Exercising

Exercise is not a taxable event for the holder. Publication 550 says that when you exercise a call, you add the cost of the call to the basis of the stock you receive. In the example, exercising means paying $10,000 for 100 shares; the basis is $12,500, or $125 per share, which is the strike plus the premium. No gain or loss is reported until the shares are sold. The important and often missed consequence is that the **holding period of the shares starts the day after exercise**. The fourteen months the option was held do not carry over. Shares sold within a year of exercise produce a short-term result even though the overall position was open for more than two years.

## What can go wrong

The one-year boundary is a cliff. An investor who sells a LEAPS a few days short of the anniversary converts what would have been a long-term gain into a short-term one, and nothing in the option's quote warns of this. The reverse trap is exercising near the anniversary in the belief that the clock has been met; exercise resets it. A LEAPS also decays: the time value paid up front is lost by expiry whatever the stock does, and a long-term loss is still a loss. Finally, if the LEAPS is the long leg of a poor man's covered call, the straddle rules in section 1092 can eliminate the holding period of a LEAPS not yet held more than a year, which then starts again only when the short call is closed; see *Qualified covered calls and the straddle rules*.

## Where this shows up in OptionsScout

The Candidates tab shows the expiration date and DTE of every LEAPS candidate. The holdings section in Portfolio & Risk records shares only, with no purchase dates, so the app cannot tell where a held LEAPS stands against the one-year mark; the broker's records can. The usual advice to roll a LEAPS below about 240 days is about the trade, not the tax year; the document *LEAPS: exercise versus sale* explains the difference.

## Sources

- IRS Publication 550, *Investment Income and Expenses*, chapter 4, "Holders of puts and calls" and "Holding Period": https://www.irs.gov/publications/p550
- IRS Tax Topic 409, Capital gains and losses: https://www.irs.gov/taxtopics/tc409
- Treas. Reg. § 1.1092(b)-2T(a), holding period of a straddle position: https://www.law.cornell.edu/cfr/text/26/1.1092(b)-2T
- 26 U.S.C. Section 1234, options to buy or sell: https://www.law.cornell.edu/uscode/text/26/1234
