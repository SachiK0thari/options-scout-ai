# OptionsScout AI screening report: run `<run_id>`
_As of 2026-10-27 20:24 UTC · fixture market data · LLM mode fixture · delayed data, for education only._

> Educational screening tool. Not investment, tax or legal advice. Options involve significant risk, including loss exceeding the premium received on margin. Data may be delayed or inaccurate.

## Profile
**Buying power** $100,000 · **Account value** $100,000 · **Account** margin · **Risk** balanced · **Strategies** csp, leaps, pmcc · **Max positions** 8

## Regime and allocation
VIX 17.51 (57th percentile, normal), risk-free rate 4.04% (fixture data).

| Bucket | Share | Dollars |
|---|---|---|
| CSP collateral | 45% | $45,000 |
| LEAPS / PMCC | 25% | $25,000 |
| Cash reserve | 30% | $30,000 |

- balanced profile baseline: CSP 45%, LEAPS/PMCC 25%, cash reserve 30%.
- VIX 17.51 sits at the 57th percentile of its last year (normal).
- Normal-IV regime: no tilt applied.
- The cash reserve is never reduced by the tilt.

## Trend board (consumer trends)
| Entity | Type | Ticker | Investable | Score | Velocity z | Coverage gap | Evidence | Flags |
|---|---|---|---|---|---|---|---|---|
| CAVA | company | CAVA | yes | 90 | +4.0 | +4.0 | 4 |  |
| On Cloud | brand | ONON | yes | 89 | +4.0 | +4.0 | 4 |  |
| HOKA | brand | DECK | yes | 89 | +4.0 | +2.1 | 4 |  |
| e.l.f. | brand | ELF | yes | 86 | +4.0 | +2.3 | 4 |  |
| Crocs | brand | CROX | yes | 86 | +4.0 | +4.0 | 4 |  |
| Owala | brand | n/a | no | 86 | +4.0 | +4.0 | 4 | not_investable |
| Dutch Bros | company | BROS | yes | 86 | +4.0 | +3.8 | 4 |  |
| Abercrombie | company | ANF | yes | 84 | +4.0 | +3.3 | 4 |  |
| Oura Ring | product | n/a | no | 81 | +4.0 | +3.0 | 4 | not_investable |
| Olipop | brand | n/a | no | 81 | +4.0 | +4.0 | 4 | not_investable |

Universe considered: NKE, COST, AAPL, MSFT, SBUX, SPY, QQQ

## Good-to-own quality screen
| Ticker | Name | Sector | Quality | 30d vol | Below 90d high | Why it's on the list |
|---|---|---|---|---|---|---|
| SPY | SPDR S&P 500 ETF | ETF | 86 | 10% | 1% | Owns the whole S&P 500; the most liquid option chain in the market. |
| AAPL | Apple | Technology | 82 | 16% | 0% | Huge installed base, large recurring services revenue, consistent buybacks and dividend. |
| COST | Costco Wholesale | Consumer Defensive | 77 | 17% | 3% | Membership model with very high renewal rates and decades of dividend growth. |
| MSFT | Microsoft | Technology | 72 | 21% | 2% | Enterprise software and cloud with long-term contracts and 20+ years of dividend growth. |
| QQQ | Invesco Nasdaq-100 ETF | ETF | 70 | 19% | 5% | Owns the 100 largest Nasdaq companies; very liquid options. |
| SBUX | Starbucks | Consumer Cyclical | 66 | 23% | 5% | Global coffee brand with a 14-year streak of dividend increases. |
| NKE | Nike | Consumer Cyclical | 46 | 28% | 15% | Leading athletic brand with 20+ years of dividend increases. |

## CSP candidates
| ID | Strike | Expiry | DTE | Delta | Mid | Collateral | Reg T margin | Ann. return | P(OTM) | OI / spread | IV rank | Earnings | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CSP-NKE-2026-11-20-35P | 35 | 2026-11-20 | 24 | -0.23 | 0.56 | $3,444 | $552 | 25.0% | 73% | 20,879/9% | 94%* | no | dte_outside_preferred |
| CSP-SPY-2026-11-30-755P | 755 | 2026-11-30 | 34 | -0.30 | 7.20 | $74,780 | $14,647 | 10.3% | 69% | 3,326/1% | 85%* | no |  |
| CSP-SPY-2026-11-30-754P | 754 | 2026-11-30 | 34 | -0.29 | 6.98 | $74,702 | $14,526 | 10.0% | 70% | 681/1% | 85%* | no |  |
| CSP-SPY-2026-11-30-752P | 752 | 2026-11-30 | 34 | -0.27 | 6.58 | $74,542 | $14,286 | 9.5% | 71% | 1,408/1% | 85%* | no |  |
| CSP-SPY-2026-11-27-750P | 750 | 2026-11-27 | 31 | -0.25 | 5.91 | $74,409 | $14,018 | 9.4% | 73% | 1,081/1% | 85%* | no |  |
| CSP-SPY-2026-11-30-750P | 750 | 2026-11-30 | 34 | -0.26 | 6.21 | $74,379 | $14,048 | 9.0% | 73% | 9,144/1% | 85%* | no |  |
| CSP-SPY-2026-11-30-749P | 749 | 2026-11-30 | 34 | -0.25 | 6.04 | $74,296 | $13,931 | 8.7% | 74% | 682/0% | 85%* | no |  |
| CSP-SPY-2026-11-30-748P | 748 | 2026-11-30 | 34 | -0.24 | 5.87 | $74,214 | $13,814 | 8.5% | 74% | 917/1% | 85%* | no |  |
| CSP-SPY-2026-11-30-747P | 747 | 2026-11-30 | 34 | -0.23 | 5.70 | $74,130 | $13,697 | 8.2% | 75% | 620/1% | 85%* | no |  |
| CSP-SPY-2026-11-27-745P | 745 | 2026-11-27 | 31 | -0.22 | 5.10 | $73,990 | $13,437 | 8.1% | 77% | 745/1% | 85%* | no |  |
| CSP-SPY-2026-11-30-746P | 746 | 2026-11-30 | 34 | -0.23 | 5.54 | $74,046 | $13,581 | 8.0% | 76% | 1,552/1% | 85%* | no |  |
| CSP-SPY-2026-11-30-745P | 745 | 2026-11-30 | 34 | -0.22 | 5.39 | $73,961 | $13,466 | 7.8% | 77% | 3,263/1% | 85%* | no |  |
| CSP-SPY-2026-11-27-743P | 743 | 2026-11-27 | 31 | -0.20 | 4.82 | $73,818 | $13,209 | 7.7% | 78% | 555/1% | 85%* | no |  |
| CSP-SPY-2026-11-30-744P | 744 | 2026-11-30 | 34 | -0.21 | 5.24 | $73,876 | $13,351 | 7.6% | 77% | 1,214/1% | 85%* | no |  |
| CSP-SPY-2026-11-27-742P | 742 | 2026-11-27 | 31 | -0.20 | 4.68 | $73,732 | $13,095 | 7.5% | 79% | 675/1% | 85%* | no |  |

\* IV rank from HV proxy (fewer than 30 stored IV snapshots).

## LEAPS / PMCC candidates
| ID | Strike | Expiry | DTE | Delta | Mid | Extrinsic/yr | Breakeven | OI / spread | PMCC short call | Flags |
|---|---|---|---|---|---|---|---|---|---|---|
| LEAPS-NKE-2028-12-15-20C | 20 | 2028-12-15 | 780 | 0.82 | 18.80 | 1.5% | 38.80 | 575/5% | 40C 2026-11-20 Δ0.30 mid 0.72 (net Δ 0.52, safety +1.20) | high_iv_rank |
| LEAPS-COST-2028-12-15-800C | 800 | 2028-12-15 | 780 | 0.78 | 297.00 | 4.9% | 1097.00 | 172/3% | n/a | high_iv_rank |
| LEAPS-AAPL-2028-12-15-230C | 230 | 2028-12-15 | 780 | 0.85 | 146.30 | 3.9% | 376.30 | 924/3% | n/a | high_iv_rank |
| LEAPS-AAPL-2029-01-19-240C | 240 | 2029-01-19 | 815 | 0.84 | 139.95 | 4.2% | 379.95 | 181/3% | n/a | high_iv_rank |
| LEAPS-AAPL-2028-12-15-240C | 240 | 2028-12-15 | 780 | 0.84 | 138.85 | 4.3% | 378.85 | 1,766/3% | n/a | high_iv_rank |
| LEAPS-AAPL-2028-03-17-240C | 240 | 2028-03-17 | 507 | 0.85 | 128.18 | 4.4% | 368.18 | 477/3% | 370C 2026-12-18 Δ0.28 mid 4.80 (net Δ 0.57, safety +1.82) | shorter_than_preferred_dte, high_iv_rank |
| LEAPS-AAPL-2027-12-17-245C | 245 | 2027-12-17 | 416 | 0.85 | 119.90 | 4.5% | 364.90 | 581/3% | 365C 2026-11-20 Δ0.25 mid 3.25 (net Δ 0.60, safety +0.10) | shorter_than_preferred_dte, high_iv_rank |
| LEAPS-AAPL-2029-01-19-250C | 250 | 2029-01-19 | 815 | 0.82 | 132.65 | 4.6% | 382.65 | 526/2% | n/a | high_iv_rank |
| LEAPS-AAPL-2028-12-15-250C | 250 | 2028-12-15 | 780 | 0.82 | 131.25 | 4.6% | 381.25 | 2,501/3% | n/a | high_iv_rank |
| LEAPS-AAPL-2028-01-21-250C | 250 | 2028-01-21 | 451 | 0.84 | 116.88 | 4.6% | 366.88 | 1,842/2% | 367.5C 2026-11-20 Δ0.22 mid 2.67 (net Δ 0.62, safety +0.62) | shorter_than_preferred_dte, high_iv_rank |
| LEAPS-AAPL-2028-03-17-250C | 250 | 2028-03-17 | 507 | 0.83 | 119.78 | 4.7% | 369.77 | 612/3% | 370C 2026-12-18 Δ0.28 mid 4.80 (net Δ 0.56, safety +0.23) | shorter_than_preferred_dte, high_iv_rank |
| LEAPS-AAPL-2027-12-17-250C | 250 | 2027-12-17 | 416 | 0.84 | 115.75 | 4.7% | 365.75 | 3,382/3% | 367.5C 2026-11-20 Δ0.22 mid 2.67 (net Δ 0.62, safety +1.75) | shorter_than_preferred_dte, high_iv_rank |

## Sized portfolio
| Candidate | Strategy | Contracts | Strike | Expiry | Capital | Margin | Loss @ -30% | $ delta | Premium | Score | PMCC short call |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CSP-NKE-2026-11-20-35P | csp | 3 | 35 | 2026-11-20 | $1,655 | $1,655 | $2,443 | 2,632 | 169 | 0.58 | n/a |
| LEAPS-NKE-2028-12-15-20C | leaps | 1 | 20 | 2028-12-15 | $1,808 | n/a | $1,808 | 1,957 | -1,808 | 0.53 | PMCCSC-NKE-2026-11-20-40C |

| Metric | Value |
|---|---|
| Short-put notional | $10,500 |
| Capital used | $3,464 (3% of buying power) |
| Reg T margin used | $1,655 |
| LEAPS net debit | $1,808 |
| Loss at -30% (all positions) | $4,251 |
| Net dollar delta | 4,589 |
| Net premium (income − debits) | -1,639 |
| Cash reserve | $96,536 |

<details><summary>Skipped candidates (135)</summary>

- CSP-SPY-2026-11-30-735P: 0 contracts fit (max loss per position)
- CSP-SPY-2026-11-30-750P: 0 contracts fit (max loss per position)
- CSP-SPY-2026-11-30-740P: 0 contracts fit (max loss per position)
- CSP-SPY-2026-11-30-745P: 0 contracts fit (max loss per position)
- CSP-SPY-2026-11-30-755P: 0 contracts fit (max loss per position)
- CSP-SPY-2026-11-27-735P: 0 contracts fit (max loss per position)
- CSP-SPY-2026-11-27-750P: 0 contracts fit (max loss per position)
- CSP-SPY-2026-11-27-740P: 0 contracts fit (max loss per position)
- …

</details>

## Risk
**All constraints pass.**

| Constraint | Value | Limit | Status |
|---|---|---|---|
| short_put_notional_x | 0.105 | 1.000 | PASS |
| margin_usage | 0.017 | 0.400 | PASS |
| max_loss_per_position | 0.024 | 0.030 | PASS |
| max_exposure_per_ticker | 0.043 | 0.080 | PASS |
| max_per_sector | 0.043 | 0.300 | PASS |
| dollar_delta_x | 0.046 | 1.000 | PASS |

**Stress test (instant move, repriced with BSM):**

| Market move | IV shock | P&L | % of account |
|---|---|---|---|
| -10% | +50% | -840 | -0.8% |
| -20% | +50% | -1,865 | -1.9% |
| -30% | +50% | -3,140 | -3.1% |

- ⚠️ CSP-NKE-2026-11-20-35P: IV rank is an HV proxy (fewer than 30 IV snapshots stored).
- ⚠️ LEAPS-NKE-2028-12-15-20C: IV rank is an HV proxy (fewer than 30 IV snapshots stored).
- ⚠️ Margin account: Reg T requirement is $1,655 but the loss at a -30% move is $4,251. Brokers can raise requirements at any time, especially in volatile markets.

## Explanation
**Allocation.** With 100000 of buying power in a margin account and a balanced profile, the plan sets aside 45000 for cash-secured put collateral, 25000 for LEAPS/PMCC and keeps 30000 in reserve. The VIX reading of 17.51 sits at the 57 percentile of its past year, so the regime is normal and the tilt applied was "none".

**Quality screen.** 7 underlying(s) passed the good-to-own gate (curated list plus limits on realised and implied volatility, price, liquidity and distance below the 90-day high): SPY (quality 86), AAPL (quality 82), COST (quality 77), MSFT (quality 72), QQQ (quality 70), SBUX (quality 66), NKE (quality 46). Only these were screened for options.

**Trend board.** The consumer-trend scan surfaced CAVA (score 90, CAVA), On Cloud (score 89, ONON), HOKA (score 89, DECK), e.l.f. (score 86, ELF), Crocs (score 86, CROX). Scores combine mention velocity, purchase intent, cross-source confirmation and the gap between social and news attention; stock-forum hype is penalised rather than rewarded.

**Cash-secured put (CSP): selling a put while holding the cash to buy the shares.** A **cash-secured put** is a short put position in which the writer sets aside enough cash to buy the shares at the strike price if the put is assigned. The writer sells the put, collects the premium up front, and accepts the obligation to buy 100 shares per contract at the strike any time before expiration. [S1]

**Assignment: what happens when a short option is exercised against you.** **Assignment** is the process by which an option writer is selected to fulfil the obligation of a contract that a holder has exercised. When a put holder exercises, some put writer is obliged to take the shares at the strike; when a call holder exercises, some call writer must deliver them. [S2]

**Poor man's covered call (PMCC): a short near-term call written against a LEAPS call.** A **poor man's covered call** is a two-leg position: a long, deep in-the-money LEAPS call (expiring a year or more out) and a short, near-term, out-of-the-money call on the same stock. Formally it is a **long call diagonal spread**: different strikes and different expirations. [S3]

**Sized positions.** CSP-NKE-2026-11-20-35P: 3 contract(s) of the csp with strike 35.0 expiring 2026-11-20, using 1655 of capital with a realistic loss of 2443 if the underlying falls 30%. Breakeven at expiry 34.44, maximum loss 10330. LEAPS-NKE-2028-12-15-20C: 1 contract(s) of the leaps with strike 20.0 expiring 2028-12-15, using 1808 of capital with a realistic loss of 1808 if the underlying falls 30%. Breakeven at expiry 38.09, maximum loss 1808. It is paired with short call PMCCSC-NKE-2026-11-20-40C.

**Risk.** 6 of 6 constraint checks pass. Stress test with an instant move and an IV shock: a -10% move gives -840; a -20% move gives -1865; a -30% move gives -3140. The combined loss at a 30% drop across all positions is 4251.

**Warnings and limitations.** CSP-NKE-2026-11-20-35P: IV rank is an HV proxy (fewer than 30 IV snapshots stored). LEAPS-NKE-2028-12-15-20C: IV rank is an HV proxy (fewer than 30 IV snapshots stored). Margin account: Reg T requirement is $1,655 but the loss at a -30% move is $4,251. Brokers can raise requirements at any time, especially in volatile markets.

Market data is delayed and Greeks are model-derived; these are screened candidates that meet the configured criteria, not recommendations.

Educational screening tool. Not investment, tax or legal advice. Options involve significant risk, including loss exceeding the premium received on margin. Data may be delayed or inaccurate.

## Sources
- **[S1]** Cash-secured put (CSP): selling a put while holding the cash to buy the shares — concepts (https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document)  
  “A **cash-secured put** is a short put position in which the writer sets aside enough cash to buy the shares at the strike price if the put is assigned.”
- **[S2]** Assignment: what happens when a short option is exercised against you — concepts (https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document)  
  “**Assignment** is the process by which an option writer is selected to fulfil the obligation of a contract that a holder has exercised.”
- **[S3]** Poor man's covered call (PMCC): a short near-term call written against a LEAPS call — concepts (https://www.cboe.com/education/)  
  “A **poor man's covered call** is a two-leg position: a long, deep in-the-money LEAPS call (expiring a year or more out) and a short, near-term, out-of-the-money call on the same stock.”

## Compliance
PASS · audit `<audit_id>` · report · attempt 1

- ✓ `check_numbers`: 50 numbers checked, all grounded
- ✓ `check_citations`: 3 tag(s) resolve to retrieved sources
- ✓ `check_education_only`: education paragraphs carry no run data; short options show their loss
- ✓ `check_suitability`: suits the profile
- ✓ `check_language`: no directive, certainty, superlative or urgency language
- ✓ `check_disclaimer`: disclaimer present once
- ✓ `check_sources_fresh`: cited rules and filings are current
- ✓ `check_no_pii`: no handles or emails

## Verification
PASS: 50 numbers checked, 0 ungrounded, banned phrases: none, disclaimer present, citations 3 checked / 0 unknown, attempts 1.

## Run metadata
- Models: {"extraction": "deepseek/deepseek-v4.1-flash", "explanation": "deepseek/deepseek-v4.1-flash", "provider": "fixture"}
- Prompt versions: {"answer_concept": "1.0.0", "explain_report": "2.0.0", "extract_entities": "1.0.0", "judge_explanation": "1.0.0", "parse_profile": "1.0.0"}
- Config hash: `<config_hash>`
- Data sources: {"AAPL": "ok", "COST": "ok", "MSFT": "ok", "NKE": "ok", "QQQ": "ok", "SBUX": "ok", "SPY": "ok", "google_trends": "ok", "market_data": "fixture", "news": "ok", "reddit": "ok", "sec": "ok", "social": "ran (7095 posts, 28 entities)", "wikipedia": "ok", "x": "ok"}
- Tokens: 0 in / 0 out · cost $0.0000

## Notes and degraded sources
- universe: no offline fixture for PEP, GOOGL, AMZN, CSCO, TXN, ACN, WMT, PG, KO, MCD, HD, LOW, TJX, JNJ, ABBV, MRK, ABT, JPM, V, MA, HON, UNP, LMT, XOM, CVX; skipped
- universe: trending ticker ANF is not on the good-to-own list; skipped
- universe: trending ticker BIRK is not on the good-to-own list; skipped
- universe: trending ticker BROS is not on the good-to-own list; skipped
- universe: trending ticker CAVA is not on the good-to-own list; skipped
- universe: trending ticker CELH is not on the good-to-own list; skipped
- universe: trending ticker CMG is not on the good-to-own list; skipped
- universe: trending ticker CROX is not on the good-to-own list; skipped
- universe: trending ticker DECK is not on the good-to-own list; skipped
- universe: trending ticker ELF is not on the good-to-own list; skipped
- universe: trending ticker GME is not on the good-to-own list; skipped
- universe: trending ticker LULU is not on the good-to-own list; skipped
- universe: trending ticker ONON is not on the good-to-own list; skipped
- universe: trending ticker SG is not on the good-to-own list; skipped
- universe: trending ticker TSLA is not on the good-to-own list; skipped

> Educational screening tool. Not investment, tax or legal advice. Options involve significant risk, including loss exceeding the premium received on margin. Data may be delayed or inaccurate.
