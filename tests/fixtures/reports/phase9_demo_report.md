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

## Bottleneck board (secondary)
_Secondary signal: re-orders, never adds. Company score = layer score × exposure; a ticker without a row takes the neutral 50 in the ranking. Scores and flags describe the state of a supply constraint; they are not forecasts._

| Layer | Name | Score | Tightness z | Price trend | Deceleration | Supply z | Cross-source | Thesis |
|---|---|---|---|---|---|---|---|---|
| ai_datacenter/power | Power generation and grid equipment | 79 | +4.0 | +0.89 | +0.00 | +0.0 | 0.50 | holding |
| electrification/grid | Grid equipment and transformers | 76 | +3.0 | +0.97 | +0.00 | -0.4 | 0.67 | holding |
| ai_datacenter/memory | DRAM and high-bandwidth memory (HBM) | 56 | +4.0 | +0.43 | +0.00 | +1.2 | 0.17 | holding |
| electrification/industrial | Industrial electrification and automation | 38 | +3.2 | +0.01 | +0.41 | -0.7 | 0.17 | holding |
| ai_datacenter/materials | Copper and specialty gases | 14 | -3.8 | +0.40 | +0.17 | +1.0 | 0.00 | holding |
| ai_datacenter/networking | Networking, optics and fiber | 13 | -1.9 | +0.23 | +0.00 | +2.8 | 0.17 | weakening |
| ai_datacenter/cooling | Liquid cooling and thermal management | 12 | -1.2 | +0.02 | +0.68 | +0.8 | 0.17 | holding |
| electrification/battery | Battery materials | 6 | -3.2 | -0.74 | +0.00 | +2.4 | 0.00 | weakening |

| Ticker | Layer | Company score | Exposure | Priced in | Catalyst days | Curated | Flags |
|---|---|---|---|---|---|---|---|
| GEV | electrification/grid | 76 | 1.00 | 0.00 | n/a | no (not on the good-to-own list) | bottleneck_support |
| ETN | electrification/grid | 76 | 1.00 | 0.00 | n/a | no (not on the good-to-own list) | bottleneck_support |
| HUBB | electrification/grid | 76 | 1.00 | 0.00 | n/a | no (not on the good-to-own list) | bottleneck_support |
| VST | ai_datacenter/power | 74 | 0.94 | 0.10 | n/a | no (not on the good-to-own list) | bottleneck_support |
| MU | ai_datacenter/memory | 55 | 0.98 | 0.04 | n/a | no (not on the good-to-own list) |  |
| HON | ai_datacenter/power | 37 | 0.47 | 0.10 | n/a | yes |  |
| PWR | electrification/grid | 33 | 0.44 | 0.00 | n/a | no (not on the good-to-own list) |  |
| AMAT | ai_datacenter/memory | 20 | 0.37 | 0.04 | n/a | no (not on the good-to-own list) |  |
| LRCX | ai_datacenter/memory | 20 | 0.37 | 0.04 | n/a | no (not on the good-to-own list) |  |
| EMR | electrification/industrial | 18 | 0.46 | 0.78 | n/a | no (not on the good-to-own list) |  |
| ROK | electrification/industrial | 15 | 0.40 | 0.78 | n/a | no (not on the good-to-own list) |  |
| VRT | ai_datacenter/cooling | 12 | 1.00 | 0.00 | n/a | no (not on the good-to-own list) | bottleneck_easing |
| XOM | ai_datacenter/power | 11 | 0.14 | 0.10 | n/a | yes |  |
| CVX | ai_datacenter/power | 11 | 0.14 | 0.10 | n/a | yes |  |
| FCX | ai_datacenter/materials | 7 | 0.51 | 0.70 | n/a | no (not on the good-to-own list) |  |

**Thesis monitor and evidence:**
- **ai_datacenter/cooling** (thesis holding): Rack power density is moving data halls from air to liquid cooling faster than thermal-equipment capacity is being added; specialists see backlog and pricing power.
  - `supply_response_z > 1.5` for 1 snapshot(s): holding (observed 0.84)
  - `tightness_z < -1` for 3 snapshot(s): holding (observed -1.25)
  - filing MSFT, 2026-09-20: “Delivery schedules for coolant distribution units slipped by 30 weeks. rack density is a limiting factor on the timing of our capital expenditures.” ([edgar](https://www.sec.gov/Archives/edgar/data/789019/000116510026746731/msft-10k.htm)) · tightening · lead_time
  - filing VRT, 2026-10-24: “Competitors announced additional chillers capacity in Ohio, and we see the liquid cooling constraint resolving over the next several quarters.” ([edgar](https://www.sec.gov/Archives/edgar/data/1674101/000183663126375172/vrt-10q.htm)) · easing · capacity
  - headline, 2026-09-07: “Explainer: why direct-to-chip became the story of the year in building solutions (Data Hall Report)” ([news](https://news.example.com/explainer-why-directtochip-became-the-story-of-the-year-in-b-000040)) · neutral · coverage
- **ai_datacenter/materials** (thesis holding): Data centers, grids and electrification all draw on copper and fab gases whose new supply takes the better part of a decade; miners and gas majors see sustained pricing.
  - `price_deceleration > 0.5` for 2 snapshot(s): holding (observed 0.17)
  - `supply_response_z > 1.5` for 1 snapshot(s): holding (observed 1.00)
  - filing APD, 2026-10-09: “We realized higher average selling prices in metals as cathode premium persisted across the industry; backlog grew 25% year over year and now extends into 2027.” ([edgar](https://www.sec.gov/Archives/edgar/data/2969/000147814926447800/apd-8k.htm)) · tightening · price
  - headline, 2026-10-27: “Copper price easing: copper cathode oversupply expected by 2027, analysts say (Mining Journal Digest)” ([news](https://news.example.com/copper-price-easing-copper-cathode-oversupply-expected-by-20-000064)) · easing · capacity
  - headline, 2026-10-25: “Explainer: why copper price became the story of the year in electronics gases (Power Markets News)” ([news](https://news.example.com/explainer-why-copper-price-became-the-story-of-the-year-in-e-000065)) · neutral · coverage
- **ai_datacenter/memory** (thesis holding): Accelerator demand has sold out HBM and tightened commodity DRAM; the three memory makers and their tool suppliers gain volume and price together.
  - `price_deceleration > 0.5` for 2 snapshot(s): holding (observed 0.00)
  - `supply_response_z > 1.5` for 1 snapshot(s): holding (observed 1.21)
  - filing MU, 2026-10-27: “We realized higher average selling prices in memory as memory supply tight persisted across the industry; backlog grew 30% year over year and now extends into 2028.” ([edgar](https://www.sec.gov/Archives/edgar/data/723125/000162454326230666/mu-8k.htm)) · tightening · price
  - filing LRCX, 2026-10-25: “Competitors announced additional HBM3E stacks capacity in Idaho, and we see the memory supply tight constraint resolving over the next several quarters.” ([edgar](https://www.sec.gov/Archives/edgar/data/707549/000136989726231403/lrcx-10k.htm)) · easing · capacity
  - headline, 2026-10-21: “LRCX signs multi-year deposition tools supply deal amid HBM sold out (Power Markets News)” ([news](https://news.example.com/lrcx-signs-multiyear-deposition-tools-supply-deal-amid-hbm-s-000021)) · tightening · deal
- **ai_datacenter/networking** (**thesis weakening**): AI clusters need far more optical and switching capacity per server than classic data centers; fiber and switch makers see demand outrun lead times.
  - `price_deceleration > 0.5` for 2 snapshot(s): holding (observed 0.00)
  - `supply_response_z > 1.5` for 1 snapshot(s): tripped since 2026-10-27 (observed 2.81)
  - filing GLW, 2026-10-24: “We realized higher average selling prices in optical communications as fiber optic cable persisted across the industry; backlog grew 12% year over year and now extends into 2027.” ([edgar](https://www.sec.gov/Archives/edgar/data/24741/000126341826320360/glw-8k.htm)) · tightening · price
  - headline, 2026-10-25: “GLW to expand 800G transceivers capacity 40% as fiber shortage persists (Power Markets News)” ([news](https://news.example.com/glw-to-expand-800g-transceivers-capacity-40-as-fiber-shortag-000044)) · easing · capacity
  - headline, 2026-10-25: “Explainer: why networking backlog became the story of the year in networking (Semiconductor Daily)” ([news](https://news.example.com/explainer-why-networking-backlog-became-the-story-of-the-yea-000057)) · neutral · coverage
- **ai_datacenter/power** (thesis holding): Data-center power demand is outrunning grid interconnection and gas-turbine supply; equipment makers and fuel suppliers see backlog growth and pricing power.
  - `price_deceleration > 0.5` for 2 snapshot(s): holding (observed 0.00)
  - `supply_response_z > 1.5` for 1 snapshot(s): holding (observed 0.00)
  - `tightness_z < -1` for 3 snapshot(s): holding (observed 4.00)
  - filing XOM, 2026-10-26: “Lead times for uninterruptible power systems extended to 52 weeks during the quarter as grid interconnection remained the binding constraint on our customers' build schedules.” ([edgar](https://www.sec.gov/Archives/edgar/data/2115436/000117959526324190/xom-10k.htm)) · tightening · lead_time
  - headline, 2026-08-19: “New entrant breaks ground on uninterruptible power systems factory, citing turbine lead time (Industrial Monitor)” ([news](https://news.example.com/new-entrant-breaks-ground-on-uninterruptible-power-systems-f-000001)) · easing · capacity
  - headline, 2026-10-22: “Gas turbines lead times stretch to 104 weeks as interconnection queue bites, survey finds (Semiconductor Daily)” ([news](https://news.example.com/gas-turbines-lead-times-stretch-to-104-weeks-as-interconnect-000005)) · tightening · lead_time
- **electrification/battery** (**thesis weakening**): Storage and vehicle batteries need lithium, nickel and graphite whose mines and refineries take years to permit and build; a renewed tightening would lift the miners first.
  - `price_trend < 0` for 2 snapshot(s): holding (observed -0.74)
  - `supply_response_z > 1.5` for 1 snapshot(s): tripped since 2026-10-27 (observed 2.40)
  - filing TSLA, 2026-07-17: “We paid higher prices for lithium hydroxide this year as lithium carbonate spread to every supplier we use; the increase was absorbed in our capital plan.” ([edgar](https://www.sec.gov/Archives/edgar/data/1318605/000152326626042217/tsla-10k.htm)) · tightening · price
  - headline, 2026-10-26: “New entrant breaks ground on lithium hydroxide factory, citing graphite anode supply (Grid Weekly)” ([news](https://news.example.com/new-entrant-breaks-ground-on-lithium-hydroxide-factory-citin-000083)) · easing · capacity
  - headline, 2026-10-23: “ALB to expand lithium hydroxide capacity 12% as lithium price persists (Industrial Monitor)” ([news](https://news.example.com/alb-to-expand-lithium-hydroxide-capacity-12-as-lithium-price-000081)) · easing · capacity
- **electrification/grid** (thesis holding): Load growth, renewables interconnection and grid hardening have stretched transformer and switchgear lead times to years; the few domestic makers hold pricing power.
  - `price_deceleration > 0.5` for 2 snapshot(s): holding (observed 0.00)
  - `supply_response_z > 1.5` for 1 snapshot(s): holding (observed -0.35)
  - `tightness_z < -1` for 3 snapshot(s): holding (observed 3.04)
  - filing GEV, 2026-10-25: “Lead times for substation equipment extended to 104 weeks during the quarter as distribution transformer remained the binding constraint on our customers' build schedules.” ([edgar](https://www.sec.gov/Archives/edgar/data/1996810/000170126026452964/gev-8k.htm)) · tightening · lead_time
  - headline, 2026-09-24: “HUBB announces new substation equipment plant in Pennsylvania to address substation backlog (Data Hall Report)” ([news](https://news.example.com/hubb-announces-new-substation-equipment-plant-in-pennsylvani-000069)) · easing · capacity
  - headline, 2026-10-13: “What transformer shortage means for HUBB and its peers (Power Markets News)” ([news](https://news.example.com/what-transformer-shortage-means-for-hubb-and-its-peers-000079)) · neutral · coverage
- **electrification/industrial** (thesis holding): Factories, mines and freight are replacing combustion and manual processes with electric drives and automation; controls makers see multi-year backlogs.
  - `supply_response_z > 1.5` for 1 snapshot(s): holding (observed -0.66)
  - `tightness_z < -1` for 3 snapshot(s): holding (observed 3.24)
  - filing TSLA, 2026-10-25: “Our expansion of plant electrification projects was constrained by electric locomotive; we have entered multi-year supply agreements to secure variable-frequency drives through 2028.” ([edgar](https://www.sec.gov/Archives/edgar/data/1318605/000153764426001988/tsla-8k.htm)) · tightening · capacity
  - filing GM, 2026-09-27: “Availability of motor controls improved and electric locomotive was no longer a constraint on our mine conversions during the quarter.” ([edgar](https://www.sec.gov/Archives/edgar/data/1467858/000104206926381928/gm-10q.htm)) · easing · capacity
  - headline, 2026-10-24: “Analysts weigh electric locomotive impact on process solutions margins (Industrial Monitor)” ([news](https://news.example.com/analysts-weigh-electric-locomotive-impact-on-process-solutio-000095)) · neutral · coverage

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

**Bottleneck board.** The supply-constraint scan is a secondary signal that re-orders quality-gated stocks and never adds one. Tightest layers: ai_datacenter/power (score 79, thesis holding), electrification/grid (score 76, thesis holding), ai_datacenter/memory (score 56, thesis holding). Curated suppliers with a company score: HON 37, XOM 11, CVX 11, UNP 3, CSCO 1. Thesis weakening (a falsifier tripped, so scores in the layer are decayed): ai_datacenter/networking, electrification/battery. A layer score describes the state of a shortage, not a forecast.

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

- ✓ `check_numbers`: 58 numbers checked, all grounded
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
PASS: 58 numbers checked, 0 ungrounded, banned phrases: none, disclaimer present, citations 3 checked / 0 unknown, attempts 1.

## Run metadata
- Models: {"extraction": "deepseek/deepseek-v4.1-flash", "explanation": "deepseek/deepseek-v4.1-flash", "provider": "fixture"}
- Prompt versions: {"answer_concept": "1.2.0", "answer_tax": "1.0.0", "classify_bottleneck": "1.0.0", "classify_news": "1.1.0", "explain_goal": "1.0.0", "explain_report": "2.2.0", "extract_entities": "1.1.0", "judge_explanation": "1.0.0", "parse_goal": "1.0.0", "parse_holdings": "1.0.0", "parse_profile": "1.2.0", "route_message": "1.3.0"}
- Config hash: `<config_hash>`
- Data sources: {"AAPL": "ok", "COST": "ok", "MSFT": "ok", "NKE": "ok", "QQQ": "ok", "SBUX": "ok", "SPY": "ok", "bottleneck": "ran (274 snippets, 8 layers, 30 companies)", "bottleneck:csv_series": "ok", "bottleneck:edgar": "ok", "bottleneck:fred": "ok", "bottleneck:google_trends": "ok", "bottleneck:news": "ok", "bottleneck:reddit": "ok", "bottleneck:transcripts": "disabled", "google_trends": "ok", "market_data": "fixture", "news": "ok", "news_alphavantage_news": "ok", "news_desk": "41 headlines for 7 ticker(s)", "news_rss": "ok", "reddit": "ok", "sec": "ok", "social": "ran (7095 posts, 28 entities)", "wikipedia": "ok", "x": "ok"}
- Tokens: 0 in / 0 out · cost $0.0000

## Notes and degraded sources
- ranker: kept the best 2 contracts per ticker and strategy (122 near-duplicate strikes/expiries not listed)
- universe: bottleneck ticker ALB is not on the good-to-own list; skipped
- universe: bottleneck ticker AMAT is not on the good-to-own list; skipped
- universe: bottleneck ticker ANET is not on the good-to-own list; skipped
- universe: bottleneck ticker APD is not on the good-to-own list; skipped
- universe: bottleneck ticker CIEN is not on the good-to-own list; skipped
- universe: bottleneck ticker EMR is not on the good-to-own list; skipped
- universe: bottleneck ticker ETN is not on the good-to-own list; skipped
- universe: bottleneck ticker FCX is not on the good-to-own list; skipped
- universe: bottleneck ticker GEV is not on the good-to-own list; skipped
- universe: bottleneck ticker GLW is not on the good-to-own list; skipped
- universe: bottleneck ticker HUBB is not on the good-to-own list; skipped
- universe: bottleneck ticker LIN is not on the good-to-own list; skipped
- universe: bottleneck ticker LRCX is not on the good-to-own list; skipped
- universe: bottleneck ticker MU is not on the good-to-own list; skipped
- universe: bottleneck ticker PWR is not on the good-to-own list; skipped
- universe: bottleneck ticker ROK is not on the good-to-own list; skipped
- universe: bottleneck ticker SCCO is not on the good-to-own list; skipped
- universe: bottleneck ticker SQM is not on the good-to-own list; skipped
- universe: bottleneck ticker VRT is not on the good-to-own list; skipped
- universe: bottleneck ticker VST is not on the good-to-own list; skipped
- universe: no offline fixture for PEP, HON, XOM, CVX, UNP, CSCO, GOOGL, AMZN, TXN, ACN, WMT, PG, KO, MCD, HD, LOW, TJX, JNJ, ABBV, MRK, ABT, JPM, V, MA, LMT; skipped
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
