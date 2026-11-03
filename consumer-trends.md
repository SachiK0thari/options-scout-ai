# Consumer Trends and Options Strategy Selection

*How much weight consumer trends should carry when picking stocks for LEAPS, PMCCs and cash-secured puts.*

> Not financial advice. This is a framework for thinking about strategy fit, not a recommendation on any position.

---

## Core idea

Consumer trends investing means spotting a trend on social media, in stores or in search data before it shows up in a company's numbers. It is an information edge about **upside surprise on a specific timeline**, usually the next one to three earnings reports.

How much weight it deserves depends on whether the options strategy lets you capture that upside.

---

## LEAPS: high weight

This is the best fit of the three. You're long, the upside is uncapped, and the long expiry gives the trend time to reach the income statement.

- **Use it as a primary selection driver**, but pair it with valuation and balance-sheet checks. You'll hold through more than one catalyst, and a fad can fade before expiry.
- **Favor durable trends over one-quarter fads.** A product that changes a company's growth trajectory suits LEAPS. A viral moment that boosts one quarter is often better played with 3–9 month calls, or shares, that expire just after the relevant earnings, so you aren't paying for time you don't need.
- **Prefer small and mid caps.** One hot product can move revenue meaningfully at a $2B company. At a $500B company it barely registers.

## PMCC (poor man's covered call): low weight

This is where consumer trends conflict with the strategy. The short calls cap exactly the earnings gap-up you're betting on. If your thesis is right, a PMCC often turns a big win into a modest one, and it can force you to roll or close at a bad moment.

- **Pick PMCC underlyings on steadier traits:** a gentle uptrend, liquid options, and decent premium.
- **Use consumer trends mainly for timing the short calls.** If you see a strong positive signal heading into earnings, skip selling calls that cycle or sell them far out of the money. You're effectively converting the position into a plain LEAPS until the catalyst passes.

## CSP (cash-secured put): low to moderate weight, mostly as a screen

Selling a put caps your upside at the premium, so a bullish edge is largely wasted on it. The signal is more useful in the other direction:

- **As a veto:** if trend data shows a brand losing momentum (falling search interest, discounting, fading social buzz), don't sell puts there, however rich the premium looks.
- **As comfort:** a positive signal supports your willingness to own the stock at the strike, which is the real question behind any CSP.
- If you're strongly bullish, a CSP is the wrong tool. Calls or shares express that view better.

---

## Rough guide

| Strategy | Weight of consumer trends | Main role |
|---|---|---|
| LEAPS | High (a co-equal driver with fundamentals and valuation) | Picking the stock |
| PMCC | Low | Deciding when not to sell short calls |
| CSP | Low to moderate | Ruling out stocks whose trend is weakening |

---

## Practical cautions

- **Small-cap option chains are often poor.** Spreads can be wide, and LEAPS may not exist. Check liquidity before the signal excites you.
- **IV crush and "priced in" risk.** Implied volatility is usually high before earnings. Even if you're right about sales, guidance or margins can sink the stock.
- **Confirmation bias.** Once you love a product, everything on your feed looks like evidence. Try to find a disconfirming data point before you size up.
- **The edge decays.** By the time a trend is all over TikTok and financial Twitter, much of it may already be in the price.

---

## Sources and basis for this logic

### Standard options mechanics

These points are textbook and verifiable in any serious options text:

- A covered call or PMCC short call caps your upside; a short put's profit is capped at the premium.
- Implied volatility tends to rise before earnings and collapse after (IV crush).
- Long-dated options cost more in time value.

References:
- Lawrence McMillan, *Options as a Strategic Investment*
- Sheldon Natenberg, *Option Volatility and Pricing*
- OCC, *Characteristics and Risks of Standardized Options*
- tastytrade, which popularized the term "poor man's covered call" and has free material on PMCCs and CSPs

### Origins of consumer trends

- **Chris Camillo**, who coined the term "social arbitrage" for this approach. *Laughing at Wall Street* and his later work describe spotting consumer trends early and positioning before earnings reveal them. He has generally favored shares and shorter-dated options timed around the catalyst.
- **Peter Lynch**, *One Up on Wall Street*. "Invest in what you know" is the older ancestor of the concept.

### Academic support for the underlying edge

- Da, Engelberg & Gao, "In Search of Attention," *Journal of Finance* (2011). Google search volume predicts short-term price moves.
- Bartov, Faurel & Mohanram, "Can Twitter Help Predict Firm-Level Earnings and Stock Returns?" *The Accounting Review* (2018). Aggregated tweet sentiment predicts earnings surprises and announcement returns.
- Froot, Kang, Ozik & Sadka, "What Do Measures of Real-Time Corporate Sales Say About Earnings Surprises and Post-Announcement Returns?" *Journal of Financial Economics* (2017). Real-time sales indicators predict surprises.
- Katona, Painter, Patatoukas & Zeng, research on satellite parking-lot data. Alternative data gives an edge to whoever has it first, supporting the idea that the edge decays as information spreads.

*These citations were given from memory and have not been re-verified.*

### What is judgment, not established finding

The weightings themselves (high for LEAPS, low for PMCC, screen-only for CSP), the "veto for CSPs" idea and the small-cap emphasis are a synthesis of the two bodies of knowledge above. No known study tests consumer trends specifically across these three option structures, so treat that part as a reasoned framework rather than a proven result.
