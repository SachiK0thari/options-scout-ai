---
id: rules-3-7-quality-gate
title: 'Rule 3.7: Good-to-own universe (quality gate)'
source: PRD.md section 3.7 and config/quality_universe.yaml, config/settings.yaml
url: PRD.md#37-good-to-own-universe-quality-gate
kind: rules
level: intermediate
as_of: '2026-11-10'
---

# Rule 3.7 Good-to-own universe (quality gate)

This document is generated from PRD.md section 3.7 and `config/quality_universe.yaml`, `config/settings.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.7)

The product promise is "stocks you would be happy to own if assigned", so the universe is a **filter, not a discovery engine**. Everything lives in `config/quality_universe.yaml`; the logic is in `core/quality.py` (pure, golden-tested).

1. **Curated list** (~30 names, in priority order): large, profitable, durable companies with long dividend records or dominant franchises, plus SPY and QQQ. Each entry carries `name`, `sector`, `tags` and a one-line `why`. Speculative or meme names (TSLA, NVDA, GME, COIN, PLTR …) are deliberately absent. The user may add tickers; they are flagged *user-added* and must pass the same numeric gate.
2. **Numeric gate**, evaluated per run on the live or fixture snapshot. All limits are config:

| Gate | Default | Why |
|---|---|---|
| Price | ≥ $20 | avoid low-priced, easily manipulated names |
| Average volume | ≥ 1M shares/day | liquidity |
| 30-day realised volatility (HV30) | ≤ 35% | calm price action |
| ATM implied volatility | ≤ 45% | the market is not pricing a shock |
| Distance below the 90-day closing high | ≤ 20% | no falling knives |
| Price history | ≥ 31 closes | enough data to judge the above |
| `require_curated` | false | set true to reject user-added tickers outright |

   A failed gate is **recorded with its reason** (`QualityCheck.reasons`) and shown in the report; the ticker never reaches the screeners. Missing data fails the gate; it does not pass it.
3. **Quality score** (0–1) for survivors: `0.4·stability + 0.3·trend + 0.3·curated`, with `stability = 1 − HV30/max_hv30` and `trend = 1 − drawdown/max_drawdown` (both clipped). Golden value: HV30 17.5%, at the high, curated → **0.80**.
4. **Ranking** (`settings.yaml → ranking.weights`): `final = 0.50·option_quality + 0.35·quality_score + 0.15·social/100`. The social signal is the smallest weight on purpose. The ranker then keeps the best two contracts per ticker and strategy (`ranking.max_per_ticker`), so one dense ETF chain cannot fill the shortlist with near-identical strikes. **Phase 11** (section 4A) adds a fourth term by splitting the Market Intelligence share, not by taking weight from the stock or the option: `final = 0.50·option_quality + 0.35·quality_score + 0.10·social/100 + 0.05·bottleneck/100`. The two signal weights together may never exceed 0.15; the config loader rejects a file that breaks that cap. A ticker with no signal gets the neutral score 50 for each term, so a run with the engines disabled ranks exactly as it does today. **W29:** a signal can only help. Each signal term uses `max(score, 50)`, so a weak or falling score ranks a ticker exactly as no score does. The bottleneck weight is 0 (the board is informational for this universe, section 4A.11) and its former 0.05 went to option quality: `final = 0.55·option_quality + 0.35·quality_score + 0.10·max(social, 50)/100`.
5. **Universe order** when more names qualify than `universe.max_tickers` (12): user tickers, then curated names whose Market Intelligence score (the consumer-trend score, or from Phase 11 the higher of the trend and bottleneck scores) is at least `universe.signal_promotion_min` (60), highest first, then list order. A weaker score leaves a name at its list position (W29). Trending or bottleneck tickers that are not curated are noted and skipped.
6. **Fixture mode** keeps only curated tickers that have fixtures: AAPL, MSFT, COST, SBUX, NKE, SPY, QQQ pass; CMG, DECK, ELF fail the gate (and are only evaluated at all if the user adds them). Tests assert both lists.

## Values in force (config/quality_universe.yaml, config/settings.yaml)

### Numeric gate

| Gate | Value in force |
|---|---|
| Price | ≥ $20 |
| Average volume | ≥ 1,000,000 shares/day |
| 30-day realised volatility (HV30) | ≤ 35% |
| ATM implied volatility | ≤ 45% |
| Distance below the 90-day closing high | ≤ 20% |
| Price history | ≥ 31 closes |
| require_curated | false |
| Universe cap | 12 tickers per run |

Missing data fails a gate; it never passes it. Every failed gate is recorded with its reason and the ticker never reaches the option screeners.

### Score and ranking

Quality score = 0.4·stability + 0.3·trend + 0.3·curated, with stability = 1 − HV30/35% and trend = 1 − drawdown/20%, both clipped to [0, 1].

Final ranking = 0.55·option quality + 0.35·quality score + 0.1·consumer-trend score/100 + 0·bottleneck score/100 (the two signals together are capped at 0.15).

### Curated good-to-own list (32 names, in priority order)

| Ticker | Name | Sector | Why it is on the list |
|---|---|---|---|
| SPY | SPDR S&P 500 ETF | ETF | Owns the whole S&P 500; the most liquid option chain in the market. |
| QQQ | Invesco Nasdaq-100 ETF | ETF | Owns the 100 largest Nasdaq companies; very liquid options. |
| AAPL | Apple | Technology | Huge installed base, large recurring services revenue, consistent buybacks and dividend. |
| MSFT | Microsoft | Technology | Enterprise software and cloud with long-term contracts and 20+ years of dividend growth. |
| GOOGL | Alphabet | Communication Services | Dominant search and advertising franchise with a large net cash position. |
| AMZN | Amazon | Consumer Cyclical | Leading cloud and e-commerce platforms with strong free cash flow. |
| CSCO | Cisco Systems | Technology | Networking incumbent with a long dividend record and steady cash generation. |
| TXN | Texas Instruments | Technology | Analog chip leader with 20+ consecutive years of dividend increases. |
| ACN | Accenture | Technology | Global consulting franchise, asset-light, rising dividend. |
| COST | Costco Wholesale | Consumer Defensive | Membership model with very high renewal rates and decades of dividend growth. |
| WMT | Walmart | Consumer Defensive | Largest retailer; 50 consecutive years of dividend increases. |
| PG | Procter & Gamble | Consumer Defensive | Household staples brands; dividends paid for over a century. |
| KO | Coca-Cola | Consumer Defensive | Global beverage brands; 60+ years of dividend increases. |
| PEP | PepsiCo | Consumer Defensive | Snacks and beverages; 50+ years of dividend increases. |
| MCD | McDonald's | Consumer Cyclical | Franchise and real-estate model; 45+ years of dividend increases. |
| HD | Home Depot | Consumer Cyclical | Largest home-improvement retailer with high returns on capital. |
| LOW | Lowe's | Consumer Cyclical | Home-improvement retailer; 60+ years of dividend increases. |
| TJX | TJX Companies | Consumer Cyclical | Off-price retail leader with resilient traffic across cycles. |
| SBUX | Starbucks | Consumer Cyclical | Global coffee brand with a 14-year streak of dividend increases. |
| NKE | Nike | Consumer Cyclical | Leading athletic brand with 20+ years of dividend increases. |
| JNJ | Johnson & Johnson | Healthcare | Diversified healthcare; one of two AAA-rated US companies, 60+ years of dividend growth. |
| ABBV | AbbVie | Healthcare | Large pharma with a high-yield, growing dividend. |
| MRK | Merck | Healthcare | Large pharma with a long dividend history. |
| ABT | Abbott Laboratories | Healthcare | Diversified medical devices and diagnostics; 50+ years of dividend increases. |
| JPM | JPMorgan Chase | Financial Services | Largest US bank by assets with a fortress balance sheet. |
| V | Visa | Financial Services | Payments network with very high margins and little credit risk. |
| MA | Mastercard | Financial Services | Payments network with very high margins and little credit risk. |
| HON | Honeywell | Industrials | Diversified industrial with a long dividend record. |
| UNP | Union Pacific | Industrials | Railroad duopoly asset with pricing power. |
| LMT | Lockheed Martin | Industrials | Defense prime with a multi-year contracted backlog. |
| XOM | Exxon Mobil | Energy | Integrated energy major; 40+ years of dividend increases. |
| CVX | Chevron | Energy | Integrated energy major; 35+ years of dividend increases. |

The list is a filter, not a recommendation: a user-added ticker is flagged *user-added* and must pass the same gate.
