---
id: tbills-and-the-risk-free-rate
title: "Treasury bills and the risk-free rate: the 13-week yield in option prices and projections"
source: "TreasuryDirect, Treasury Bills (U.S. Department of the Treasury)"
url: https://www.treasurydirect.gov/marketable-securities/treasury-bills/
kind: basics
level: beginner
as_of: 2026-11-04
---

# Treasury bills and the risk-free rate

A **Treasury bill** (T-bill) is a short-term loan to the U.S. government. TreasuryDirect describes bills as securities with maturities of one year or less, sold at a discount to their face value and paying face value at maturity, with the difference being the interest. Bills are issued in 4-, 8-, 13-, 17-, 26- and 52-week terms. Because they are backed by the Treasury and mature quickly, their yield is used throughout finance as the **risk-free rate**: the return available for taking essentially no credit risk and little interest-rate risk over a short period.

## The 13-week rate

The yield on the 13-week (three-month) bill is the most widely quoted short rate. Market data vendors publish it as the index symbol **^IRX**, quoted in percent. Suppose the 13-week bill auctions at a price of $98.90 per $100 of face value. The holder receives $100 after 91 days, a gain of $1.10, which annualises to roughly 4.4%. The rate changes at every weekly auction and moves with the Federal Reserve's policy rate, so a document can describe how it is used but not what it is today.

## Why it is inside every option price

The Black-Scholes model, which the app uses to compute delta and probability of expiring out of the money, takes the risk-free rate as one of its inputs. The rate enters because the strike price is paid in the future and must be discounted to today, and because the model's no-arbitrage argument assumes the hedger can borrow or lend at that rate. A higher rate makes calls slightly more valuable and puts slightly less valuable, all else equal. For the 30- to 45-day puts the CSP screener looks at, the effect is small: a one-percentage-point change in the rate moves a $50 strike's present value by about four cents. For a LEAPS call with 500 days to expiry, the same change matters several times more.

## The rate as the floor for cash

The risk-free rate is also what idle cash can earn. A cash reserve held in a money market fund or in bills itself earns roughly the 13-week rate, less fund expenses. This matters for a put writer in two ways. First, the collateral behind a cash-secured put is cash, and whether a broker pays interest on it, and how much, changes the all-in return. Second, the bill yield is the alternative every short put is competing with: a put that annualises to 5% of collateral when bills pay 4.5% is being paid half a point for taking equity risk.

## What can go wrong

The "free" in risk-free rate refers only to default risk on a 13-week bill held to maturity. It does not mean the rate is stable, and it does not mean the purchasing power of the proceeds is preserved: when inflation runs above the bill yield, the real return is negative. The rate the app fetches is delayed free-tier data and can be stale or unavailable, in which case the engine substitutes a configured fallback and labels it; a projection built on a stale rate is only as current as the rate. Finally, a brokerage's cash sweep may pay far less than the bill yield, so the floor an investor actually earns on collateral can be well below ^IRX.

## Where this shows up in OptionsScout

The regime node calls `get_risk_free_rate()`, which reads ^IRX and converts the percentage to a fraction, falling back to a constant when the feed has no bill index. Every Black-Scholes calculation in the screener and the risk engine uses that single value, and the report header prints it with its source. In the Goal Planning agent's projections, the profile's cash reserve is assumed to earn the risk-free rate rather than the portfolio return, so a conservative profile's 35% reserve grows at the bill yield in both the base and stress paths. The number is stated on the Goals tab beside the assumed return so the user can see the two rates separately.

## Sources

- TreasuryDirect, Treasury Bills: https://www.treasurydirect.gov/marketable-securities/treasury-bills/
- SEC investor.gov, Bonds, on how Treasury securities differ from other fixed income: https://www.investor.gov/introduction-investing/investing-basics/investment-products/bonds-or-fixed-income-products/bonds
- Cboe Options Institute, education on option pricing inputs: https://www.cboe.com/education/
