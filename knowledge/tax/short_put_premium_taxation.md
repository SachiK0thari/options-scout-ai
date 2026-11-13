---
id: short-put-premium-taxation
title: "Short put premium: when the premium is taxed and why the gain is short-term"
source: "IRS Publication 550, Investment Income and Expenses, chapter 4, Writers of puts and calls; 26 U.S.C. §1234(b)"
url: https://www.irs.gov/publications/p550
kind: tax
level: intermediate
as_of: 2026-11-13
---

# Short put premium: when the premium is taxed and why the gain is short-term

When an investor sells (writes) a put, the broker credits the **premium** to the account on the day of the trade. It is natural to assume that cash is income in the year it arrives. For U.S. federal tax purposes it is not. IRS Publication 550, in the section titled "Writers of puts and calls", says that a writer does not include the premium in income when it is received. The tax event waits until the option position is closed, and how it closes decides what is reported. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## Three ways a short put can end

A short put has three possible endings, and Publication 550 gives each a different result:

- **Expires worthless.** The writer keeps the whole premium and reports it as a **short-term capital gain** in the year the option expires.
- **Closed by buying it back** (a "closing transaction"). The writer reports the difference between the premium received and the price paid to close as a short-term capital gain or loss, in the year of the buy-back.
- **Assigned.** The writer buys the shares at the strike. No gain or loss is reported on the option itself; instead the premium reduces the cost basis of the shares. That case is covered in the document *Assignment and cost basis*.

## Why "short-term" regardless of time open

The usual rule for capital assets is that something held more than one year produces a long-term gain. Written options are an exception. Section 1234(b) of the Internal Revenue Code says that, for a non-dealer, gain or loss from any closing transaction on a written option, and gain on the lapse of a written option, is treated as **short-term** capital gain or loss. The writer never owned an asset whose holding period could run; the writer took on an obligation and was paid for it. So a put written 400 days before expiry and left to expire still produces a short-term gain. The screener in this app looks at 30-45 day puts, where the question rarely arises, but the rule matters for anyone who also writes long-dated puts.

## A worked example

Suppose an investor writes one put with a $50 strike and receives a $1.20 premium, so $120 for the contract, and suppose the trade is opened in November and the option expires in the following January. Nothing is reported for November's tax year. If the put expires worthless in January, $120 of short-term capital gain is reported for the January tax year. If instead the investor buys the put back in December for $0.40, the result is a $80 short-term gain in December's tax year. If the stock falls and the buy-back costs $3.00, the result is a $180 short-term capital loss. Commissions and fees adjust these amounts; the example ignores them.

## What can go wrong

Because recognition waits for the close, a premium collected in one year can become taxable in the next, which surprises people who budget for taxes using the cash they saw arrive. A string of expired puts is a string of short-term gains, which Tax Topic 409 explains are netted against short-term losses and then taxed differently from long-term gains; this document does not state rates, because they depend on the reader's situation and change over time. Finally, a loss from buying back a put can be caught by the wash sale rule if, within 30 days before or after, the investor acquires substantially identical stock or a contract or option to acquire it (the 61-day window); see *Wash sales and options*.

## Where this shows up in OptionsScout

The Candidates tab shows each CSP's premium and annualised return on collateral. Those figures are pre-tax, computed by tested Python code, and the Compliance agent requires any explanation that mentions after-tax results to carry a disclaimer. The Tax & Accounts page in Learn links to this document so a reader can see why the premium shown is not "income" in the tax sense until the position closes.

## Sources

- IRS Publication 550, *Investment Income and Expenses*, chapter 4, "Writers of puts and calls": https://www.irs.gov/publications/p550
- 26 U.S.C. Section 1234(b), options to buy or sell - treatment of grantor of option: https://www.law.cornell.edu/uscode/text/26/1234
- IRS Tax Topic 409, Capital gains and losses: https://www.irs.gov/taxtopics/tc409
