---
id: open-interest-vs-volume
title: "Open interest versus volume: what each counts and how the screener reads them"
source: "OCC, Characteristics and Risks of Standardized Options, chapter X (secondary market risk); Cboe Options Institute; config/screener_rules.yaml"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: intermediate
as_of: 2026-11-04
---

# Open interest versus volume: what each counts and how the screener reads them

Two numbers appear next to every option series and are often confused. **Volume** is a count of contracts traded during the current session. **Open interest** (OI) is a count of contracts that exist, that is, positions that have been opened and not yet closed, exercised or expired. Volume is a flow; open interest is a stock. The *Liquidity* document explains why depth is a filter; this one explains how the two counts are produced.

## What a single trade does to each

Every option trade has a buyer and a seller, and each may be opening a new position or closing an existing one. Volume rises by the number of contracts traded, whatever the parties intend. Open interest changes only according to intent:

- Both parties open: OI rises by the trade size.
- Both parties close: OI falls by the trade size.
- One opens and one closes: OI is unchanged; the position has changed hands.

A series can therefore trade 2,000 contracts in a day and finish with unchanged open interest if holders were simply passing contracts to new ones. Suppose a $50 put shows OI of 1,200 and volume of 300: the 300 says there was activity today; the 1,200 says 1,200 contracts were outstanding at the previous close.

## Why open interest is a day old

The OCC computes open interest once a day from the opening and closing designations that clearing members submit after the close, and publishes it before the next session. Intraday, the OI figure on a quote screen is therefore yesterday's number. Volume updates with every trade. A newly listed weekly series can therefore show OI of zero on its first day even if it trades briskly, and a surge of new positions today will not appear until tomorrow.

## Why a liquid chain matters for the exit

A short put is closed by buying the same series back. If the writer wants to close early, to take a profit or to escape a falling stock, someone must be willing to sell it. Open interest is the best available proxy for how many such counterparties exist: a series with thousands of open contracts has holders who will want to adjust and market makers who are already quoting it; a series with 30 contracts open may have a quote only because the exchange requires one, and that quote can be very wide. The OCC disclosure document warns that a secondary market may not exist for a particular series and that a position may then be impossible to close. For a seller that is sharper than for a buyer: a buyer who cannot exit loses at most the premium; a writer who cannot exit keeps the full obligation.

## How the screener uses OI >= 500

The cash-secured put screener requires open interest of at least 500 contracts in the specific series, as a hard filter rather than a score. Three consequences follow. First, a series that will be liquid later can fail today because its OI has not yet been published; the screener accepts that and will pick it up on a later run. Second, volume is not a filter, because one large trade can create a spike in an otherwise dead series. Third, the LEAPS screener uses a lower OI floor of 100, because far-dated series are structurally thinner and the tighter 5% spread cap does more of the work there.

## What can go wrong

Open interest can be concentrated in a few large positions, so a high number does not promise many small counterparties. Delayed free-tier data can carry a stale OI or a zero that means "not reported" rather than "none open". And open interest says nothing about price.

## Where this shows up in OptionsScout

The Candidates tab shows open interest for every CSP, PMCC short leg and LEAPS, and the rule in force, `min_open_interest: 500` for puts and 100 for LEAPS, lives in `config/screener_rules.yaml` and is quoted in the Learn tab's rules documents. The Scout chat explains an exclusion for low OI by citing the threshold rather than a judgment.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on the risk that a secondary market may be unavailable: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute, open interest and volume education: https://www.cboe.com/education/
- FINRA, *Options* investor page: https://www.finra.org/investors/investing/investment-products/options
