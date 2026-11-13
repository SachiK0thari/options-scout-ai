---
id: risk-tolerance-and-time-horizon
title: "Risk tolerance and time horizon: the two inputs behind a risk profile"
source: "SEC investor.gov, Introduction to Investing (assessing your risk tolerance, time horizon and goals)"
url: https://www.investor.gov/introduction-investing
kind: basics
level: beginner
as_of: 2026-11-13
---

# Risk tolerance and time horizon

**Risk tolerance** is how much decline in the value of an account an investor can absorb without being forced, financially or emotionally, to sell. **Time horizon** is how long the money can stay invested before it is needed. The SEC's investor.gov introduction treats the two together because they constrain each other: a long horizon lets an investor wait out a decline, and so supports a higher tolerance; a short horizon does not, whatever the investor's temperament.

## Risk tolerance has two parts

The first part is **capacity**, which is arithmetic. An investor with a stable job, no debt and ten years before the money is needed can recover from a 30% decline. One who needs the money for a house deposit in eighteen months cannot. The second part is **willingness**, which is temperament. Some investors watch a 20% drop and do nothing; others sell at the bottom and lock in the loss. Willingness is only discovered in a real decline, so questionnaires overstate it in calm markets. The lower of capacity and willingness is the one that binds.

## Time horizon changes what "risk" means

Over a few months, the risk of a stock position is that its price falls before it must be sold. Over twenty years, the larger risk is that cash and bonds fail to grow enough to meet the goal. The same 30% drawdown is a crisis on a one-year horizon and a footnote on a thirty-year one. This is why guidance on investor.gov ties the allocation between stocks, bonds and cash to when the money will be spent rather than to a view of the market.

## How the app encodes them

OptionsScout collapses both inputs into one of three **risk profiles**, chosen on the Setup tab: conservative, balanced and aggressive, as named in `config/risk_profiles.yaml`. The profile sets the split of buying power between cash-secured puts, LEAPS calls and a cash reserve, and the tightness of the portfolio constraints. The conservative profile keeps 35% in cash and caps the realistic loss of any single position at 2% of the account; the aggressive profile keeps 20% in cash and allows 5%. A user who selects conservative is saying, in the app's language, that a 30% drop in one stock must not cost more than 2% of the account. See the *Risk profiles* document for the full table.

## Why a short horizon and short puts conflict

A cash-secured put is a conditional purchase of stock. If it is assigned, the writer owns 100 shares that may then fall further, and the sensible response is to hold them until they recover. That requires time. Suppose an investor needs $20,000 in six months and writes a put at a $50 strike that is assigned at a market price of $42. The shares are worth $4,200 against $5,000 of collateral, and there is no horizon left to wait. The premium, perhaps $120, does not change the arithmetic. The screened strategies all presume the user can hold shares through a decline; an investor with a short horizon cannot make that presumption, and the cash reserve inside the app is not a substitute for cash held outside it.

## What can go wrong

Profiles are coarse. Three buckets cannot capture a household with one short-horizon goal and one long one, and the app has no way to test willingness; a user who picks aggressive in a calm market may discover a conservative temperament in the first 20% decline. The stress test shows the loss at -10%, -20% and -30% so that discovery can happen on paper first, but a number on a screen is not the same as a number in an account.

## Where this shows up in OptionsScout

The Setup tab asks for buying power, account type and risk profile before any screening runs. The profile then drives the allocation and constraint tables on the Portfolio & Risk tab, and the Goal Planning agent uses the profile's assumed-return cap to judge whether a goal fits. The app never infers a profile from behaviour; the choice is the user's, and the Compliance agent requires every sized recommendation to name the profile it was sized under.

## Sources

- SEC investor.gov, Introduction to Investing: https://www.investor.gov/introduction-investing
- SEC investor.gov, Glossary (risk tolerance, time horizon, asset allocation): https://www.investor.gov/introduction-investing/investing-basics/glossary
- OCC, Characteristics and Risks of Standardized Options, chapter X, on assignment risk for put writers: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
