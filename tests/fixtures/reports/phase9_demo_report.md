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

## News desk
- **AAPL** (6 headline(s)): “Apple reports record services revenue as iPhone sales hold steady” — Reuters, 2026-10-26, earnings, high relevance, sentiment +0.31
- **COST** (6 headline(s)): “Costco quarterly results beat on membership fee growth” — Reuters, 2026-10-26, earnings, high relevance, sentiment +0.27
- **MSFT** (6 headline(s)): “Microsoft cloud revenue tops estimates as Azure growth accelerates” — Reuters, 2026-10-26, earnings, high relevance, sentiment +0.35
- **NKE** (6 headline(s)): “Nike earnings miss estimates as China sales fall” — Reuters, 2026-10-26, earnings, high relevance, sentiment -0.33
- **QQQ** (6 headline(s)): “Nasdaq-100 rallies as megacap earnings impress” — Reuters, 2026-10-26, earnings, high relevance, sentiment +0.25
- **SBUX** (6 headline(s)): “Starbucks same-store sales fall for fourth straight quarter” — Reuters, 2026-10-26, earnings, high relevance, sentiment -0.29
- **SPY** (5 headline(s)): “S&P 500 closes at record as earnings season beats expectations” — Reuters, 2026-10-26, earnings, high relevance, sentiment +0.21

| Candidate | Flag | Event date | Detail |
|---|---|---|---|
| PMCCSC-AAPL-2026-12-18-370C | earnings_within_dte | 2026-11-02 | earnings on 2026-11-02 fall before the 2026-12-18 expiry |
| PMCCSC-AAPL-2026-11-20-365C | earnings_within_dte | 2026-11-02 | earnings on 2026-11-02 fall before the 2026-11-20 expiry |
| PMCCSC-AAPL-2026-11-20-367.5C | earnings_within_dte | 2026-11-02 | earnings on 2026-11-02 fall before the 2026-11-20 expiry |
| PMCCSC-MSFT-2026-11-27-575C | earnings_within_dte | 2026-10-28 | earnings on 2026-10-28 fall before the 2026-11-27 expiry |
| PMCCSC-MSFT-2026-12-18-580C | earnings_within_dte | 2026-10-28 | earnings on 2026-10-28 fall before the 2026-12-18 expiry |
| PMCCSC-MSFT-2026-12-18-590C | earnings_within_dte | 2026-10-28 | earnings on 2026-10-28 fall before the 2026-12-18 expiry |

_Headlines never change the ranking; they flag what to read before trading._

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
| CSP-SPY-2026-11-30-735P | 735 | 2026-11-30 | 34 | -0.17 | 4.10 | $73,090 | $12,337 | 6.0% | 82% | 7,250/1% | 85%* | no |  |
| CSP-SPY-2026-11-30-750P | 750 | 2026-11-30 | 34 | -0.26 | 6.21 | $74,379 | $14,048 | 9.0% | 73% | 9,144/1% | 85%* | no |  |
| CSP-QQQ-2026-11-30-700P | 700 | 2026-11-30 | 34 | -0.30 | 10.43 | $68,956 | $13,344 | 16.2% | 68% | 4,918/1% | 62%* | no |  |
| CSP-QQQ-2026-11-30-695P | 695 | 2026-11-30 | 34 | -0.27 | 9.27 | $68,573 | $12,727 | 14.5% | 71% | 5,930/2% | 62%* | no |  |
| CSP-NKE-2026-11-20-35P | 35 | 2026-11-20 | 24 | -0.23 | 0.56 | $3,444 | $552 | 25.0% | 73% | 20,879/9% | 94%* | no | dte_outside_preferred |

\* IV rank from HV proxy (fewer than 30 stored IV snapshots).

## LEAPS / PMCC candidates
| ID | Strike | Expiry | DTE | Delta | Mid | Extrinsic/yr | Breakeven | OI / spread | PMCC short call | Flags |
|---|---|---|---|---|---|---|---|---|---|---|
| LEAPS-SPY-2028-12-15-555C | 555 | 2028-12-15 | 780 | 0.83 | 265.65 | 3.1% | 820.65 | 143/2% | n/a | high_iv_rank |
| LEAPS-SPY-2028-01-21-550C | 550 | 2028-01-21 | 451 | 0.85 | 254.28 | 3.6% | 804.28 | 758/2% | 805C 2026-12-18 Δ0.22 mid 4.11 (net Δ 0.63, safety +0.72) | shorter_than_preferred_dte, high_iv_rank |
| LEAPS-QQQ-2029-01-19-500C | 500 | 2029-01-19 | 815 | 0.84 | 286.00 | 4.0% | 786.00 | 458/2% | n/a | high_iv_rank |
| LEAPS-QQQ-2028-12-15-500C | 500 | 2028-12-15 | 780 | 0.84 | 284.00 | 4.1% | 784.00 | 224/2% | n/a | high_iv_rank |
| LEAPS-AAPL-2028-12-15-230C | 230 | 2028-12-15 | 780 | 0.85 | 146.30 | 3.9% | 376.30 | 924/3% | n/a | high_iv_rank |
| LEAPS-AAPL-2028-12-15-240C | 240 | 2028-12-15 | 780 | 0.84 | 138.85 | 4.3% | 378.85 | 1,766/3% | n/a | high_iv_rank |
| LEAPS-MSFT-2028-12-15-340C | 340 | 2028-12-15 | 780 | 0.85 | 234.50 | 3.8% | 574.50 | 345/2% | 575C 2026-11-27 Δ0.21 mid 5.35 (net Δ 0.63, safety +0.50) | high_iv_rank |
| LEAPS-MSFT-2028-12-15-350C | 350 | 2028-12-15 | 780 | 0.84 | 227.00 | 4.0% | 577.00 | 1,853/2% | 580C 2026-12-18 Δ0.25 mid 7.92 (net Δ 0.59, safety +3.00) | high_iv_rank |
| LEAPS-NKE-2028-12-15-20C | 20 | 2028-12-15 | 780 | 0.82 | 18.80 | 1.5% | 38.80 | 575/5% | 40C 2026-11-20 Δ0.30 mid 0.72 (net Δ 0.52, safety +1.20) | high_iv_rank |
| LEAPS-COST-2028-12-15-800C | 800 | 2028-12-15 | 780 | 0.78 | 297.00 | 4.9% | 1097.00 | 172/3% | n/a | high_iv_rank |

## Sized portfolio
| Candidate | Strategy | Contracts | Strike | Expiry | Capital | Margin | Loss @ -30% | $ delta | Premium | Score | PMCC short call |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CSP-NKE-2026-11-20-35P | csp | 3 | 35 | 2026-11-20 | $1,655 | $1,655 | $2,443 | 2,632 | 169 | 0.58 | n/a |
| LEAPS-NKE-2028-12-15-20C | leaps | 1 | 20 | 2028-12-15 | $1,808 | n/a | $1,808 | 1,957 | -1,808 | 0.52 | PMCCSC-NKE-2026-11-20-40C |

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

<details><summary>Skipped candidates (13)</summary>

- CSP-SPY-2026-11-30-735P: 0 contracts fit (max loss per position)
- CSP-SPY-2026-11-30-750P: 0 contracts fit (max loss per position)
- LEAPS-SPY-2028-12-15-555C: 0 contracts fit (allocation budget)
- CSP-QQQ-2026-11-30-700P: 0 contracts fit (max loss per position)
- LEAPS-SPY-2028-01-21-550C: 0 contracts fit (allocation budget)
- CSP-QQQ-2026-11-30-695P: 0 contracts fit (max loss per position)
- LEAPS-QQQ-2029-01-19-500C: 0 contracts fit (allocation budget)
- LEAPS-QQQ-2028-12-15-500C: 0 contracts fit (allocation budget)
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

**LEAPS: long-dated call options as a leveraged stand-in for owning shares.** **LEAPS** (Long-term Equity AnticiPation Securities) is the exchanges' name for listed options with more than a year until expiration. They trade and settle exactly like shorter options; only the time horizon is different. This app screens **deep in-the-money LEAPS calls** as a way to hold long exposure to a good-to-own stock for a year or more while committing less capital than buying the shares outright. [S3]

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
- **[S3]** LEAPS: long-dated call options as a leveraged stand-in for owning shares — concepts (https://www.cboe.com/education/)  
  “**LEAPS** (Long-term Equity AnticiPation Securities) is the exchanges' name for listed options with more than a year until expiration. They trade and settle exactly like shorter options; only the time horizon is different.”

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
- ✓ `goal_narrative`: no goal reply to check
- ✓ `news_grounding`: no headlines to check
- ✓ `tax_reply`: no tax reply to check

## Verification
PASS: 50 numbers checked, 0 ungrounded, banned phrases: none, disclaimer present, citations 3 checked / 0 unknown, attempts 1.

## Run metadata
- Models: {"extraction": "deepseek/deepseek-v4.1-flash", "explanation": "deepseek/deepseek-v4.1-flash", "provider": "fixture"}
- Prompt versions: {"answer_concept": "1.2.0", "answer_tax": "1.0.0", "classify_bottleneck": "1.0.0", "classify_news": "1.1.0", "explain_goal": "1.0.0", "explain_report": "2.1.0", "extract_entities": "1.1.0", "judge_explanation": "1.0.0", "parse_goal": "1.0.0", "parse_holdings": "1.0.0", "parse_profile": "1.2.0", "route_message": "1.3.0"}
- Config hash: `<config_hash>`
- Data sources: {"AAPL": "ok", "COST": "ok", "MSFT": "ok", "NKE": "ok", "QQQ": "ok", "SBUX": "ok", "SPY": "ok", "google_trends": "ok", "market_data": "fixture", "news": "ok", "news_alphavantage_news": "ok", "news_desk": "41 headlines for 7 ticker(s)", "news_rss": "ok", "reddit": "ok", "sec": "ok", "social": "ran (7095 posts, 28 entities)", "wikipedia": "ok", "x": "ok"}
- Tokens: 0 in / 0 out · cost $0.0000

## Notes and degraded sources
- ranker: kept the best 2 contracts per ticker and strategy (122 near-duplicate strikes/expiries not listed)
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
