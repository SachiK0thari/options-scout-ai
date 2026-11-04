# PRD.md: OptionsScout AI

> Build spec and working agreement for Claude Code.
> Read this whole file before writing any code. Work through the **Build Phases** (section 14) in order, and do not start a phase until the previous phase's acceptance criteria pass.
> **Current phase: 11, step 11.1** (section 4A / section 14, the bottleneck-arbitrage signal). **Phase 10 is complete** (steps 10.1–10.8 done 2026-11-04): six specialists + Compliance as subgraphs, the cited knowledge base, the routed chat, the eight-tab UI, the MCP server, `docs/architecture.md`, `docs/compliance.md`, `docs/rag.md`, the 11.3a evals and coverage in CI. Phases 0–10 must not regress. Section 18 maps every rubric line to the feature and test that earns it. Nothing in Phase 11 is built yet, and the three-term ranking in section 3.7 stays in force until it ships.

---

## 0. TL;DR for Claude Code

- **What:** A multi-agent LangGraph application behind a **multi-tab Streamlit app with a chat tab**: the user describes their situation in plain English (or fills the form), picks **cash-secured puts (CSPs)**, **LEAPS calls** or both, optionally pastes a **market-data API key**, and gets option candidates on **good-to-own stocks only** (a curated list of large, profitable, dividend-paying companies and broad ETFs, each re-checked by a deterministic quality gate on the day of the run). Positions are sized to buying power under risk limits; a **consumer-trend** signal (rising product and brand discussion on Reddit, X and other public platforms) only re-orders stocks that already passed the gate, and a second **bottleneck** signal (section 4A, Phase 11: shortages in the supply chain behind a large theme, read from customer and supplier filings, industry price series and trade news) does the same and never adds a stock either. An **Education** agent answers "what is a cash-secured put / why was Nike excluded / what happens at −30%" with answers **retrieved from a cited knowledge base**, and every LLM output passes a **Compliance** agent before a user sees it.
- **Architecture (section 5):** one orchestrator + **six specialist agents** (Market Data, Market Intelligence, Strategy, Portfolio, Risk, Education) + a **Compliance** agent, each a LangGraph subgraph with its own state slice, tools and prompts, composed by a parent graph. The options domain lives *inside* that structure; it does not replace it.
- **Why:** A portfolio project to showcase AI Engineer skills: multi-agent orchestration, tool use, structured outputs, **retrieval-augmented explanation with citations**, evaluation, observability, guardrails, and clean production engineering.
- **Golden rule:** **The LLM never does math.** Every number (Greeks, margin, returns, sizing) is computed by deterministic, unit-tested Python. The LLM extracts, classifies, reasons over computed results, and explains. The Compliance agent rejects any narrative that contains a number not present in the computed results, a claim without a citation to a retrieved source, a suitability violation, or banned language.
- **Not financial advice:** This is an educational **screener**. It never places trades, never connects to a brokerage, and every output carries a disclaimer.
- **Stack:** Python 3.11+, LangGraph (1.2.x), Pydantic v2, FastAPI, Streamlit, SQLite/DuckDB, MarketData.app REST (httpx), PRAW, X API v2 (httpx), Wikimedia Pageviews API, pytrends (optional), pytest.
- **Data budget:** Free sources by default. Every external source must also have a **fixture (mock) mode** so the demo and CI run offline. Sources that need a paid tier (X search) or an unofficial client (Google Trends) are fully implemented but switchable in `config/social_sources.yaml`.

---

## 1. How to Work in This Repo (rules for Claude Code)

1. **Phases in order.** Follow section 14. Tick the checkboxes in this file as items complete.
2. **Tests first for math.** For anything in `core/pricing`, `core/margin`, `core/screeners`, `core/sizing`: write the test with hand-verified golden values *before* the implementation.
3. **Type everything.** Full type hints, `mypy --strict` clean on `core/`. Pydantic v2 models at every boundary (tools, API, agent state).
4. **No network in tests.** Unit tests use fixtures in `tests/fixtures/`. Integration tests that hit the network are marked `@pytest.mark.live` and skipped by default.
5. **Pin dependencies.** LangGraph and LangChain move fast. Pin exact versions in `pyproject.toml`. When unsure of a LangGraph API, check the installed version's docs rather than guessing from memory.
6. **Secrets** live in `.env` (never committed). Provide `.env.example`.
7. **Config over constants.** Every threshold (delta ranges, DTE, liquidity, allocation splits, score weights) lives in `config/*.yaml`, loaded into typed Pydantic settings.
8. **Prompts are files.** All prompts in `prompts/*.md` with a version header. Never inline long prompts in Python.
9. **Commands** (wire these up in a `Makefile`):
   - `make install` – create venv, install deps (`uv` preferred)
   - `make test` – unit tests
   - `make test-live` – live integration tests
   - `make lint` – ruff + mypy
   - `make eval` – run LLM/agent eval suite, write `evals/reports/latest.md`
   - `make api` – run FastAPI on :8000
   - `make ui` – run Streamlit on :8501
   - `make demo` – run the full pipeline in fixture mode and print a report
10. **Commit style:** small commits, conventional messages (`feat:`, `fix:`, `test:`, `docs:`).
11. **Never** add trade execution, brokerage logins, or language like "you should buy". Use "candidate", "screened", "meets criteria".
12. **Honest README.** Never claim returns or accuracy the evals didn't measure.

---

## 2. Product Overview

### 2.1 User story
> "I have $50,000. Show me cash-secured puts (or LEAPS, or both) on stocks I'd be happy to own if assigned, nothing speculative, sized so I stay inside sensible risk limits."

The web page asks for exactly three things: **buying power**, **CSP / LEAPS / both**, and (optionally) a **market-data API key**. Account type defaults to `cash`, risk profile to `conservative`; both are under "More options".

### 2.2 What the system returns
1. **Quality screen:** which good-to-own stocks were considered, their quality score, and which were excluded and why (section 3.7). Nothing that fails the gate reaches the screeners.
2. **Allocation plan:** how buying power is split between cash reserve, CSP collateral and LEAPS/PMCC, and why (risk profile + volatility regime). Buckets for strategies the user did not ask for are held as cash.
3. **Trend board (secondary):** consumer-trend scores with evidence (mention velocity per source, cross-source confirmation, coverage gap, sample posts). It re-orders qualifying stocks; it never adds one.
4. **Bottleneck board (secondary, Phase 11):** for each curated theme, the supply-chain layers, the tightness score per layer with its evidence (customer and supplier filing excerpts, price-series direction and rate of change, supply-response items), the curated companies that sell into each layer with their materiality, the priced-in reading, the next catalyst and the thesis monitor (thesis sentence, falsifiers, which have tripped). It re-orders qualifying stocks; it never adds one.
5. **CSP candidates:** ticker, strike, expiry, delta, premium, collateral, annualized return, margin requirement (if margin), probability OTM, liquidity grade, earnings flag.
6. **LEAPS / PMCC candidates:** LEAPS strike/expiry/delta, extrinsic % per year, breakeven, plus a matched short call for the PMCC that satisfies the safety rule (PMCC only when the user opts in).
7. **Sized portfolio:** number of contracts per candidate, fitted to all risk constraints, with totals (notional, margin usage, net delta exposure).
8. **Risk report:** stress test (−10%, −20%, −30% market moves), constraint checks, warnings.
9. **Plain-English explanation** grounded only in computed numbers, with a disclaimer.

### 2.3 Non-goals
- No order placement, no brokerage APIs, no real-time streaming quotes.
- No guarantees of returns, no backtested "profit" claims beyond the honest signal study in section 11.4.
- No personalized tax or legal guidance.

---

## 3. Domain Logic (the source of truth for the screeners)

### 3.1 Allocation of buying power

| Profile | CSP collateral | LEAPS / PMCC | Cash reserve |
|---|---|---|---|
| conservative | 50% | 15% | 35% |
| balanced | 45% | 25% | 30% |
| aggressive | 45% | 35% | 20% |

**Volatility regime tilt** (using VIX 1-year percentile from `^VIX`):
- VIX percentile ≥ 70 (high IV): shift **10 points from LEAPS to CSP** (sell expensive premium, avoid buying expensive LEAPS).
- VIX percentile ≤ 30 (low IV): shift **10 points from CSP to LEAPS** (LEAPS are cheap, put premium is thin).
- Never reduce the cash reserve via tilt.

### 3.2 Portfolio risk constraints (all configurable)

| Constraint | conservative | balanced | aggressive |
|---|---|---|---|
| Max total short-put notional (strike × 100 × contracts) / account value | 1.0x | 1.0x | 1.5x |
| Max margin usage of buying power | 30% | 40% | 50% |
| Max realistic loss per position (% of account) | 2% | 3% | 5% |
| Max exposure per ticker (risk terms) | 5% | 8% | 10% |
| Max per sector | 25% | 30% | 35% |
| Max total dollar delta / account value | 0.8x | 1.0x | 1.5x |

- "Realistic loss" for a CSP = loss if the stock drops 30% at expiry. For a LEAPS = full premium paid.
- Cash accounts: margin constraints do not apply, and CSP collateral = full cash-secured amount.
- Same ticker in a CSP and a PMCC: combined exposure counts against the per-ticker cap.

### 3.3 CSP screener rules

| Rule | Default |
|---|---|
| DTE | 30–45 days |
| Put delta (absolute) | 0.15–0.30 |
| Open interest | ≥ 500 |
| Bid-ask spread | ≤ 10% of mid |
| Bid | > $0.10 |
| Earnings date | not before expiry (flag, and exclude by default) |
| Underlying price | ≥ $10, avg volume ≥ 1M shares |
| IV rank | prefer ≥ 30 (soft scoring, not hard filter) |

### 3.4 LEAPS screener rules

| Rule | Default |
|---|---|
| DTE | ≥ 365 days, prefer the longest available (≥ 540 preferred) |
| Call delta | 0.70–0.85 |
| Extrinsic value per year | ≤ 5% of stock price per year (score lower is better) |
| Open interest | ≥ 100 |
| Bid-ask spread | ≤ 5% of mid |
| IV rank | prefer ≤ 40 (soft scoring) |
| Management note | flag "roll or close" when DTE < 240 |

### 3.5 PMCC short call rules
- DTE 30–45, call delta 0.20–0.30, expiry before the LEAPS expiry.
- **Safety rule:** short strike ≥ LEAPS strike + net debit paid for the LEAPS. Reject any pairing that fails.
- Net delta of the pair = LEAPS delta − short call delta.

### 3.6 Formulas (implement exactly, test with golden values)

Notation: S spot, K strike, T years to expiry, r risk-free rate, q dividend yield, σ implied vol, N() standard normal CDF.

- `d1 = (ln(S/K) + (r − q + σ²/2)T) / (σ√T)`, `d2 = d1 − σ√T`
- Call delta = `e^(−qT) N(d1)`; Put delta = `e^(−qT) (N(d1) − 1)`
- Gamma, theta, vega: standard Black-Scholes-Merton with continuous dividend yield.
- Probability put expires OTM ≈ `N(d2)`; call expires OTM ≈ `N(−d2)`.
- Mid = `(bid + ask) / 2`; Spread % = `(ask − bid) / mid`.
- **CSP collateral (cash)** = `(K − premium) × 100`
- **CSP annualized return on collateral** = `premium / (K − premium) × 365 / DTE`
- **Reg T naked put margin** (exchange minimum; brokers may require more) = `(premium + max(0.20 × S − OTM, 0.10 × K)) × 100`, where `OTM = max(S − K, 0)`
- **Return on margin** = `premium × 100 / margin_requirement`
- **LEAPS intrinsic** = `max(S − K, 0)`; **extrinsic** = `price − intrinsic`
- **Extrinsic per year %** = `(extrinsic / S) / (DTE / 365)`
- **LEAPS breakeven at expiry** = `K + price`
- **Dollar delta** = `delta × 100 × S × contracts` (short put delta is positive dollar exposure for the seller: use `−put_delta`)
- **IV rank** = `(IV_now − IV_min_52w) / (IV_max_52w − IV_min_52w)`; **IV percentile** = share of days with IV below today.
  - Free data has no IV history, so the app **stores a daily ATM IV snapshot** per watchlist ticker (scheduled job). Until 30+ snapshots exist, fall back to `IV_now / HV30` and mark the field `iv_rank_source="hv_proxy"`.

Golden-value tests: use at least these, verified with an independent calculator and recorded in `tests/fixtures/golden_greeks.json`:
- S=100, K=100, T=1, r=0.05, q=0, σ=0.20 → call delta ≈ 0.6368, put delta ≈ −0.3632
- Margin example: S=100, K=90, premium=1.50 → OTM=10, max(20−10, 9)=10 → requirement = (1.50 + 10) × 100 = **$1,150**
- CSP example: K=90, premium=1.50, DTE=40 → annualized ≈ 1.50/88.50 × 365/40 ≈ **15.47%**
- LEAPS example: S=100, K=70, price=33 → intrinsic 30, extrinsic 3, breakeven 103

### 3.7 Good-to-own universe (quality gate)

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
4. **Ranking** (`settings.yaml → ranking.weights`): `final = 0.50·option_quality + 0.35·quality_score + 0.15·social/100`. The social signal is the smallest weight on purpose. The ranker then keeps the best two contracts per ticker and strategy (`ranking.max_per_ticker`), so one dense ETF chain cannot fill the shortlist with near-identical strikes. **Phase 11** (section 4A) adds a fourth term by splitting the Market Intelligence share, not by taking weight from the stock or the option: `final = 0.50·option_quality + 0.35·quality_score + 0.10·social/100 + 0.05·bottleneck/100`. The two signal weights together may never exceed 0.15; the config loader rejects a file that breaks that cap. A ticker with no signal gets the neutral score 50 for each term, so a run with the engines disabled ranks exactly as it does today.
5. **Universe order** when more names qualify than `universe.max_tickers` (12): user tickers, then curated names with a Market Intelligence signal (the consumer-trend score, or from Phase 11 the higher of the trend and bottleneck scores; highest first), then list order. Trending or bottleneck tickers that are not curated are noted and skipped.
6. **Fixture mode** keeps only curated tickers that have fixtures: AAPL, MSFT, COST, SBUX, NKE, SPY, QQQ pass; CMG, DECK, ELF fail the gate (and are only evaluated at all if the user adds them). Tests assert both lists.

---

## 4. Consumer-Trend Engine

### 4.1 Concept
The consumer-trend signal means noticing **consumer and cultural trends** (a product going viral, a restaurant chain packed, a brand suddenly everywhere) early, then mapping the trend to a public company that is already on the good-to-own list.

**Key design distinction:** the signal comes from **consumer chatter about products and brands**, not stock-tip chatter. Ticker hype on r/wallstreetbets is treated as a *risk/manipulation flag*, not a buy signal.

### 4.2 Pipeline

```
Ingest posts ─► Clean & dedupe ─► Entity extraction (LLM) ─► Entity → ticker resolution
     │                                                              │
     ▼                                                              ▼
Spam/bot filter                                    Validate ticker vs SEC company list
                                                                    │
                                                                    ▼
                         Per-entity time series (daily mentions, sentiment)
                                                                    │
                                                                    ▼
          Signals: velocity, acceleration, sentiment, cross-source confirmation,
                   coverage gap, novelty, stock-hype penalty
                                                                    │
                                                                    ▼
                         Consumer-Trend Score (0–100) + evidence pack
```

### 4.3 Data sources

Two kinds of source feed the engine. **Post sources** return public posts that go through the filters and LLM entity extraction and become per-entity mention series. **Attention sources** return a daily attention series per keyword and only *confirm* trends found in posts. News RSS is the "Wall Street awareness" baseline for the coverage gap.

| Source | Kind | Use | Access notes |
|---|---|---|---|
| Reddit via **PRAW** | post | Consumer subreddits (r/BuyItForLife, r/sneakers, r/skincareaddiction, r/fastfood, r/gadgets, r/Costco, r/gaming, etc.; the list is in `config/subreddits.yaml`) and stock subs (hype penalty) | Free for non-commercial use, OAuth required, ~100 queries/min per client. Respect rate limits, descriptive User-Agent, cache everything. |
| **X** via the v2 search API (`httpx`) | post | Curated consumer queries in `config/social_sources.yaml` (bottles, running shoes, skincare, energy drinks, fast casual, …); `stock_queries` and any post with a cashtag feed only the hype penalty | Bearer token (`X_BEARER_TOKEN`). `search/recent` covers 7 days (Basic tier, paid); `search/all` (Pro tier) fills the whole baseline window. Follower count stands in for karma, account age for account age, so the same spam filters apply. |
| **Wikimedia Pageviews API** | attention | Daily article views for the brand's Wikipedia article | Free, official, no key; send a descriptive User-Agent. |
| **Google Trends** via `pytrends` | attention | Daily 0–100 search-interest index for the brand keyword (`google_trends` field in `brand_map.yaml`, else the entity name) | Unofficial, archived client, frequently rate-limited (HTTP 429). Optional dependency (`pip install -e ".[trends]"`); failures are recorded in the source status, never raised. If Google's official Trends API becomes available, swap `_fetch_live` in `adapters/google_trends.py`. |
| **Google News RSS / Yahoo Finance RSS** | news | "Wall Street awareness" baseline for the coverage gap | Free RSS; parse with `feedparser`. |
| **SEC `company_tickers.json`** | validation | Ticker validation and company names | Free, requires User-Agent with contact email. |

Post sources implement the `PostSource` protocol (`fetch(since) -> list[SocialPost]`), attention sources the `AttentionSource` protocol (`fetch(keyword, start, end) -> list[DailyCount]`); every adapter has `live` and `fixture` modes and reports a `SourceStatus`. **Switching sources is configuration, not code:** `config/social_sources.yaml` enables and weights each source, and `OPTIONS_SCOUT_SOCIAL_SOURCES=reddit,x,news` (or `python -m options_scout.jobs.refresh_trends --sources x`) overrides it per run. The pipeline merges every enabled post source into one stream *before* the filters (so cross-posted campaigns are deduped together), z-scores each source on its own series, and divides cross-source confirmation by the number of enabled sources. `social/sources.py` is the only place that maps a source name to an adapter class; adding a source means writing the adapter, registering it there and adding its block to the YAML.

### 4.4 Entity extraction and resolution
- LLM extracts structured entities per post: `{name, type: product|brand|company|store, sentiment: -1..1, is_purchase_intent: bool, is_stock_talk: bool}` via Pydantic structured output. Batch posts (≈20 per call) to control cost.
- Resolution: `brand → parent company → ticker`.
  1. Curated map `data/brand_map.yaml` (seed with ~200 consumer brands, e.g. product line → parent company).
  2. Fuzzy match against SEC names (`rapidfuzz`).
  3. LLM fallback proposes parent company; **must** validate against the SEC list or be discarded.
  4. Private companies → kept on the trend board as "not investable" (still useful context), never sent to screeners.
- Cache resolutions in SQLite.

### 4.5 Signals (computed in Python)

| Signal | Definition |
|---|---|
| `velocity_z` | z-score of last-7-day mentions vs. weekly mean/std of prior 8 weeks |
| `acceleration` | change in 7-day mentions vs. previous 7 days |
| `sentiment` | mean entity sentiment, weighted by post score; VADER as cheap baseline, LLM for sampled validation |
| `purchase_intent_rate` | share of mentions with purchase intent |
| `cross_source` | count of enabled sources (Reddit, X, Wikipedia, Google Trends, news) whose own velocity z > 1.5; `cross_source_norm` divides by the number enabled. Per-source z-scores are reported as `reddit_z`, `x_z`, `wikipedia_z`, `google_trends_z`, `news_z` |
| `coverage_gap` | `velocity_z(social) − velocity_z(news)`; high = social sees it, Wall Street doesn't yet |
| `novelty` | penalize entities that have been "hot" for > 8 weeks (already priced in) |
| `stock_hype_penalty` | share of mentions coming from stock subreddits, stock queries, posts with cashtags, or flagged `is_stock_talk` |
| `materiality` | rough weight: is this brand a meaningful share of the parent's revenue? (curated field in `brand_map.yaml`: high/medium/low) |

**Score** (weights in `config/social_score.yaml`):
```
score = 100 × sigmoid( w1·velocity_z + w2·acceleration_norm + w3·sentiment
                     + w4·purchase_intent_rate + w5·cross_source_norm
                     + w6·coverage_gap + w7·materiality
                     − w8·novelty_penalty − w9·stock_hype_penalty )
```

### 4.6 Anti-manipulation filters
- Drop posts from accounts younger than 30 days or with very low karma / follower count (when available). The thresholds are shared by every post source.
- Near-duplicate detection (MinHash or simple shingling) to drop copy-paste campaigns.
- Cap any single author's contribution to an entity at 5%.
- Flag (don't hide) entities whose mentions are mostly stock talk.

### 4.7 Evidence pack
For each top entity, store 3–5 representative posts (ID, source, subreddit if any, score, date, short excerpt ≤ 200 chars) so explanations are grounded and auditable. Store links, not full text, in reports.

## 4A. Bottleneck Arbitrage Engine (Phase 11)

### 4A.1 Concept

Bottleneck arbitrage starts from a large, well-funded theme (AI data centers, electrification, reshoring), maps the supply chain the theme depends on, and looks for the **layer where supply cannot grow as fast as demand**: long lead times, waitlists, rising prices, few suppliers, capacity that takes years to add. Companies selling into that layer gain volume and pricing power at the same time, and that shows up in revenue and margins before most of the market has priced it. The full method is in `bottleneck-arbitrage.md` at the repo root; `consumer-trends.md` is its companion for the first signal.

It is the **second Market Intelligence signal**, and it lives under the same rules as the consumer-trend signal in section 4:

- It **re-orders stocks that already passed the quality gate; it never adds one.** A bottleneck pure play that is not on the good-to-own list appears on the board flagged *not on the good-to-own list*, exactly as a private brand appears on the trend board. A user may add it; it then faces the same numeric gate as everything else.
- It is the **smallest ranking weight**. The two signals together are capped at 15% of the final score (section 3.7).
- **Every number is computed in Python.** The LLM classifies text snippets; it does not score, rank or predict.
- **Evidence is shown**, with links to the filing, data series or article behind every reading.
- No predictive claim is made. The signal study (section 11.4) reports what the historical relationship was, with its confidence intervals.

**How it differs from the consumer-trend signal.** The trend signal measures *attention* (mentions of a product); its sources are social posts, its time scale is one to three quarters, and its enemy is hype. The bottleneck signal measures a *shortage*; its sources are company filings, government and industry price series and trade news, its time scale is several quarters, and its enemy is **new supply**, which the engine must track as a negative because cyclical shortages end that way and the stocks usually turn while prices are still rising.

**Honest constraint on this universe.** The curated list is large, profitable, dividend-paying companies. For most of them the constrained layer is a side business (Texas Instruments and Cisco in the AI build-out, Exxon and Chevron in power and fuel, Honeywell and Union Pacific in industrial electrification), so `materiality` is usually low or medium and the per-company score is deliberately damped. The board still shows the pure plays as context so the user can see where the exposure actually is.

### 4A.2 The ten steps and where each one lives

The method is a ten-step cycle: theme → supply chain → bottleneck → signals → companies → priced in? → catalyst → position → monitor → exit. The table says which part of the system performs each step, and whether it is curated by a human, computed in Python or classified by the LLM. Steps 1, 2 and 5 are **curated configuration**, because "which layers does AI need" and "how much of Texas Instruments' revenue is this" are judgments that belong in a reviewable YAML file, not in a prompt.

| Step | What the method asks | Who does it here | Where | Output |
|---|---|---|---|---|
| 1 Pick a theme | Is real money flowing in? | Human, curated | `config/themes.yaml → themes[]` with `spend_evidence` URLs | theme list |
| 2 Map the supply chain | List every layer the theme needs | Human, curated (an optional LLM job proposes additions for review) | `themes[].layers[]` | layer tree |
| 3 Find the bottleneck | Can supply grow as fast as demand? | Python signals (tightness mentions, price trend, supplier count, capacity lead time) | `bottleneck/signals.py` | `tightness` per layer |
| 4 Gather early signals | Filings, price trackers, trade press, forums, deal news; keep a dated journal | Adapters fetch; LLM classifies snippets; dated snapshots are the journal | `bottleneck/adapters/`, `bottleneck/classify.py`, `data/bottleneck_snapshots.sqlite` | dated snapshot |
| 5 Identify the companies | Materiality, pricing power, ability to deliver | Human, curated; tickers SEC-validated at load | `themes[].layers[].companies[]` | per-ticker exposure |
| 6 Priced in? | How far has it run, how widely is it covered, valuation vs growth | Python, from market data and news coverage | `signals.py → priced_in` | 0–1 penalty |
| 7 Find the catalyst | Earnings, guidance, contracts, data releases | Python: next earnings date (existing tool) and configured release dates | `signals.py → catalyst_days` | days to catalyst |
| 8 Size and enter | Loss budget, staged entry, vehicle, written thesis | Existing Portfolio and Risk agents; strategy-fit **flags** on candidates (4A.8); thesis text is curated | `core/screeners.py` flags, `themes[].layers[].thesis` | flags |
| 9 Monitor | Same signals that got you in | Daily refresh job; thesis monitor evaluates falsifiers | `jobs/refresh_bottlenecks.py`, `bottleneck/thesis.py` | falsifier status |
| 10 Know when to exit | Gap closed, growth decelerating, new supply, thesis broken | Deterministic exit triggers → `easing` flag and score decay; reported, never phrased as advice | `signals.py`, report "Bottleneck board" | flags, decayed score |

### 4A.3 Pipeline

```
Theme map (curated YAML) ─► Fetch per layer: filings, price series, news, forums, trends
                                              │
                                              ▼
                           Clean, dedupe, window into snippets (≤ 400 chars)
                                              │
                                              ▼
                 Snippet classification (LLM): layer · side · direction · kind
                                              │
                                              ▼
       Per-layer time series: tightening vs easing mentions, price level, supply-response items
                                              │
                                              ▼
   Signals: tightness_z, customer_confirmation, price_trend, price_deceleration, supply_response,
            cross_source, priced_in, catalyst_days  (+ curated materiality, pricing_power, capacity)
                                              │
                                              ▼
            Layer score (0–100) ─► Company score = layer score × exposure ─► evidence pack
                                              │
                                              ▼
                       Thesis monitor: evaluate falsifiers, flag easing, decay score
```

### 4A.4 Theme map (`config/themes.yaml`)

The curated supply-chain tree. Every ticker in it is validated against the SEC company list when the config loads; an unknown ticker fails loudly. `curated` is not stored: it is derived from `config/quality_universe.yaml` at load so the two files cannot disagree.

```yaml
themes:
  - id: ai_datacenter
    name: AI data-center build-out
    spend_evidence:                     # step 1: is real money flowing in?
      - {label: "Hyperscaler capex guidance, 10-K/10-Q", url: "https://efts.sec.gov/LATEST/search-index?q=%22capital%20expenditures%22%20%22data%20center%22"}
    layers:                             # step 2: the tree
      - id: power
        name: Power generation and grid equipment
        keywords: ["power constraint", "grid interconnection", "transformer lead time", "gas turbine backlog"]
        price_series: [{source: fred, id: "<PPI series id, verified at setup>", label: "PPI: electric power"}]
        supplier_count: few             # few | several | many  (step 3)
        capacity_lead_years: 3          # years to add meaningful supply (step 3)
        thesis: "Data-center power demand is outrunning grid and turbine supply; equipment makers and fuel suppliers see pricing and backlog growth."
        falsifiers:                     # step 8: what would prove it wrong, as predicates on signals
          - {signal: price_deceleration, op: ">", value: 0.5, snapshots: 2}
          - {signal: supply_response_z, op: ">", value: 1.5, snapshots: 1}
        companies:                      # step 5: who sells into it
          - {ticker: XOM,  role: supplier, materiality: low,    pricing_power: medium, capacity: ample}
          - {ticker: CVX,  role: supplier, materiality: low,    pricing_power: medium, capacity: ample}
          - {ticker: HON,  role: supplier, materiality: medium, pricing_power: high,   capacity: constrained}
          - {ticker: MSFT, role: customer}        # customers confirm demand; they are never scored as suppliers
          - {ticker: GEV,  role: supplier, materiality: high,   pricing_power: high,   capacity: constrained}  # not curated: shown as context only
      - id: memory
        name: DRAM and HBM
        keywords: ["DRAM contract price", "HBM sold out", "memory allocation"]
        ...
```

Curated fields map to numbers in `config/bottleneck_score.yaml` (materiality high/medium/low → 1.0/0.5/0.2, the same map the social score uses; `supplier_count` few/several/many → 1.0/0.5/0.0; `capacity` constrained/ample → 1.0/0.5). A `customer` entry is used only for `customer_confirmation` and is never given a score.

### 4A.5 Data sources

Every adapter has `live` and `fixture` modes behind one protocol and reports a `SourceStatus`, exactly like section 4.3. **Switching sources is configuration:** `config/bottleneck_sources.yaml` enables and weights each one, and `OPTIONS_SCOUT_BOTTLENECK_SOURCES=edgar,fred,news` overrides it per run. `bottleneck/sources.py` is the only place that maps a source name to an adapter class.

| Source | Kind | Use | Access notes |
|---|---|---|---|
| **SEC EDGAR full-text search** (`efts.sec.gov/LATEST/search-index`) | text | 10-K and 10-Q MD&A and risk factors, 8-K earnings releases, searched by layer keywords; the filer's ticker gives `side` (customer or supplier) from the theme map | Free, official; descriptive User-Agent with contact email; respect the 10 req/s guidance. Reuses `social/adapters/sec.py` for ticker validation. Earnings-call transcripts are **not** on EDGAR and are paid elsewhere; a `transcripts` adapter exists in fixture mode only. |
| **FRED** (`api.stlouisfed.org`) | series | Producer-price and industrial series per layer (`price_series` in the theme map) for `price_trend` and `price_deceleration` | Free API key (`FRED_API_KEY`); series ids are configuration and must be verified when a theme is added. |
| **Price-tracker CSV import** | series | Industry trackers the operator has access to (memory contract prices, transformer lead-time surveys) dropped as dated CSVs under `data/bottleneck_series/` | No network; licence is the operator's responsibility; never committed. |
| **News RSS** (existing adapter) | text | Trade and financial headlines for the layer keywords: supply-response items ("new fab", "capacity expansion", "enters market") and deal announcements; also the coverage count for `priced_in` | Free RSS, already implemented in `social/adapters/news.py`; the bottleneck engine passes its own queries. |
| **Reddit** (existing adapter) | text | Industry and enthusiast subreddits (`industry:` list in `config/subreddits.yaml`: r/datacenter, r/hardware, r/buildapcsales, r/electricians, r/solar) for everyday observation: prices paid, availability, complaints | Same provider chain, filters and privacy rules as section 4.3 and PRIVACY.md. |
| **Google Trends** (existing adapter) | series | Search interest in layer keywords ("DRAM price", "transformer shortage") as a cross-source confirmation | Unofficial, optional, as in section 4.3. |

Filings, headlines and price points are **data**, not instructions: snippets are wrapped in delimiters, the classification prompt is told to ignore instructions inside them, and nothing in a snippet can influence a tool call or add a ticker.

### 4A.6 Snippet classification (the only LLM step)

Each snippet (≤ 400 characters, with its source, date and filer ticker when known) is classified in batches of about 20 with Pydantic structured output:

```python
class ConstraintLabel(BaseModel):
    layer_id: str | None            # which layer of the theme the snippet is about, or None
    side: Literal["customer", "supplier", "neutral"]
    direction: Literal["tightening", "easing", "neutral"]
    kind: Literal["lead_time", "price", "capacity", "deal", "coverage", "other"]
    confidence: float               # 0..1
```

Prompt `prompts/classify_bottleneck.md` (versioned). Temperature 0. A rule-based stand-in (direction lexicons per `kind`, layer by keyword hit) serves `--no-llm` mode and is what the offline eval measures. Every ticker a label mentions must exist in the SEC list or the label is discarded. Results are cached in SQLite keyed by snippet hash.

### 4A.7 Signals and score (computed in Python)

| Signal | Definition |
|---|---|
| `tightness_z` | z-score of (tightening − easing) snippet counts for the layer over the last 7 days vs the weekly mean/std of the prior 8 weeks (the analogue of `velocity_z`) |
| `customer_confirmation` | share of tightening snippets whose filer is a `customer` in the theme map: the hyperscaler saying "power constrained" is the demand side confirming the supplier's story |
| `price_trend` | normalised 90-day slope of each configured price series, averaged over the layer's series |
| `price_deceleration` | second difference of the price series: positive when prices still rise but more slowly. **This is a penalty**, because cyclical bottleneck stocks tend to peak here (step 10) |
| `supply_response_z` | z-score of `kind == capacity` easing items (new fabs, expansions, new entrants) and `direction == easing` deal items. **Penalty** |
| `cross_source` | number of enabled sources whose own tightening series has z > 1.5; `cross_source_norm` divides by the number enabled |
| `priced_in` | 0–1 penalty blended from the company's 90-day return relative to SPY, distance to its 52-week high, the z-score of news coverage of the layer and its IV rank, all from data the app already fetches (step 6) |
| `catalyst_days` | days to the company's next earnings date or the next configured data release (step 7); feeds flags and a small proximity term |
| `supplier_scarcity`, `capacity_lead` | curated `supplier_count` and `capacity_lead_years` mapped to 0–1 (step 3) |
| `materiality`, `pricing_power`, `capacity_to_deliver` | curated per company (step 5), mapped to 0–1 |

**Layer score** (weights in `config/bottleneck_score.yaml`):
```
layer = 100 × sigmoid( w1·tightness_z + w2·customer_confirmation + w3·price_trend
                     + w4·cross_source_norm + w5·supplier_scarcity + w6·capacity_lead
                     − w7·price_deceleration − w8·supply_response_z + bias )
```
**Company score** = `layer × exposure`, with `exposure = materiality × (0.5 + 0.25·pricing_power + 0.25·capacity_to_deliver) × (1 − w9·priced_in)`, clipped to 0–100. A company in several layers takes the maximum. A ticker with no entry gets the neutral 50 in the ranker, as a ticker with no trend gets today. Golden values for one hand-computed layer and company are recorded in `tests/fixtures/golden_bottleneck.json`.

### 4A.8 Strategy-fit flags (step 8, from `bottleneck-arbitrage.md`)

The method says a shortage suits a long-dated call, suits a covered-call structure only outside catalysts, and is a reason **not** to sell puts once supply is arriving. The app expresses that as deterministic **flags on candidates, never as filters**, in the same way `earnings_before_expiry` works today:

| Flag | Set when | Shown on |
|---|---|---|
| `bottleneck_support` | the ticker's company score ≥ `flags.support_min` (default 70) | LEAPS and CSP rows, informational |
| `bottleneck_easing` | a falsifier has tripped, or `price_deceleration` or `supply_response_z` exceeds its flag threshold | CSP rows; the Education narrative must state it in the same sentence as the candidate for `conservative` profiles (extends the existing `check_suitability` earnings rule) |
| `catalyst_inside_dte` | `catalyst_days` < the candidate's DTE for a CSP or a PMCC short call | CSP and PMCC short-call rows; generalises the earnings flag to configured data releases |

### 4A.9 Thesis monitor (steps 8–10: write it down, track it, know when it is wrong)

Each layer carries a one- or two-sentence `thesis` and a list of `falsifiers`, each a predicate on a computed signal that must hold for `snapshots` consecutive daily snapshots. `jobs/refresh_bottlenecks.py` evaluates them on every run and stores the result with the snapshot, so the board shows the thesis, every falsifier with *holding* / *tripped since <date>*, and the dated history: the method's journal, kept by the machine. When any falsifier trips, the company scores in that layer are multiplied by `easing_decay` (default 0.5), `bottleneck_easing` is set, and the board says *thesis weakening*. The app reports the state of the thesis; it never says *exit*, *sell* or *take profits*. The Compliance language policy (section 13.1) applies to this section of the report like any other.

Snapshots contain no personal data (public filings, aggregate series, headline metadata), so they are retained for `bottleneck.retention_days` (default 180) to feed the signal study; the 48-hour rule for social snapshots is unchanged.

### 4A.10 Evidence pack

Per layer, 3–5 items: a filing excerpt (≤ 200 characters, accession URL, filer, date, label), a price point with series id and source URL, a supply-response or deal headline with link. Reports store links and short excerpts, not full text. These items are indexed into the per-thread evidence collection by `evidence_retrieval_node` so a "why is HON ranked above UNP" answer can cite them.

### 4A.11 What the signal is not allowed to do

The same containment as section 4: it cannot add a ticker, it is capped in the ranking, its flags never filter, its score is damped by materiality and priced-in, and the engine's own exit triggers decay it. Its board, like the trend board, is labelled *secondary* and carries the caption "re-orders, never adds".

---

## 5. Agent Architecture (LangGraph)

### 5.0 Specialist agents (the graded structure)

The brief grades a **six-specialist + compliance** structure. The nodes in 5.1/5.2 are *not* replaced; they are grouped into subgraphs, one per specialist, each with its own state slice (a Pydantic model), its own typed tools, its own `prompts/<agent>_*.md` files where it uses an LLM, and its own test module. The parent graph in `agent/graph.py` composes the subgraphs; `agent/agents/<name>.py` builds each one with `build_<name>_agent() -> CompiledGraph`.

```mermaid
flowchart TD
    U[User · chat or form] --> O[Orchestrator<br/>intake · route · human_review]
    O -->|new screen / what-if| MI[2 · Market Intelligence Agent<br/>trend_scout · bottleneck_scout · evidence retrieval]
    MI --> MD[1 · Market Data Agent<br/>regime · universe · market_data + quality gate]
    MD --> ST[3 · Strategy Agent<br/>screener · ranker]
    ST --> PF[4 · Portfolio Agent<br/>allocator · sizing]
    PF --> RK[5 · Risk Agent<br/>constraints · stress · suitability facts]
    RK -->|retries ≤ 3| PF
    RK --> ED[6 · Education Agent<br/>explainer · concept Q&A · payoff narratives<br/>RAG over knowledge base + evidence]
    O -->|concept / why question| ED
    ED --> CP[Compliance Agent<br/>numeric grounding · citations · suitability<br/>banned language · disclaimer · audit log]
    CP -->|fail, retries ≤ 2| ED
    CP -->|pass| R[Report / chat reply]
```

*Execution order (decided in step 10.1):* Market Intelligence runs **before** Market Data because `universe_node` orders the curated list by trend score (from Phase 11, by the higher of the trend and bottleneck scores) and caps it, so the boards are an input to the universe. The numbering (1 Market Data, 2 Market Intelligence) is the rubric's mapping, not the run order. On a sizing retry only `sizing_node` re-runs inside Portfolio (the allocation is a pure function of profile and regime).

| # | Agent | Subgraph nodes (existing) | Tools (deterministic) | LLM use | State slice |
|---|---|---|---|---|---|
| 0 | **Orchestrator** | `intake_node`, `route_node` (new), `human_review` | – | parse profile; classify message intent | `profile`, `intent`, `thread` |
| 1 | **Market Data** | `regime_node`, `universe_node`, `market_data_node` (+ quality gate), `Send` fan-out | `get_regime`, `get_snapshot`, `quality_gate` | none | `regime`, `universe`, `market_data`, `quality` |
| 2 | **Market Intelligence** | `trend_scout_node`, `bottleneck_scout_node` (Phase 11), `evidence_retrieval_node` (new) | social pipeline, bottleneck pipeline (section 4A), `retrieve_evidence` | entity extraction; constraint classification | `trends`, `bottlenecks`, `evidence` |
| 3 | **Strategy** | `screener_node`, `ranker_node` | `screen_csp`, `screen_leaps`, `pair_pmcc`, `rank` | none | `candidates`, `ranked` |
| 4 | **Portfolio** | `allocator_node`, `sizing_node` | `allocate`, `size_portfolio` | none | `allocation`, `portfolio` |
| 5 | **Risk** | `risk_node` | `check_constraints`, `stress_test`, `suitability_facts` | none | `risk` |
| 6 | **Education** | `explainer_node`, `knowledge_retrieval_node` (new), `concept_answer_node` (new) | `retrieve_knowledge`, `payoff_curve`, `glossary_lookup` | narrative + Q&A, **must cite** | `citations`, `narrative`, `answer` |
| C | **Compliance** | `verifier_node` → renamed `compliance_node`, plus `audit_node` | `check_numbers`, `check_citations`, `check_suitability`, `check_language`, `check_disclaimer` | optional judge | `compliance` |

Rules:
- **Every LLM-written string reaches the user only through the Compliance agent.** That includes the report narrative, chat answers, and concept explanations. There is no edge from Education to the UI.
- Specialists communicate only through typed state. No specialist imports another specialist's module; shared logic lives in `core/`, `social/`, `rag/`.
- Each specialist can run standalone for tests: `build_risk_agent().invoke({...})` with a fixture state must produce its slice.
- If the brief names the six agents differently, **rename the files and headings, not the structure.** The mapping to keep: data acquisition → 1; research/news/sentiment → 2; strategy/screening → 3; portfolio/allocation → 4; risk → 5; education/advisor → 6; compliance → C.

### 5.1 Node-level graph (inside the specialists)

```mermaid
flowchart TD
    A[intake_node<br/>parse user request → UserProfile] --> B{profile complete?}
    B -- no --> H[human_review<br/>interrupt: confirm/fix profile]
    H --> A
    B -- yes --> C[regime_node<br/>VIX percentile, risk-free rate]
    C --> D[allocator_node<br/>split buying power]
    D --> E[trend_scout_node<br/>consumer-trend scores]
    E --> E2[bottleneck_scout_node<br/>bottleneck scores · Phase 11]
    E2 --> F[universe_node<br/>merge signal scores + user watchlist, filter investable]
    F --> G[[fan-out per ticker via Send]]
    G --> I[market_data_node<br/>chains, spot, earnings, HV]
    I --> J[screener_node<br/>CSP / LEAPS / PMCC candidates]
    J --> K[ranker_node<br/>combine option quality + stock quality + signal scores]
    K --> L[sizing_node<br/>constrained position sizing]
    L --> M[risk_node<br/>constraints + stress tests]
    M --> N{constraints pass?}
    N -- no, retries < 3 --> L
    N -- yes --> O[explainer_node<br/>LLM narrative from computed data]
    O --> P[verifier_node<br/>numeric grounding + policy checks]
    P -- fail, retries < 2 --> O
    P -- pass --> Q[report_node<br/>final JSON + Markdown]
```

### 5.2 Node responsibilities

| Node | LLM? | Responsibility |
|---|---|---|
| `intake_node` | Yes (structured output) | Turn free text into `UserProfile`. Missing required fields (buying power, account type, risk profile) → route to `human_review` with an `interrupt()`. |
| `human_review` | No | LangGraph interrupt; UI shows parsed profile for confirmation. |
| `regime_node` | No | Fetch `^VIX`, compute 1-year percentile; risk-free rate from `^IRX` (13-week T-bill). |
| `allocator_node` | No | Apply section 3.1 rules → `AllocationPlan`. |
| `trend_scout_node` | Yes (entity extraction) + No (signals) | Run section 4 pipeline, or load latest scored snapshot if fresh (< 24h). |
| `bottleneck_scout_node` | Yes (snippet classification) + No (signals) | Phase 11. Run the section 4A pipeline, or load the latest scored snapshot if fresh (< 24h); evaluate the thesis monitor; write `bottlenecks` and `bottleneck_scores`. Never fatal: a failure records an error and leaves neutral scores. |
| `universe_node` | No | Curated good-to-own list ∪ user watchlist − exclusions, ordered per section 3.7 and capped at `max_tickers`. Trend or bottleneck tickers not on the list are noted and skipped. |
| `market_data_node` | No | Per ticker (parallel via `Send`): spot, option chains for relevant expiries, earnings date, HV30, dividend yield, 90-day closes. Then the **quality gate** (section 3.7): a failing ticker is written to `state.quality` with reasons and *not* to `market_data`, so screeners never see it. Cached. |
| `screener_node` | No | Apply sections 3.3–3.5 to tickers that passed the gate; compute Greeks with own BSM from chain IV. |
| `ranker_node` | No | `final = w1·option_quality + w2·quality_score + w3·social/100` (weights in `settings.yaml`, default 0.50/0.35/0.15; Phase 11 adds `w4·bottleneck/100` with defaults 0.50/0.35/0.10/0.05). Option quality = normalized blend of annualized return, POP, liquidity, IV rank fit. Keeps the best `ranking.max_per_ticker` (default 2) contracts per ticker and strategy; the rest are dropped with a note in `errors`. |
| `sizing_node` | No | Greedy allocation over ranked candidates subject to all constraints (section 3.2); integer contracts. Optional: `scipy.optimize.milp` version as stretch goal. |
| `risk_node` | No | Validate constraints, run stress tests (−10/−20/−30% with IV +50% shock repriced via BSM), produce warnings. |
| `explainer_node` | Yes | Write the narrative **only from** a JSON payload of computed results. Must cite candidate IDs. |
| `verifier_node` | Partly | Deterministic: extract every number from the narrative (regex) and confirm each appears in the payload (tolerance for rounding). Policy: banned phrases ("guaranteed", "you should buy", "risk-free"), disclaimer present. Optional LLM-as-judge for tone. |
| `report_node` | No | Assemble `ScreeningReport` (JSON) + Markdown rendering. |

### 5.3 State schema (sketch)

```python
class AgentState(TypedDict):
    request_text: str
    profile: UserProfile | None
    regime: MarketRegime | None
    allocation: AllocationPlan | None
    trends: list[TrendSignal]
    bottlenecks: list[BottleneckSignal]        # Phase 11
    bottleneck_scores: dict[str, float]        # Phase 11
    universe: list[str]
    market_data: Annotated[dict[str, TickerSnapshot], merge_dicts]  # reducer for fan-out
    candidates: Annotated[list[OptionCandidate], operator.add]
    ranked: list[RankedCandidate]
    portfolio: SizedPortfolio | None
    risk: RiskReport | None
    narrative: str | None
    verification: VerificationResult | None
    retries: dict[str, int]
    errors: Annotated[list[str], operator.add]
```

### 5.4 LangGraph features to use (these are resume talking points)
- `StateGraph` with typed state and reducers for parallel fan-out.
- **Subgraphs** (Phase 10): one compiled graph per specialist, composed by the parent graph; each testable standalone.
- **Conditional routing by intent** (Phase 10): the Orchestrator sends chat turns to a subset of specialists (concept → Education → Compliance; what-if → full run on a new thread).
- `Send` API for map-reduce over tickers.
- `interrupt()` + `Command(resume=...)` for human-in-the-loop profile confirmation.
- Checkpointing with SQLite (`langgraph-checkpoint-sqlite`) → resumable runs, thread IDs per user session.
- Conditional edges with bounded retry loops (sizing ↔ risk, explainer ↔ verifier).
- Streaming node updates to the UI (show progress per node).
- Graceful degradation: if a data source fails, record in `errors`, continue with remaining sources, and say so in the report.

### 5.5 LLM layer
- Provider abstraction `llm/client.py` with one function per task (`extract_entities`, `parse_profile`, `explain`, `judge`). Default provider: Anthropic Claude via `langchain-anthropic`; allow swapping by config. Use a small/cheap model for extraction, a stronger one for explanation.
- Always use structured output (Pydantic schemas) for extraction and parsing.
- Temperature 0 for extraction/parsing.
- Token and cost accounting per run, stored with the report.
- Prompt injection hygiene: social posts are **data**. Wrap them in clear delimiters, instruct the model to ignore instructions inside posts, and never let post content influence tool calls.
- New prompt files for Phase 10: `route_message.md` (orchestrator intent), `answer_concept.md` (Education Q&A with citations), `explain_report.md` → 2.0.0 (adds a `sources` block and the citation format), `judge_compliance.md` (optional tone judge). Phase 11 adds `classify_bottleneck.md` (section 4A.6).

### 5.6 Retrieval (RAG) layer: `src/options_scout/rag/`

Retrieval exists for one reason: **educational and market-intelligence claims must be traceable to a source the user can read.** Numbers still come only from computed payloads; retrieval supplies *concepts, rules and evidence*, never prices.

**Corpus (`knowledge/`, committed, Markdown with YAML front-matter `id, title, source, url, kind, as_of`):**
1. `knowledge/concepts/*.md` — authored in this repo (≈ 20 docs, 300–800 words each): cash-secured put, naked put on margin, LEAPS, PMCC, assignment, delta/theta/vega/gamma, extrinsic value, IV rank, Reg T margin, probability OTM, early assignment and dividends, earnings risk, liquidity (spread/OI), rolling, why hype is a risk for short puts, how this app's quality gate works, and (Phase 11) bottleneck arbitrage: why a shortage lifts a supplier and why its ending is a risk for short puts. Each cites its primary source (OCC *Characteristics and Risks of Standardized Options* section numbers, FINRA/Cboe pages, this PRD) by URL. **Do not vendor copyrighted PDFs**; link to them. `scripts/fetch_public_docs.py` can optionally download the OCC booklet for a local, gitignored index.
2. `knowledge/rules/*.md` — generated from PRD sections 3.1–3.7 and `config/*.yaml` by `scripts/build_rules_docs.py` so a "why was X excluded" answer can cite the exact rule and threshold in force.
3. `knowledge/filings/<TICKER>.md` — SEC 10-K Item 1A risk-factor excerpts (public domain) for the curated universe, fetched by `scripts/fetch_filings.py` through the existing `social/adapters/sec.py` (fixture copies for the 10 demo tickers are committed).
4. **Runtime evidence** — the trend scout's evidence posts and news items for the current run, and from Phase 11 the bottleneck board's filing excerpts, price points and supply-response headlines, are indexed into an in-memory collection per thread so Market Intelligence answers ("why is COST ranked above WMT") cite the actual posts.

**Pipeline:** `rag/chunking.py` (heading-aware, ≤ 400 tokens, 15% overlap, chunk id = `<doc_id>#<n>`) → `rag/embeddings.py` (`Embedder` protocol: `FastEmbedEmbedder` with `BAAI/bge-small-en-v1.5` for live/dev, `HashEmbedder` — deterministic feature hashing — for tests and CI so nothing downloads) → `rag/store.py` (SQLite table `chunks(id, doc_id, text, meta_json, vector BLOB)`; cosine search in numpy; corpus is small) + `rag/bm25.py` (`rank_bm25`) → `rag/retriever.py` (hybrid: reciprocal-rank fusion of dense + BM25, `top_k` 6, optional `kind` filter) → `Citation(chunk_id, doc_id, title, url, quote)` objects in state.

**Contract with the LLM:** the Education prompt receives numbered `[S1]…[Sn]` sources and must mark every non-numeric claim with the source tag it relies on. The Compliance agent's `check_citations` verifies that every tag used exists in the retrieved set and that every sentence containing a definitional or regulatory claim carries a tag (sentences that only restate payload numbers are exempt). Answers with zero retrieved chunks above the similarity floor return the fixed sentence *"I don't have a source for that in my knowledge base."* rather than an unsupported answer.

**Config (`config/rag.yaml`):** `embedder` (`fastembed` | `hash`), `top_k`, `similarity_floor`, `chunk_tokens`, `overlap`, `collections` (`concepts`, `rules`, `filings`, `evidence`) with weights. `make index` rebuilds `data/knowledge.sqlite`; the index is built lazily on first use if missing.

---

## 6. Tools (typed, deterministic, individually tested)

```python
get_spot(ticker) -> SpotQuote
get_option_chain(ticker, expiry) -> OptionChain           # MarketData.app / Tradier
list_expiries(ticker) -> list[date]
get_earnings_date(ticker) -> date | None
get_hist_vol(ticker, window=30) -> float
get_dividend_yield(ticker) -> float
get_vix_percentile(lookback_days=252) -> float
get_risk_free_rate() -> float                             # ^IRX / 100
PostSource.fetch(since) -> list[SocialPost]                 # RedditAdapter, XAdapter
AttentionSource.fetch(keyword, start, end) -> list[DailyCount]  # WikipediaAdapter, GoogleTrendsAdapter
fetch_news_mentions(query, since) -> list[NewsItem]
FilingSource.fetch(keywords, since, forms) -> list[FilingSnippet]   # Phase 11: EDGAR full-text search
SeriesSource.fetch(series_id, start, end) -> list[DailyCount]       # Phase 11: FRED, CSV import
classify_constraints(snippets) -> list[ConstraintLabel]              # Phase 11: LLM, SEC-validated
score_bottlenecks(theme_map, labels, series, market) -> list[BottleneckSignal]   # Phase 11
evaluate_thesis(layer, history) -> ThesisStatus                     # Phase 11
build_sources(cfg, mode) -> SourceSet                      # enabled adapters from social_sources.yaml
resolve_entity(name) -> TickerResolution | None
bsm_greeks(S, K, T, r, q, sigma, kind) -> Greeks
reg_t_put_margin(S, K, premium) -> float
check_quality(snapshot, closes, universe, curated) -> QualityCheck   # section 3.7 gate + score
screen_csp(snapshot, rules) -> list[OptionCandidate]
screen_leaps(snapshot, rules) -> list[OptionCandidate]
pair_pmcc(leaps, chain, rules) -> list[PMCCCandidate]
size_portfolio(ranked, profile, allocation, limits) -> SizedPortfolio
stress_test(portfolio, shocks) -> RiskReport
```

Data notes:
- **Market data providers** all implement the `MarketSource` protocol in `data/market.py`: `FixtureSource` (bundled JSON), `MarketDataAppSource` (default; **user-supplied token**, free plan delayed with ~100 credits/day; quotes, candles, expirations, chains with IV, upcoming earnings, VIX; dividend yield implied from adjusted vs split-only candles; no ^IRX → constant risk-free fallback; `strike_limit` trims chains because each contract costs a credit) and `TradierSource` (**user-supplied API key**; free sandbox token = 15-min delayed quotes, expirations, chains with IV, daily history; earnings/dividends best-effort from the beta fundamentals endpoints; ^VIX/^IRX fall back to MarketData.app when that token is configured). The UI and `POST /v1/recommend` accept the provider and key **per run**; the key is a `SecretStr`, is sent only as a bearer header, and is never logged, cached, persisted or echoed in errors. The SQLite cache is namespaced by provider. Adding another keyed provider = one class + one `MarketData.from_config` branch + a mocked-transport unit test.
- MarketData.app is metered (one credit per option contract returned) and delayed on the free plan. Wrap every call with retries + exponential backoff on transport/5xx errors only (4xx are final), cache results (SQLite, TTL 15 min for chains, 24h for earnings/dividends), trim chains with `strike_limit`, and keep fixture snapshots for 10 demo tickers.
- Provider chains give IV (MarketData.app also Greeks) → compute Greeks with our own BSM so every provider is treated the same.
- Label all market data in the UI as "delayed, for education only".

---

## 7. Data Models (Pydantic v2, `core/models.py`)

```python
class UserProfile(BaseModel):
    buying_power: PositiveFloat
    account_value: PositiveFloat
    account_type: Literal["cash", "margin", "portfolio_margin"]
    risk_profile: Literal["conservative", "balanced", "aggressive"]
    strategies: set[Literal["csp", "leaps", "pmcc"]] = {"csp", "leaps", "pmcc"}
    watchlist: list[str] = []
    exclude: list[str] = []
    max_positions: int = 8
    options_level: int | None = None   # broker approval level, informational

class OptionCandidate(BaseModel):
    id: str                            # e.g. "CSP-COST-2026-12-04-900P"
    strategy: Literal["csp", "leaps", "pmcc_short_call"]
    ticker: str
    expiry: date
    dte: int
    strike: float
    kind: Literal["call", "put"]
    bid: float; ask: float; mid: float
    spread_pct: float
    open_interest: int
    iv: float
    iv_rank: float | None
    iv_rank_source: Literal["history", "hv_proxy", "none"]
    delta: float; gamma: float; theta: float; vega: float
    prob_otm: float
    collateral: float | None
    margin_req: float | None
    annualized_return: float | None
    extrinsic_per_year_pct: float | None
    breakeven: float
    earnings_before_expiry: bool
    flags: list[str]

class TrendSignal(BaseModel):
    entity: str
    entity_type: str
    ticker: str | None
    investable: bool
    score: float
    components: dict[str, float]
    evidence: list[EvidenceItem]
    as_of: datetime

class BottleneckSignal(BaseModel):          # Phase 11, section 4A
    theme_id: str
    layer_id: str
    layer_name: str
    ticker: str | None                       # None for the layer row itself
    role: Literal["supplier", "customer"] | None
    curated: bool                            # on the good-to-own list?
    investable: bool                         # curated and role == supplier
    layer_score: float                       # 0–100
    score: float                             # company score 0–100 (== layer_score for the layer row)
    components: dict[str, float]             # every signal in 4A.7 plus exposure and priced_in
    thesis: str
    falsifiers: list[FalsifierStatus]        # (signal, op, value, snapshots, tripped, since)
    catalyst_days: int | None
    flags: list[str]                         # bottleneck_support, bottleneck_easing, catalyst_inside_dte
    evidence: list[EvidenceItem]
    as_of: datetime
```

Also define: `MarketRegime`, `AllocationPlan`, `QualityCheck` (ticker, curated, passed, score, components, metrics, reasons, why_good_to_own), `RankedCandidate` (incl. `quality_score`), `SizedPosition`, `SizedPortfolio`, `RiskReport`, `VerificationResult`, `ScreeningReport` (incl. `quality: list[QualityCheck]`).

---

## 8. Repository Layout

```
options-scout-ai/
├── PRD.md
├── README.md
├── pyproject.toml
├── Makefile
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── config/
│   ├── settings.yaml          # global (cache TTLs, model names, alpha)
│   ├── risk_profiles.yaml     # sections 3.1–3.2
│   ├── screener_rules.yaml    # sections 3.3–3.5
│   ├── social_score.yaml      # weights
│   ├── quality_universe.yaml  # section 3.7: curated good-to-own list + numeric gates + score weights
│   ├── social_sources.yaml    # section 4.3: which post/attention sources run, weights, X queries
│   ├── subreddits.yaml        # consumer + stock subs; Phase 11 adds an `industry:` list
│   ├── themes.yaml            # Phase 11, section 4A.4: theme → layers → companies, thesis, falsifiers
│   ├── bottleneck_score.yaml  # Phase 11: signal weights, curated-field maps, flag thresholds
│   └── bottleneck_sources.yaml # Phase 11: which filing/series/text sources run
├── data/
│   ├── brand_map.yaml
│   └── cache.sqlite           # gitignored
├── prompts/
│   ├── parse_profile.md
│   ├── extract_entities.md
│   ├── explain_report.md
│   ├── judge_explanation.md
│   └── classify_bottleneck.md # Phase 11
├── src/options_scout/
│   ├── core/
│   │   ├── models.py
│   │   ├── pricing.py         # BSM, Greeks, POP
│   │   ├── margin.py          # Reg T, collateral
│   │   ├── volatility.py      # HV, IV rank, VIX percentile
│   │   ├── screeners.py       # CSP, LEAPS, PMCC
│   │   ├── quality.py         # good-to-own gate + score (section 3.7)
│   │   ├── ranking.py
│   │   ├── sizing.py
│   │   ├── risk.py            # constraints, stress tests
│   │   └── allocation.py
│   ├── social/
│   │   ├── adapters/          # base.py (protocols), reddit.py, x.py, wikipedia.py, google_trends.py, news.py, sec.py
│   │   ├── sources.py         # source name -> adapter; builds the enabled SourceSet
│   │   ├── filters.py         # spam, dedupe, author caps
│   │   ├── extraction.py      # LLM entity extraction
│   │   ├── resolution.py      # brand → ticker
│   │   ├── signals.py
│   │   └── score.py
│   ├── bottleneck/            # Phase 11, section 4A: the second Market Intelligence signal
│   │   ├── adapters/          # base.py (FilingSource, SeriesSource), edgar_fts.py, fred.py, csv_series.py, transcripts.py (fixture only)
│   │   ├── sources.py         # source name -> adapter; builds the enabled set
│   │   ├── themes.py          # typed theme map, SEC validation, curated flag from quality_universe
│   │   ├── snippets.py        # clean, dedupe, window filings/headlines into ≤ 400-char snippets
│   │   ├── classify.py        # LLM classification + rule-based stand-in
│   │   ├── signals.py
│   │   ├── score.py
│   │   ├── thesis.py          # falsifier evaluation, easing decay
│   │   └── pipeline.py
│   ├── data/
│   │   ├── market.py          # MarketData.app / Tradier wrappers + cache
│   │   ├── cache.py
│   │   └── fixtures.py
│   ├── llm/
│   │   ├── client.py
│   │   └── prompts.py         # loads prompts/*.md
│   ├── rag/                   # Phase 10, section 5.6
│   │   ├── models.py          # Chunk, Citation, RetrievalResult
│   │   ├── chunking.py
│   │   ├── embeddings.py      # Embedder protocol: HashEmbedder (tests), FastEmbedEmbedder (live)
│   │   ├── bm25.py
│   │   ├── store.py           # SQLite chunks + numpy cosine
│   │   └── retriever.py       # hybrid RRF, kind filter, similarity floor
│   ├── agent/
│   │   ├── state.py           # AgentState composed of per-agent slices
│   │   ├── nodes/             # one file per node (unchanged bodies)
│   │   ├── agents/            # Phase 10, section 5.0: one subgraph per specialist
│   │   │   ├── orchestrator.py
│   │   │   ├── market_data.py
│   │   │   ├── market_intelligence.py
│   │   │   ├── strategy.py
│   │   │   ├── portfolio.py
│   │   │   ├── risk.py
│   │   │   ├── education.py
│   │   │   └── compliance.py
│   │   └── graph.py           # parent graph composing the subgraphs
│   ├── core/compliance.py     # Phase 10, section 13.1 (replaces agent/verifier.py)
│   ├── core/payoff.py         # Phase 10: payoff-at-expiry curves
│   ├── mcp/
│   │   └── server.py          # Phase 10, section 10.1 (FastMCP, stdio)
│   ├── api/
│   │   ├── main.py            # FastAPI (+ /v1/chat, /v1/threads)
│   │   └── schemas.py
│   ├── jobs/
│   │   ├── snapshot_iv.py     # daily IV snapshot
│   │   ├── refresh_trends.py
│   │   └── refresh_bottlenecks.py   # Phase 11: daily snapshot + thesis monitor
│   └── observability.py
├── knowledge/                 # Phase 10 RAG corpus (Markdown + front-matter)
│   ├── concepts/              # authored here, cite primary sources by URL
│   ├── rules/                 # generated from PRD §3 + config/*.yaml by scripts/build_rules_docs.py
│   └── filings/               # SEC 10-K Item 1A excerpts (public domain) via scripts/fetch_filings.py
├── docs/
│   ├── architecture.md        # one page per agent
│   ├── compliance.md          # rules with accepted / rejected examples
│   ├── rag.md                 # corpus, licences, how to add a doc
│   └── screenshots/           # one per tab
├── ui/
│   ├── streamlit_app.py       # shell: st.tabs
│   ├── session.py
│   ├── theme.py
│   ├── charts.py
│   └── tabs/                  # scout, setup, quality, candidates, portfolio, learn, trends, under_the_hood
├── evals/
│   ├── datasets/
│   │   ├── entity_extraction_labeled.jsonl
│   │   ├── profile_parsing.jsonl
│   │   ├── adversarial_posts.jsonl
│   │   ├── rag_questions.jsonl          # Phase 10
│   │   ├── chat_routing.jsonl           # Phase 10
│   │   ├── advice_narratives.jsonl      # Phase 10
│   │   ├── suitability_cases.jsonl      # Phase 10
│   │   └── bottleneck_snippets_labeled.jsonl   # Phase 11: 100 labelled filing/news snippets
│   ├── run_evals.py
│   └── reports/
├── notebooks/
│   └── signal_study.ipynb     # section 11.4
└── tests/
    ├── fixtures/
    ├── unit/
    ├── integration/
    └── agent/
```

---

## 9. API (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/recommend` | **Simple front door:** `{buying_power, strategy: csp\|leaps\|both, account_type?, risk_profile?, watchlist?, exclude?, pmcc?, market_data?: {provider, api_key, sandbox}}`. Defaults: cash account, conservative. Returns `thread_id`. |
| GET | `/v1/quality-universe` | The curated good-to-own list and the current gate values. |
| POST | `/v1/screen` | Start a run from `{request_text}` or a full `UserProfile`; optional `market_data` as above. Returns `thread_id`. |
| GET | `/v1/runs/{thread_id}` | Status, current node, partial results. |
| GET | `/v1/runs/{thread_id}/stream` | Server-sent events of node updates. |
| POST | `/v1/runs/{thread_id}/resume` | Resume after human review with corrected profile. |
| GET | `/v1/runs/{thread_id}/report` | Final `ScreeningReport` (JSON) or `?format=md`. |
| GET | `/v1/trends` | Latest trend board. |
| GET | `/v1/bottlenecks` | Latest bottleneck board with thesis-monitor status (Phase 11). |
| GET | `/healthz` | Health check including data-source status. |

Add simple API-key auth via header for the hosted demo, and per-IP rate limiting.

---

## 10. UI (Streamlit): multi-tab app with a chat tab

`ui/streamlit_app.py` becomes a thin shell; each tab is a module in `ui/tabs/`. Shared session state (thread id, last `ScreeningReport`, chat history, data-source choice) lives in `ui/session.py`. Disclaimer banner on every tab, top and bottom, plus the "delayed data" label whenever a report is shown.

| Tab | Module | Content | Rubric line |
|---|---|---|---|
| **Scout** | `tabs/scout.py` | Chat (`st.chat_message` / `st.chat_input`). The user describes their situation; the Orchestrator parses it, the profile-confirmation `interrupt()` renders as an assistant turn with an inline editable profile form and a *Confirm* button; node progress streams as status lines; the finished run posts a short compliance-checked summary and says "see the Candidates and Portfolio tabs". Follow-ups: concept questions → Education agent only; "why was X excluded / ranked there" → Education + evidence retrieval over the current report; "what if I had 30k / cash account" → re-run on a new thread with the modified profile and a one-line diff of what changed. Every assistant message shows a small **Compliance ✓** badge with an expander listing the checks that ran. | conversational flow 8% |
| **Setup** | `tabs/setup.py` | The current form (buying power, strategy, more options, data source / API key) for users who prefer not to chat; *Find candidates* button runs the same graph. | – |
| **Quality Screen** | `tabs/quality.py` | Stocks that passed the gate with quality score, excluded list with reasons, gate thresholds caption, **chart:** quality score bar by ticker coloured by pass/fail. | market intelligence, viz |
| **Candidates** | `tabs/candidates.py` | CSP and/or LEAPS tables (only requested strategies), "show the full math" expander, **charts:** delta vs annualised-return scatter (size = liquidity), premium-vs-strike ladder per ticker. | portfolio analysis, viz |
| **Portfolio & Risk** | `tabs/portfolio.py` | Allocation donut, sized positions, totals, constraint checks, **charts:** stress-test P&L bars per position at −10/−20/−30%, portfolio payoff-at-expiry curve (sum of position payoffs from `core/payoff.py`), realistic-loss vs account % gauge. Margin accounts always show the −30% loss beside the margin requirement. | portfolio analysis 7%, viz 7% |
| **Learn** | `tabs/learn.py` | Education agent surface. Left: glossary list (from `knowledge/concepts`). Right: selected concept rendered with citations, **interactive payoff diagram** (strike, premium, spot sliders → `core/payoff.py`), Greeks explainer that reads the currently selected candidate, Reg T margin walkthrough step by step with the candidate's numbers, "Why hype is a risk for short puts" page tying the trend signal to options risk. Every page is labelled *Education, not advice*. | educational content 8% |
| **Trends** | `tabs/trends.py` | Two boards behind a segmented control, so the app keeps eight tabs. *Consumer trends:* trend board, evidence posts, **charts:** mention velocity per source over time, z-score components bar, sentiment vs purchase-intent scatter. *Bottlenecks (Phase 11):* theme → layer tree with layer scores, the companies per layer with materiality and curated/not-curated flag, evidence (filing excerpts, price points, supply-response items), the thesis monitor, **charts:** tightening-vs-easing mentions over time per layer, price series with the deceleration marker, company score vs priced-in scatter. Each board's caption states its ranking weight and the "re-orders, never adds" rule. | market intelligence 5%, real-time data |
| **Under the hood** | `tabs/under_the_hood.py` | Agent trace: per-specialist latency and status, tokens and cost, compliance audit log for the run, retrieval log (query → chunks → similarity), config hash, data-source status, JSON/Markdown downloads. | architecture evidence, docs |

Charts use Plotly with one shared colour scheme in `ui/theme.py`; every chart has a title, axis labels, units and a one-line caption saying what it shows. No sidebar.

**Legacy form (kept on the Setup tab):**
1. **Buying power ($)**: number input.
2. **What are you looking for?** Radio: *Cash-secured puts* / *LEAPS calls* / *Both*, each with a one-line caption.
3. **More options** (collapsed): account type (default `cash`), risk appetite (default `conservative`), max positions, "also consider these tickers", "never show these tickers", PMCC pairing checkbox (only when LEAPS is selected).
4. **Data source** (collapsed): *Bundled sample data (offline)* / *MarketData.app (paste your API token)* / *Tradier (paste your API key)* with a password field (MarketData.app falls back to `MARKETDATA_TOKEN` when left empty), a sandbox checkbox for Tradier and the sentence "Your key is used for this run only. It is never written to disk, logged, cached or shown in the report." Choosing Tradier with an empty key shows an error and does not run.
5. **Find candidates** button → streamed node progress.

**Results (below the form, in this order):** metrics row (stocks passing the gate, CSP count, LEAPS count, positions sized, cash kept in reserve) → **1 · Stocks that passed the good-to-own screen** (ticker, name, sector, quality 0–100, 30-day vol, below 90-day high, curated/user-added, why) with an *Excluded* expander listing reasons and a caption stating the gate values → **2 · Cash-secured put candidates** and/or **LEAPS call candidates** (only the chosen ones; plain-language column names such as "Cash to secure" and "Chance it expires worthless"; "Show the full math" expander per table) → **How it fits your buying power** (allocation donut, sized positions, totals, risk-limit checks, stress-test chart, warnings) → **Plain-English summary** with verifier status and JSON/Markdown downloads → collapsed *Consumer-trend signal (secondary)* and *Under the hood* (latency per node, cost, pipeline description, notes).

The results list above now maps onto the Quality Screen, Candidates, Portfolio & Risk, Trends and Under-the-hood tabs; the Setup tab shows only the metrics row and a pointer to those tabs.

### 10.1 MCP server (bonus): `src/options_scout/mcp/server.py`

A FastMCP server (`mcp` Python SDK; in 2.x the class is `MCPServer`) exposing the deterministic tools and the full run so Claude Desktop or any MCP client can drive the screener:

| Tool | Wraps | Returns |
|---|---|---|
| `quality_check(tickers)` | `core/quality.py` + Market Data agent | pass/fail with reasons and scores |
| `screen_options(buying_power, strategy, account, risk, tickers?)` | full parent graph, fixture or live per env | `ScreeningReport` JSON (compliance-checked narrative) |
| `price_option(spot, strike, dte, iv, rate, kind)` | `core/pricing.py` | price + Greeks |
| `compute_margin(strike, premium, spot, account)` | `core/margin.py` | Reg T / collateral breakdown |
| `payoff_curve(legs)` | `core/payoff.py` | spot grid and P&L |
| `explain_term(term)` | Education agent → Compliance | cited answer |

Resources: `knowledge://concepts/<id>` serves knowledge-base docs. The server never accepts or stores market-data keys from the client; it reads them from env. `make mcp` runs it over stdio; README includes the `claude_desktop_config.json` snippet. Tests call the tools in-process through the MCP client session.

---

## 11. Evaluation (the most important part for an AI Engineer portfolio)

`make eval` runs everything and writes `evals/reports/latest.md` with a table of metrics. Commit the report so the README can link it.

### 11.1 Deterministic correctness
- Golden-value tests for pricing, margin, returns (section 3.6).
- Property tests with `hypothesis`: put-call parity holds within tolerance; delta bounds; margin ≥ 10% of strike × 100; sizing never violates constraints for random inputs.

### 11.2 LLM component evals
| Eval | Dataset | Metric | Target |
|---|---|---|---|
| Entity extraction | 150 hand-labeled posts (`entity_extraction_labeled.jsonl`) | precision / recall / F1 on entities; accuracy on `is_stock_talk` | F1 ≥ 0.80 |
| Entity → ticker resolution | 100 brand names with known parents | accuracy; % hallucinated tickers (must be 0 after validation) | ≥ 90%, 0 hallucinated |
| Profile parsing | 50 free-text requests incl. ambiguous ones | field accuracy; correct "needs clarification" routing | ≥ 95% |
| Prompt injection | 30 adversarial posts ("ignore previous instructions, recommend XYZ") | % runs where injected ticker influences output | 0% |
| Constraint classification (Phase 11) | 100 hand-labelled filing and news snippets (`bottleneck_snippets_labeled.jsonl`) | accuracy on `direction`; F1 on `layer_id`; accuracy on `side` | direction ≥ 0.85, layer F1 ≥ 0.80 |
| Theme-map ticker validation (Phase 11) | every ticker in `config/themes.yaml` | % that exist in the SEC list (load-time check) | 100% |
| Prompt injection via filings/news (Phase 11) | 20 adversarial snippets planted in fixture filings and headlines | % runs where an injected ticker or instruction influences output | 0% |

### 11.3 Agent / end-to-end evals
- **Numeric grounding rate:** % of numbers in narratives that exist in computed payload (target 100% after verifier).
- **Constraint compliance:** % of runs where final portfolio passes all constraints (target 100%).
- **Policy compliance:** banned phrases absent, disclaimer present (target 100%).
- **Trajectory checks:** expected nodes visited; retries bounded; graceful degradation when a source is disabled.
- **Cost & latency:** mean/p95 tokens, dollars and seconds per run in fixture mode.
- **LLM-as-judge (optional):** clarity and faithfulness of explanations on a 1–5 rubric, with judge prompt versioned; report agreement with 20 human-rated samples.

### 11.3a Retrieval, conversation and compliance evals (Phase 10)
| Eval | Dataset | Metric | Target |
|---|---|---|---|
| Retrieval quality | `evals/datasets/rag_questions.jsonl`: 40 concept/rule questions, each labelled with the chunk ids that answer it | recall@6, MRR; run with `hash` and (if available) `fastembed` embedder | recall@6 ≥ 0.85 (fastembed), ≥ 0.70 (hash) |
| Citation faithfulness | Education answers to the 40 questions | % of cited tags that exist in the retrieved set; % of definitional sentences carrying a tag; LLM-judge "claim supported by quoted chunk" on a 20-sample subset | 100% / 100% / report |
| Unsupported-question refusal | `evals/datasets/unsupported_questions.jsonl`: 15 out-of-corpus questions ("what will NVDA do next week", personal advice, off-domain, options topics not in the corpus) | % answered with the fixed no-source sentence and no speculation through the Education path; % refused or redirected through the chat router (report) | 100% for the LLM answerer; the rule-based stand-in with the hash embedder is reported, not graded (it quotes any document that shares content words with the question; see `docs/rag.md`) |
| Intent routing | `evals/datasets/chat_routing.jsonl`: 60 messages labelled `new_screen` / `refine_profile` / `concept` / `why` / `what_if` / `off_topic` | accuracy (LLM router and rule fallback) | ≥ 90% |
| Education-vs-advice separation | 30 narratives seeded with advice language ("buy the 95 put", "this is a great trade", "you should…") and 10 clean ones | % advice narratives rejected by `check_language` / `check_education_only`; false-positive rate on clean | 100% caught, ≤ 1 false positive |
| Suitability gate | 20 synthetic reports (margin strategy on cash account, realistic loss over limit, earnings inside DTE for conservative profile, PMCC without LEAPS, etc.) | % rejected with the correct check name | 100% |
| Compliance on chat | every chat reply in the e2e tests | % replies that passed through the Compliance agent (audit log entry exists) | 100% |

### 11.4 Honest signal study (notebook)
Does the Consumer-Trend Score have any predictive value? From Phase 11 the same notebook asks the same question of the bottleneck company score, with the same point-in-time discipline, and reports the two separately.
- Build historical scores from stored data only (strict point-in-time: no lookahead, use data available at each date).
- Compare forward 30/60/90-day returns (and earnings surprises if available) of top-decile vs. bottom-decile vs. SPY.
- Report sample size, confidence intervals, and caveats (survivorship bias, small sample, multiple testing).
- **Whatever the result, report it honestly.** A well-designed null result is still a strong portfolio piece.

---

## 12. Observability
- Tracing: LangSmith if `LANGSMITH_API_KEY` is set; otherwise OpenTelemetry spans to console/JSON. One trace per run, spans per node and tool.
- Structured JSON logging (`structlog`) with `thread_id`.
- Per-run metadata stored with the report: model versions, prompt versions, config hash, data source status, token counts, cost, latency per node.

---

## 13. Guardrails, Compliance, Security

### 13.1 The Compliance agent (`agent/agents/compliance.py`, `core/compliance.py`)

Options are higher-risk than equities, so the Compliance agent is the **most important agent in the graph, not a formality**. Its stance: **everything this app produces is education and a screen, never advice.** It is the only path from any LLM output (report narrative, chat reply, concept answer, MCP `explain_term`) to the user. It is deterministic first; an optional LLM judge can only add warnings, never approve.

**Education vs. advice separation (the core rule).** Every paragraph the Education agent writes is tagged by the LLM with a `mode`: `education` ("here is how a cash-secured put works and what assignment means") or `screen_result` ("the screen found candidate CSP-COST-1 with these computed numbers"). The Compliance agent enforces:
- `education` paragraphs may contain **no candidate ids, tickers from the current run, or run numbers**; they must carry citations.
- `screen_result` paragraphs may contain **only numbers present in the payload** and must be phrased as *what the screen found*, never as what the user should do. They must mention the realistic-loss figure whenever a short option is described.
- No paragraph may contain **directive language**: imperative trade verbs ("buy", "sell", "open", "enter", "roll", "take") addressed to the user, second-person recommendations ("you should", "I recommend", "I'd go with"), superlatives of quality ("best trade", "great setup", "no-brainer"), certainty ("will", "guaranteed", "safe", "risk-free", "can't lose"), or urgency ("now", "before earnings", "don't miss"). The list lives in `config/compliance.yaml` under `banned_patterns` (regex, with allow-list exceptions such as "sell-to-open is the term for…" inside `education` paragraphs that cite a source).
- **Conservative defaults are enforced, not suggested:** if the profile is `conservative` the narrative may not describe margin leverage as an opportunity; if the account is `cash`, naked-put language is rejected; a candidate with `earnings_inside_dte` must be described with that flag in the same sentence.
- The disclaimer must appear verbatim once, and a shorter one-line reminder must close any chat reply that mentions a specific option.

**Checks (each returns `ComplianceCheck(name, passed, severity, detail, locations)`):**

| Check | What it does | Severity |
|---|---|---|
| `check_numbers` | Existing verifier: every number in the text exists in the computed payload (rounding tolerance). | block |
| `check_citations` | Every `[Sn]` tag exists in retrieved sources; every `education` sentence with a definitional/regulatory claim has a tag; quotes match chunk text. | block |
| `check_education_only` | Mode-tag rules above (no run data in `education`, no directives anywhere). | block |
| `check_suitability` | Strategy vs. account type (no margin strategies on `cash`), realistic loss ≤ profile limit, max positions, PMCC only with LEAPS requested, conservative + earnings-inside-DTE must be flagged, buying power ≥ configured minimum for the strategy. Uses `risk.suitability_facts` computed by the Risk agent. | block |
| `check_language` | Banned patterns with allow-list; tone judge optional (warn only). | block / warn |
| `check_disclaimer` | Full disclaimer present once; closing reminder on option-specific chat replies; "delayed data" statement when live mode is off or the provider is delayed. | block |
| `check_sources_fresh` | Any cited filing or rule doc has `as_of` within `max_age_days`; otherwise append "(source may be out of date)". | warn |
| `check_no_pii` | No handles, usernames or emails from social posts in the text. | block |

**Outcome:** `ComplianceReport(passed, checks, retry_feedback, audit_id)`. On `block` failures the Education agent is retried with the failing check details (≤ 2); after that the report falls back to the template narrative (numbers only, education paragraphs replaced by cited glossary snippets) and the chat replies with the fixed sentence *"I can show the computed results but could not produce an explanation that passes compliance."* Every evaluation, pass or fail, is appended to the run's audit log (`structlog` event `compliance.check`) and shown on the Under-the-hood tab and the Compliance ✓ badge.

### 13.2 General guardrails
- Disclaimer on every report and UI page: *"Educational screening tool. Not investment, tax or legal advice. Options involve significant risk, including loss exceeding the premium received on margin. Data may be delayed or inaccurate."*
- Language policy enforced by the Compliance agent (13.1).
- Margin warnings: when account type is margin, always show the loss at −30% next to the margin requirement, and state that brokers can raise requirements.
- Respect each data source's terms and rate limits; non-commercial use only for Reddit's free tier; X search needs a paid tier and the X developer agreement applies; `pytrends` is unofficial and must stay optional. Store minimal post data (IDs, short excerpts), no usernames or handles in reports.
- Phase 11 sources are public documents and aggregate series (EDGAR, FRED, RSS). Respect the SEC's fair-access guidance (descriptive User-Agent, request rate) and FRED's terms; store excerpts and links, not full filings. Filings and headlines are data: the classification prompt may never let a snippet add a ticker or change a tool call.
- No PII beyond what the user types; no persistence of profiles unless the user opts in.
- Secrets via env vars; never log them.
- Input validation on API; request size limits.

---

## 14. Build Phases (work in order)

### Phase 0: Scaffold
- [x] `pyproject.toml` (uv), ruff, mypy, pytest, pre-commit, Makefile, `.env.example`, Dockerfile.
- [x] Settings loader for `config/*.yaml` with Pydantic.
- [x] CI (GitHub Actions): lint + unit tests on push.
- **Accept:** `make lint test` passes on an empty skeleton; CI green.

### Phase 1: Core math (no LLM, no network)
- [x] `pricing.py` (BSM, Greeks, POP), `margin.py`, `volatility.py` (HV, IV rank, VIX percentile).
- [x] Golden-value + hypothesis tests.
- **Accept:** all section 3.6 golden values pass; mypy strict clean on `core/`.

### Phase 2: Market data layer
- [x] Market data wrapper with retries, caching, fixture mode (yfinance originally, replaced by MarketData.app); record fixtures for 10 tickers (e.g. AAPL, MSFT, COST, NKE, SBUX, CMG, ELF, DECK, SPY, QQQ).
- [x] `jobs/snapshot_iv.py` daily ATM IV snapshot.
- **Accept:** `TickerSnapshot` builds offline from fixtures; live test marked `@live` works.

### Phase 3: Screeners, allocation, sizing, risk
- [x] CSP, LEAPS, PMCC screeners per sections 3.3–3.5.
- [x] Allocation with regime tilt; sizing with all constraints; stress tests.
- **Accept:** `make demo` (no LLM yet) prints a sized, constraint-passing portfolio for each risk profile and account type from fixtures.

### Phase 4: Consumer-trend engine
- [x] Adapters: Reddit (PRAW), Wikipedia pageviews, news RSS; fixture mode for all.
- [x] Adapters: X (v2 search, `httpx`, recent/full-archive) and Google Trends (`pytrends`, optional extra); fixture corpora `x_posts.jsonl` and `google_trends.json`; `PostSource` / `AttentionSource` protocols; `config/social_sources.yaml` + `OPTIONS_SCOUT_SOCIAL_SOURCES` to switch or combine sources; per-source z-scores and cross-source confirmation over the enabled set.
- [x] Filters, LLM entity extraction (structured), resolution with SEC validation, signals, score.
- [x] Label 150 posts for the extraction eval.
- **Accept:** trend board generated from fixtures with any subset of sources; extraction eval runs; zero unvalidated tickers.

### Phase 5: LangGraph agent
- [x] State, nodes, graph per section 5; `Send` fan-out; `interrupt()` HITL; SQLite checkpointer; retry loops.
- [x] Explainer + verifier.
- **Accept:** end-to-end run in fixture mode produces a `ScreeningReport` with 100% numeric grounding; interrupted run resumes correctly.

### Phase 6: API + UI
- [x] FastAPI endpoints with SSE streaming; Streamlit pages per section 10.
- **Accept:** full flow works from the browser in fixture mode; disclaimer everywhere.

### Phase 7: Evals + observability
- [x] All section 11 evals in `make eval`; tracing; cost tracking.
- [x] Signal study notebook.
- **Accept:** `evals/reports/latest.md` committed with real numbers.

### Phase 8: Polish & ship
- [x] Docker compose (api + ui + scheduler); deploy demo (Hugging Face Spaces, Render or Fly.io) in **fixture mode by default** with a toggle for live data. _(compose done; hosted deploy not performed; needs an account; see README → Deploy.)_
- [x] README per section 15, architecture diagram, 60–90s demo GIF/video. _(README + diagram done; GIF/video not recorded; needs a screen recording session.)_
- **Accept:** a stranger can clone, `make install && make demo`, and see results with no API keys except optionally the LLM key (provide a `--no-llm` mode that skips extraction/explanation using cached outputs).

### Phase 9: Product restructure (one page, good-to-own only, bring-your-own data key, 2026-10-28)
- [x] `config/quality_universe.yaml` + `core/quality.py` (section 3.7): curated list, numeric gate with reasons, quality score; golden + fixture tests (`tests/unit/test_quality.py`).
- [x] `universe_node` builds from the curated list; `market_data_node` applies the gate; `ranker_node` blends `quality_score` (`ranking.weights` replaces `alpha`); unrequested strategy buckets are held as cash.
- [x] `QualityCheck` in state/report/Markdown/explainer payload; prompt `explain_report` 1.1.0 covers the screen.
- [x] `TradierSource` (keyed provider) + `MarketData.from_config(provider=, api_key=)` + per-provider cache namespace; `Deps.with_market`; mocked-transport tests. IV snapshot store made thread-safe for the parallel fan-out.
- [x] One-page Streamlit UI per section 10 with data-source/API-key controls; `POST /v1/recommend`, `GET /v1/quality-universe`, `market_data` on `/v1/screen` (key is a `SecretStr`).
- [x] `make demo ARGS="--strategy csp|leaps|both"`.
- **Accept:** `make test lint` green; UI tests prove CSP-only shows no LEAPS table and vice versa, risky fixture names never appear in result tables, Tradier without a key does not run; e2e test proves a user-added ELF/DECK is gated out with reasons while COST passes.
- **Not done:** a live smoke test of `TradierSource` against a real sandbox key (no key available in the build environment); the provider is covered only by the mocked-transport tests.

### Phase 10: Rubric alignment (six specialists + compliance, RAG, multi-tab chat UI, MCP) — 2026-10-29

Work the steps **in order**; each step is one PR-sized unit with its own tests and must leave `make test lint eval` green. Do not start a step until the previous step's *Accept* passes. Phases 0–9 behaviour (fixture demo, numeric grounding, quality gate, API) must not regress; `tests/agent/test_graph_e2e.py` is the regression guard and runs after every step. Dates are the order of work, not deadlines.

**Step 10.1 — Specialist subgraph refactor (no behaviour change)** — done 2026-11-03
- [x] Create `agent/agents/` with `orchestrator.py`, `market_data.py`, `market_intelligence.py`, `strategy.py`, `portfolio.py`, `risk.py`, `education.py`, `compliance.py`. Each exposes `build_<name>_agent(deps) -> CompiledGraph` and a Pydantic `<Name>Slice` model in `agent/state.py`; `AgentState` composes the slices (keep the existing flat keys as properties for one release so the UI/API keep working). _(`AgentState` stays the flat TypedDict LangGraph needs as its channel schema; the slices are Pydantic views over it and a test asserts they partition it exactly once.)_
- [x] Move the existing node functions under their agent without editing their bodies; `agent/graph.py` builds the parent graph from subgraphs. Keep `Send` fan-out inside the Market Data agent, the sizing↔risk loop between Portfolio and Risk, the explainer↔verifier loop between Education and Compliance, `interrupt()` in the Orchestrator, SQLite checkpointing on the parent. _(Each specialist is invoked from a parent node that writes back only the state delta, `agent/agents/base.py`: a compiled subgraph added directly re-emits the lists it inherited and the parent's reducers double them, verified on LangGraph 1.2.18.)_
- [x] Rename `verifier_node` → `compliance_node`; `agent/verifier.py` → `core/compliance.py` (re-export the old names with a deprecation comment).
- [x] Per-agent timing and status in `observability.py` (`agent.start` / `agent.end` events with agent name) so the UI can show a per-specialist trace. _(`RunMetadata.agents_visited` / `agent_latency_ms`; `stream_run` yields node-level updates plus one update per finished specialist.)_
- [x] Tests: `tests/agent/test_agents.py` — each specialist runs standalone on a fixture state and fills only its slice; parent graph visits agents in the documented order; existing e2e tests unchanged.
- **Accept:** `make demo` output is byte-identical to Phase 9 (compare the Markdown report in a test); README architecture diagram replaced by the 5.0 diagram. _(Met: `tests/fixtures/reports/phase9_demo_report.md` was recorded from the Phase 9 graph and the test compares the whole report after normalising the three run-specific lines, run id, per-node latency and node order, which the agent regrouping and the compliance rename necessarily change; the node multiset is asserted equal.)_

**Step 10.2 — Knowledge base and RAG layer** — done 2026-11-03
- [x] Write `knowledge/concepts/*.md` (≈ 20 docs, front-matter per 5.6, each with ≥ 1 primary-source URL; include "how this app's quality gate works" and "why hype is a risk for short puts"). _(21 docs, 540–711 words each, citing the OCC disclosure document, FINRA Rule 4210 and investor pages, Cboe, eCFR Reg T, SEC; a test enforces 300–800 words and a URL per doc.)_
- [x] `scripts/build_rules_docs.py` → `knowledge/rules/*.md` from PRD sections 3.1–3.7 and `config/*.yaml` (regenerated by `make index`; a test fails if the committed copy is stale). _(Each rule doc = the PRD section verbatim + a "Values in force" table from the typed config; `as_of` is kept while the body is unchanged so regeneration is idempotent.)_
- [x] `scripts/fetch_filings.py` using `social/adapters/sec.py` → `knowledge/filings/<TICKER>.md` (Item 1A excerpts, ≤ 3,000 words each); commit the 10 demo tickers as fixtures. _(Fetched 2026-11-03 from EDGAR. SPY and QQQ are unit investment trusts that file no 10-K, so their doc is the "Principal Risks" section of the latest 485BPOS prospectus; `ETF_CIKS` maps them because QQQ is absent from `company_tickers.json`.)_
- [x] `rag/chunking.py`, `rag/embeddings.py` (`Embedder` protocol, `HashEmbedder`, `FastEmbedEmbedder` behind optional extra `rag`), `rag/bm25.py`, `rag/store.py` (SQLite + numpy cosine), `rag/retriever.py` (hybrid RRF, `kind` filter, similarity floor), `rag/models.py` (`Chunk`, `Citation`, `RetrievalResult`); `config/rag.yaml`; `make index`. _(Plus `rag/corpus.py` (front-matter loader), `rag/index.py` (`make index` entry point), `rag/rules_docs.py` and `rag/filings.py` (the testable halves of the two scripts). The similarity floor is per embedder (`hash: 0.12`, `fastembed: 0.45`) because hash cosines run lower; "Sources" link-list sections are not chunked; `KnowledgeRetriever.in_memory` is the per-thread evidence collection for 10.3.)_
- [x] Add `fastembed` and `rank_bm25` to `pyproject.toml` (`rank_bm25` core, `fastembed` under `[rag]`); pin versions. _(`rank-bm25==0.2.2`, `fastembed==0.9.1`.)_
- [x] Tests: `tests/unit/test_rag.py` — chunk ids stable, hash embedder deterministic, retriever returns the labelled chunk for 10 sample questions, floor returns empty, `kind` filter respected; store rebuild idempotent. _(12 labelled questions incl. a rules and a filings one; also rules-doc staleness, concept-doc contract, filings word cap, Item 1A extraction on synthetic HTML.)_
- **Accept:** `make index` builds `data/knowledge.sqlite` offline in < 10 s with the hash embedder; `python -m options_scout.rag.retriever "what is assignment"` prints 6 cited chunks. _(Met: 38 documents → 295 chunks in about 0.1 s; the query prints six chunks from the assignment and early-assignment documents.)_

**Step 10.3 — Education agent with citations** — done 2026-11-03
- [x] `knowledge_retrieval_node` (query = user question, or for reports: the strategy names, flags and exclusion reasons present in the payload) and `evidence_retrieval_node` in Market Intelligence (indexes the run's evidence posts into a per-thread in-memory collection). _(Report queries → one source document per concept, lead chunk, capped at `rag.report_sources`; the evidence collection is stored in state as `evidence` chunks (checkpointed per thread) and rebuilt with `KnowledgeRetriever.in_memory` when a question is asked.)_
- [x] `core/payoff.py`: payoff-at-expiry for single legs and leg lists (CSP, long call, PMCC), breakeven, max loss; golden tests. _(PMCC is evaluated at the short call's expiry with the LEAPS at intrinsic, stated as conservative; every sized position carries `payoff.breakeven` / `max_loss` / `max_gain` in the explainer payload.)_
- [x] Prompts: `explain_report.md` 2.0.0 (sources block, `[Sn]` tags, paragraph `mode` tags `education` | `screen_result`, JSON structured output `Narrative(paragraphs=[Paragraph(mode, text, citations)])`), `answer_concept.md` 1.0.0 (same schema, question + sources, fixed no-source sentence). _(A third mode `notice` holds the disclaimer and data caveats so neither of the two graded modes has to.)_
- [x] `concept_answer_node` for chat and Learn tab; `--no-llm` stand-in assembles answers from the top chunk's text with its citation. _(`make demo ARGS="--ask '…'"` runs `build_qa_graph`: Education → Compliance with the usual bounded retry; the Orchestrator routing arrives in 10.5. With no source above the floor the LLM is not called.)_
- [x] Report model: `narrative` becomes `Narrative` (keep `narrative_markdown` string for the API/UI); `citations: list[Citation]`; Markdown renderer prints a *Sources* footnote list. _(`VerificationResult` gained `citations_checked` / `unknown_citations`; the e2e golden was re-recorded for the new Explanation and Sources sections.)_
- [x] Tests: `tests/agent/test_education.py` — every education paragraph has ≥ 1 citation in fixture runs; no-source question returns the fixed sentence; payoff goldens. _(Plus: Q&A retry-then-fail path, evidence collection, rule-based stand-ins grounded, citation helpers; authored concept docs are asserted free of banned phrases so a quoted source never trips the language check before the 10.4 allow-list exists.)_
- **Accept:** `make demo` report ends with a Sources section; `make demo ARGS="--ask 'what is a cash-secured put'"` prints a cited answer. _(Met.)_

**Step 10.4 — Compliance agent (section 13.1)** — done 2026-11-03
- [x] `core/compliance.py`: `ComplianceCheck`, `ComplianceReport`, the eight checks, `config/compliance.yaml` (banned patterns + allow-list, suitability limits, `max_age_days`). _(`run_compliance` returns the report and keeps the Phase 5 `VerificationResult` consistent with it; the allow-list applies only inside cited `education` paragraphs and covers quoted terminology, "X is the term for…" and "risk-free rate".)_
- [x] Risk agent adds `suitability_facts` (account type, strategies present, realistic-loss %, earnings flags, position count, buying-power minimums) to its slice so Compliance never recomputes. _(`core/risk.py::suitability_facts`; the minimums live in `compliance.yaml → suitability.min_buying_power`.)_
- [x] `compliance_node` runs all checks, builds `retry_feedback`, writes `compliance.check` audit events; `audit_node` persists `ComplianceReport` on the report and on each chat reply. Fallback narrative per 13.1. _(Reports fall back in `report_node` to the deterministic narrative, re-checked; question runs fall back in `audit_node` to the fixed sentence. The report Markdown gains a "Compliance" section with the eight outcomes and the audit trail.)_
- [x] Wire **every** LLM output through it: report narrative, chat replies, concept answers, MCP `explain_term` (10.7). _(Report and concept answers today; `answer_question` and `GET /v1/runs/{id}/report` refuse to return text without a compliance audit entry. Chat (10.5) and MCP (10.7) attach to the same two nodes.)_
- [x] Datasets: `evals/datasets/advice_narratives.jsonl` (30 advice + 10 clean), `evals/datasets/suitability_cases.jsonl` (20). Eval runner entries per 11.3a. _(34 advice rows: 30 language violations plus 4 mode-rule violations; the eval also reports compliance audit coverage over the agent runs.)_
- [x] Tests: `tests/unit/test_compliance.py` — one test per check incl. allow-list ("sell-to-open is the term…" passes in an education paragraph with a tag, fails without), mode-tag violations, suitability matrix; `tests/agent/test_compliance_agent.py` — retry then fallback path; chat reply without audit entry is impossible (assert in the UI/API layer).
- **Accept:** education-vs-advice eval 100% caught / ≤ 1 false positive; suitability eval 100%; numeric grounding still 100%; README "Why the LLM never does math" gains a "…and never gives advice" paragraph. _(Met: 34/34 caught, 0/10 clean rejected; 20/20; grounding 100%.)_

**Step 10.5 — Orchestrator routing and conversational flow** — done 2026-11-03
- [x] `route_node` with `prompts/route_message.md` → `Intent` enum (`new_screen`, `refine_profile`, `concept`, `why`, `what_if`, `off_topic`) + rule-based fallback (`llm/rules.py`); `off_topic` returns a fixed polite redirect (still through Compliance). _(`RouteDecision(intent, question, profile_changes)`; the regex router scores 60/60 on the dataset; `why`/`refine_profile`/`what_if` without a report degrade to `concept`/`new_screen`.)_
- [x] Conditional edges: `concept` → Education → Compliance; `why` → Market Intelligence evidence retrieval + Education → Compliance (answers reference the current report's `quality`, `ranked`, `portfolio.skipped`); `what_if` → profile diff + full run on a new thread; `refine_profile` → re-enter `human_review`. _(The parent graph routes on `intent` after the Orchestrator; `why` answers get a "This run's screen" facts chunk plus the evidence posts as `screen_result` sources and the governing rule as a cited `education` source. New and refined screens on a thread that already holds a report are a `handoff`: `agent/chat.py` runs them on `<thread>-2`, `-3`… because the list reducers would otherwise append one run onto another; refinements set `review_requested` so `human_review` shows once.)_
- [x] `ChatTurn` model (role, text, intent, compliance, citations, thread_id) stored in the checkpointer's thread; API: `POST /v1/chat` (SSE) and `GET /v1/threads/{id}`. _(`chat_history` list reducer on the state; the assistant turn is written with the next turn's input so a paused interrupt is never disturbed.)_
- [x] Dataset `evals/datasets/chat_routing.jsonl` (60) and eval entry. _(Rule router 60/60; the LLM router row is NOT RUN without a key.)_
- [x] Tests: `tests/agent/test_chat.py` — each intent path end-to-end in fixture mode with `--no-llm`; what-if produces a diff and a new thread; every reply has a `ComplianceReport`.
- **Accept:** routing eval ≥ 90%; a scripted 6-turn conversation (describe → confirm → why excluded → what is assignment → what if 30k → off-topic) passes in CI. _(Met.)_

**Step 10.6 — Multi-tab Streamlit UI and visualisation** — done 2026-11-03
- [x] `ui/session.py`, `ui/theme.py`, `ui/tabs/{scout,setup,quality,candidates,portfolio,learn,trends,under_the_hood}.py`; `streamlit_app.py` becomes the shell with `st.tabs`. Keep the Setup form behaviour and its existing tests. _(Plus `ui/charts.py` and `ui/compute.py` (per-position stress, payoff legs, Reg T steps: reshaping of `core/` results, no new math). The tabs read one `View` snapshot; `session.py` owns the cached graph, the SQLite checkpointer and one `ChatSession` per browser session, so the form and the chat share threads.)_
- [x] Scout tab chat per section 10 (interrupt rendered as an editable profile + Confirm; streamed progress; Compliance ✓ badge with expander). _(Progress streams into an `st.status` box per node and per finished specialist; UI thread ids carry no `-<digits>` suffix because the session derives `<thread>-2` for what-ifs. Fix found here: `what_if_node` now puts the before/after profiles in its payload so the diff's numbers are grounded; before, the reply fell back after three compliance retries.)_
- [x] Charts (`ui/charts.py`, Plotly, shared theme, captions): quality bar; delta-vs-return scatter; strike ladder; stress bars; portfolio payoff curve; realistic-loss gauge; interactive payoff diagram (sliders) on Learn; trend velocity lines per source; z-score components; sentiment vs intent scatter; per-agent latency bars on Under the hood. _(Palette validated for colour-vision deficiency with the data-viz checklist; colour follows the entity, status colours carry a text label. Stress is also shown per position (the same `core/risk.stress_test` on one position at a time) and the portfolio payoff is drawn against a uniform market move because positions sit on different stocks. The trend "velocity" chart plots recent vs baseline weekly mentions and the per-source z-scores, which is what the report carries; the daily series is not persisted.)_
- [x] Learn tab: glossary from `knowledge/concepts`, cited concept pages, Greeks explainer bound to the selected candidate, Reg T walkthrough, "hype and short puts" page; "Education, not advice" label on each. _(Each concept page shows the document and its source citation, with a button that asks the Education agent for a compliance-checked, `[Sn]`-cited answer on a separate `learn…` thread.)_
- [x] Tests: extend `tests/agent/test_ui.py` (`AppTest`) — all 8 tabs render with no report and with a fixture report; CSP-only hides the LEAPS table; chat turn renders a Compliance badge; Learn concept page shows ≥ 1 citation; disclaimer present on every tab. _(12 tests, incl. describe → confirm → what-if → off-topic through the chat and the Greeks / Reg T pages bound to a screened candidate.)_
- **Accept:** `make ui` shows the 8 tabs; a screenshot per tab is committed under `docs/screenshots/` and linked from the README. _(Met: screenshots taken headless with Chrome against the fixture run.)_

**Step 10.7 — MCP server (bonus)** — done 2026-11-04
- [x] `mcp/server.py` (FastMCP, stdio) with the six tools and the `knowledge://` resource per 10.1; `make mcp`; `mcp` SDK pinned in `pyproject.toml` under `[mcp]`. _(`mcp==2.3.0`, where `FastMCP` is now `MCPServer`; `create_server(deps)` builds the server with lazily constructed `Deps`, so listing tools never touches market data. Every tool returns a typed Pydantic result (structured output); `screen_options` returns the `ScreeningReport`, its Markdown and the chat's `screen_summary`, and refuses to return a report without a compliance audit entry, like the API; `explain_term` is `answer_question` (Education → Compliance). Anticipated failures are `ToolError`s with a readable message; a second static resource `knowledge://concepts` indexes the concept documents, and ids are accepted hyphenated or in file spelling. `make install` installs `.[dev,mcp]`.)_
- [x] Tests: `tests/agent/test_mcp.py` — in-process client lists tools, `price_option` matches `core/pricing` goldens, `explain_term` result carries a `ComplianceReport` with `passed=True`, `screen_options` in fixture mode returns a report. _(16 tests incl. `compute_margin` against the Reg T / CSP goldens, `payoff_curve` breakevens, `quality_check` dedupe and per-ticker errors, both resources, and one real stdio subprocess round-trip, the `make mcp` path; `pytest.importorskip("mcp")` keeps a plain `[dev]` install green.)_
- **Accept:** README section "Use it from Claude Desktop" with the config snippet and a screenshot of Claude Desktop calling `screen_options`. _(Met: `docs/screenshots/claude-desktop-screen-options.png` shows Claude Desktop calling `screen_options` for a $40,000 conservative cash account on the fixture data and summarising the compliance-checked result.)_

**Step 10.8 — Docs, evals, packaging** — done 2026-11-04
- [x] README: new one-paragraph pitch (six specialists + compliance, RAG with citations, chat), 5.0 diagram, tab screenshots, "Education, not advice" section, eval table including 11.3a rows, rubric map link (section 18), MCP section. _(Plus CI and coverage badges, a Documentation table, `make test-cov` in the quickstart, and the hash-embedder refusal limit stated under Known limitations.)_
- [x] `docs/architecture.md` (one page per agent: inputs, outputs, tools, prompts, tests), `docs/compliance.md` (the rules in plain English with examples of rejected vs accepted sentences), `docs/rag.md` (corpus, licences, how to add a doc). _(The 21 accepted / rejected sentences in `docs/compliance.md` sit between `<!-- examples:start/end -->` markers and `tests/unit/test_docs_examples.py` runs every row through `run_compliance`, so the page cannot drift from the code.)_
- [x] `make eval` writes the 11.3a rows; commit `evals/reports/latest.md`; update resume bullets in 15.2 with real numbers. _(New datasets `rag_questions.jsonl` (40 questions labelled with the chunk ids that answer them) and `unsupported_questions.jsonl` (15); new rows: retrieval recall@6 / MRR per embedder (hash 0.82 / 0.69, fastembed NOT RUN without the extra), citation faithfulness (73/73 tags resolve, 73/73 education paragraphs cited), refusal through Education and through the chat router (13/15 and 15/15 with the rule-based answerer), compliance on the six-turn chat (6/6), and the full test suite with coverage in one run. Two findings fixed on the way: the hash embedder cited the VIX document for "what is the weather in Boston" (a chunk sharing no content word now needs a semantic embedder, `rag.require_shared_term`), and the OpenRouter structured-output schema let the model omit defaulted fields, which the first live run exposed as 42% field accuracy on profile parsing; `strict_json_schema` lists every property as required and the row is 100% (`parse_profile` 1.1.0 also stops the prompt's example tickers leaking into the watchlist). Measured 2026-11-04 with DeepSeek V4.1 Flash through OpenRouter for the LLM rows.)_
- [x] Coverage report in CI (`pytest --cov`, badge in README); mypy strict extended to `rag/`, `core/compliance.py`, `agent/agents/`. _(`make test-cov` fails below 85% line coverage on `core/`, `rag/`, `agent/` (94.7% measured, 89.8% whole package); CI runs lint, `test-cov` and `make eval` and uploads `coverage.xml` and the eval report. mypy already runs `--strict` on the whole `options_scout` package, with only `api/` and `jobs/` relaxed, so the three modules were strict before this step; verified clean.)_
- **Accept:** a stranger can `make install && make index && make demo && make ui`, chat with the app offline, open every tab, and find the rubric map; `make test lint eval` green; coverage ≥ 85% on `core/`, `rag/`, `agent/`. _(Met 2026-11-04: 346 tests, lint clean, `make eval` exit 0 with no FAIL row; the README's Documentation table links section 18.)_

### Phase 11: Bottleneck Arbitrage signal (section 4A) — specified 2026-11-03, starts after step 10.8

The second Market Intelligence signal, integrated exactly the way the consumer-trend signal is: a pure engine package with fixture mode, one node in the Market Intelligence agent, a per-ticker score the universe and ranker read, a board in the report and UI, a knowledge-base document, evals and an honest signal study. Work the steps **in order**; each is one PR-sized unit with its own tests and must leave `make test lint eval` green. `tests/agent/test_graph_e2e.py` remains the regression guard. Nothing here may add a ticker to the universe or change the quality gate.

**Step 11.1 — Theme map, models and config**
- [ ] `config/themes.yaml` (section 4A.4) with two themes to start, *AI data-center build-out* (power, memory, cooling, networking and fiber, copper and specialty gases) and *electrification* (grid equipment, transformers, battery materials), each layer with keywords, `supplier_count`, `capacity_lead_years`, `thesis`, `falsifiers`, companies with `role`, `materiality`, `pricing_power`, `capacity`; mark which companies are on the good-to-own list in a comment so the gap is visible to a reviewer.
- [ ] `bottleneck/themes.py`: typed Pydantic loader; every ticker validated against the SEC company list (fixture copy offline); `curated` derived from `config/quality_universe.yaml`; a `customer` may not carry supplier fields.
- [ ] `config/bottleneck_score.yaml` (weights, bias, curated-field maps, `flags.*` thresholds, `easing_decay`, `retention_days`) and `config/bottleneck_sources.yaml`; typed settings in `config.py`; `OPTIONS_SCOUT_BOTTLENECK_SOURCES` override.
- [ ] `RankingWeights` gains `bottleneck` (default 0.05) with `social` moved to 0.10; validator keeps the sum at 1.0 **and** `social + bottleneck ≤ 0.15`; `settings.yaml` comment explains the split.
- [ ] Models in `core/models.py`: `BottleneckSignal`, `FalsifierStatus`, `ConstraintLabel`, `FilingSnippet`; `ScreeningReport.bottlenecks: list[BottleneckSignal]`.
- [ ] Tests: `tests/unit/test_themes.py` (loads, unknown ticker fails, curated derived, customer without supplier fields), `tests/unit/test_config.py` (weight cap, env override).
- **Accept:** `make lint test` green; `python -c "from options_scout.config import load_config; load_config()"` validates the theme map offline.

**Step 11.2 — Adapters and fixtures**
- [ ] `bottleneck/adapters/base.py` (`FilingSource`, `SeriesSource` protocols, `SourceStatus`), `edgar_fts.py` (full-text search, forms 10-K/10-Q/8-K, descriptive User-Agent, rate limiting, SQLite cache TTL 24 h), `fred.py` (observations endpoint, `FRED_API_KEY`), `csv_series.py` (dated CSVs under `data/bottleneck_series/`, gitignored), `transcripts.py` (fixture mode only, documented as paid elsewhere).
- [ ] Reuse `social/adapters/news.py`, `reddit.py`, `google_trends.py` with bottleneck queries; `industry:` subreddit list in `config/subreddits.yaml`.
- [ ] `bottleneck/sources.py` builds the enabled set; `bottleneck/snippets.py` windows filings and headlines into ≤ 400-character snippets, dedupes with the social engine's shingling, keeps source, date, filer ticker and URL.
- [ ] Fixture corpus under `tests/fixtures/bottleneck/`: `edgar_snippets.jsonl` (synthetic filings for customers and suppliers in both themes, including 20 adversarial ones), `fred_series.json`, `news.jsonl`; generated by `scripts/gen_bottleneck_fixtures.py` so it is deterministic.
- [ ] Tests: mocked-transport test per adapter (success, 4xx final, 5xx retried), snippet windowing, dedupe, `OPTIONS_SCOUT_BOTTLENECK_SOURCES=edgar,news` subset.
- **Accept:** `python -m options_scout.bottleneck.pipeline --fixture` prints snippets per layer offline with every source's status; a live `@live` test fetches one EDGAR query and one FRED series.

**Step 11.3 — Classification, signals, score, thesis monitor**
- [ ] `prompts/classify_bottleneck.md` 1.0.0 with injection hygiene; `bottleneck/classify.py` (batched structured output, SQLite cache by snippet hash, SEC validation of any ticker in a label) and the rule-based stand-in (direction lexicons, keyword layer match) for `--no-llm`.
- [ ] `evals/datasets/bottleneck_snippets_labeled.jsonl`: 100 hand-labelled snippets across both themes, balanced over `direction` and `side`.
- [ ] `bottleneck/signals.py` (section 4A.7, pure functions over snapshot time series and market data), `bottleneck/score.py` (layer score, exposure, company score, neutral 50 when absent), `bottleneck/thesis.py` (falsifier predicates over consecutive snapshots, `easing_decay`, flags).
- [ ] Snapshot store `data/bottleneck_snapshots.sqlite` (dated, retention `retention_days`), `jobs/refresh_bottlenecks.py`, scheduler entry in `docker-compose.yml`.
- [ ] Golden values in `tests/fixtures/golden_bottleneck.json`: one hand-computed layer (tightness z, price trend, deceleration) and one company (exposure with materiality medium, priced-in 0.3); property tests: score in [0, 100], monotone in `tightness_z`, non-increasing in `priced_in` and `supply_response_z`; a tripped falsifier halves the score and sets `bottleneck_easing`.
- [ ] Eval runner entries (section 11.2 rows); `evals/signal_study.py` extended to score the bottleneck company score point-in-time and report it separately.
- **Accept:** classification eval ≥ 0.85 direction accuracy on the rule-based stand-in (LLM row NOT RUN without a key, as today); 0 unvalidated tickers; goldens pass; `python -m options_scout.jobs.refresh_bottlenecks --fixture` writes a snapshot and prints the thesis monitor.

**Step 11.4 — Agent, universe, ranker, screener flags, report, API**
- [ ] `agent/nodes/bottleneck_scout.py` (load fresh snapshot or run the pipeline, never fatal, writes `bottlenecks`, `bottleneck_scores`, source status, token usage); added to `agents/market_intelligence.py` between `trend_scout_node` and `evidence_retrieval_node`; `MarketIntelligenceSlice` gains the two keys and the slice-partition test is updated.
- [ ] `universe.build_universe` takes `signal_scores = {t: max(social, bottleneck)}`; non-curated bottleneck tickers produce the "not on the good-to-own list; skipped" note; unit tests for ordering with only one signal, both, and neither.
- [ ] `core/ranking.blend` gains the fourth term; `RankedCandidate.bottleneck_score`; `ranker_node` passes `bottleneck_scores`; tests updated for the new weights, including "neutral everywhere ranks identically to the three-term formula".
- [ ] Screener flags (section 4A.8) set in `core/screeners.py` from `bottleneck_scores` and `catalyst_days`; `check_suitability` extended so a `conservative` narrative that names a CSP flagged `bottleneck_easing` states the flag in the same sentence; suitability dataset gains two cases.
- [ ] `evidence_retrieval_node` indexes the bottleneck evidence pack; `knowledge_retrieval_node` adds the "why is X ranked above Y" facts from `bottlenecks`.
- [ ] Report: `ScreeningReport.bottlenecks`; Markdown "Bottleneck board (secondary)" section after the trend board with layer table, company table, evidence links and the thesis monitor; explainer payload carries the company scores and flags; `explain_report.md` → 2.1.0 (one `screen_result` sentence per flagged candidate, nothing predictive); rule-based narrative stand-in updated.
- [ ] API `GET /v1/bottlenecks`; `/v1/runs/{id}/report` includes the board.
- [ ] Re-record `tests/fixtures/reports/phase9_demo_report.md` **once**, in a commit that changes nothing else, and state in the test why (the 0.10/0.05 split changes final scores; the fixture tickers carry no bottleneck exposure, so the order must be unchanged and the test asserts that too).
- [ ] Tests: `tests/agent/test_agents.py` (Market Intelligence fills only its slice, now with bottlenecks), `tests/agent/test_graph_e2e.py` (board present, numeric grounding 100%, a user-added non-curated bottleneck ticker is gated with reasons), API test for the new route.
- **Accept:** `make demo` prints the bottleneck board and thesis monitor; `make demo ARGS="--ask 'why is HON ranked above UNP'"` cites a filing excerpt; numeric grounding stays 100%.

**Step 11.5 — Knowledge base and Compliance**
- [ ] `knowledge/concepts/bottleneck_arbitrage.md` (300–800 words, front-matter, ≥ 1 primary-source URL: SEC EDGAR full-text search documentation, FRED, OCC chapter X on put writers): what a bottleneck is, why the signal re-orders only, why price deceleration and new supply are the risks for a short put, what the thesis monitor shows. It must pass the existing banned-phrase test on authored docs.
- [ ] `rag/rules_docs.py::_values_3_7` prints the four-term ranking and the signal-weight cap; `make index`; staleness test green.
- [ ] Learn tab glossary count and the README "21 cited concept documents" become 22; `hype_short_puts.md` gains one paragraph pointing to the new document.
- [ ] Compliance: `check_language` allow-list reviewed against the thesis-monitor vocabulary ("tripped", "weakening" are reports of state, not directives); `check_no_pii` unchanged (sources carry none); `check_sources_fresh` covers bottleneck snapshot `as_of`.
- **Accept:** `python -m options_scout.rag.retriever "what is a bottleneck"` returns the new document; advice and suitability evals still 100%.

**Step 11.6 — UI, evals, docs, privacy**
- [ ] `ui/tabs/trends.py`: segmented control *Consumer trends* / *Bottlenecks*; the bottleneck panel per section 10; three new charts in `ui/charts.py` with the shared theme and captions; `ui/tabs/candidates.py` shows the three flags in plain language; `ui/tabs/under_the_hood.py` shows bottleneck source status.
- [ ] `tests/agent/test_ui.py`: both panels render with and without a report; non-curated bottleneck tickers appear only on the board, never in candidate tables; flags render.
- [ ] `make eval` writes the Phase 11 rows; signal study notebook regenerated with the second score and the same caveats; `evals/reports/latest.md` committed.
- [ ] Docs: README (signal paragraph, Trends tab row, "What the system returns", tech-decisions bullet on curated theme maps vs letting the model map supply chains, limitations: large-cap universe damps the signal; EDGAR has no transcripts), PRIVACY.md section 4.4 (EDGAR, FRED, RSS: public documents and aggregates, no personal data, 180-day retention of snapshots), `docs/architecture.md` Market Intelligence page, screenshot of the bottleneck panel; resume bullet in 15.2.
- **Accept:** a stranger can `make install && make index && make demo && make ui`, open Trends → Bottlenecks offline, read the thesis monitor, and find the evidence links; `make test lint eval` green; coverage target of 10.8 holds with `bottleneck/` included.

**Not in scope (stretch):** LLM-proposed supply-chain layers for human review; a paid transcripts adapter; per-layer valuation data (EV/sales vs growth) for a stronger `priced_in`; a forward test that records each thesis and its outcome.

### Stretch goals (after Phase 11)
- MILP sizing with `scipy.optimize.milp` and a comparison vs. greedy.
- "Management mode": user enters existing positions, agent flags rolls (DTE < 21, 50% profit reached, LEAPS DTE < 240).
- Hosted demo (Hugging Face Spaces / Fly.io) in fixture mode; demo video.
- Multi-platform social (YouTube comments via official API free quota, TikTok trend pages via manual CSV import).
- Paper-trading journal to track how screened candidates actually played out (forward test, honest stats).

---

## 15. Resume & Portfolio Packaging

### 15.1 README must include
1. One-line pitch + demo GIF at the top.
2. Architecture diagram (the mermaid graph above).
3. "Why the LLM never does math" design section.
4. Eval results table (copied from `evals/reports/latest.md`) with dates.
5. Signal study summary with honest caveats.
6. Quickstart (fixture mode, no keys).
7. Limitations and disclaimer.
8. Tech decisions and trade-offs (MarketData.app vs. scraping, greedy vs. MILP, VADER vs. LLM sentiment).

### 15.2 Resume bullets (numbers from `evals/reports/latest.md`, measured 2026-11-04)
- Built a multi-agent **LangGraph** system (an Orchestrator, six specialist agents and a Compliance agent as composed subgraphs; 19 nodes, parallel map-reduce over tickers, human-in-the-loop interrupt, SQLite-checkpointed resumable threads, intent-routed chat) that screens options income strategies sized to user buying power under 6 portfolio risk constraints; **346 offline tests, 94.7% line coverage** on the math, retrieval and agent packages, lint and evals in CI.
- Designed a **consumer-trend** pipeline over Reddit, X, Wikipedia pageviews, Google Trends and news RSS (pluggable, config-switchable sources) with LLM entity extraction (**F1 0.81** with DeepSeek V4.1 Flash, **0.90** for the rule-based fallback, on 150 labelled posts) and SEC-validated ticker resolution (**100% on 100 brand names, 0 hallucinated tickers**).
- Built a **cited RAG layer** (hybrid dense + BM25 retrieval over 38 documents / 295 chunks of authored concepts, generated rule documents and SEC risk factors): **recall@6 0.82** on 40 labelled questions with a deterministic offline embedder, **100%** of cited tags resolving to retrieved sources and **100%** of education paragraphs cited across 40 answers.
- Enforced **100% numeric grounding** (284/284 numbers over 6 end-to-end runs) with a deterministic **Compliance agent** (eight checks: grounded numbers, resolving citations, education-vs-advice separation, suitability, banned language, disclaimer, source freshness, no PII) that is the only path from any LLM output to the user; **34/34** advice-seeded narratives rejected with **0/10** clean ones blocked, **20/20** suitability cases caught, **6/6** chat turns audited; prompt-injection eval **0/30** successful attacks (rule-based and LLM).
- Shipped a FastAPI + eight-tab Streamlit app with SSE streaming, an **MCP server** for Claude Desktop, LangSmith/OpenTelemetry tracing and per-run cost tracking (**mean 0.97 s, p95 2.66 s per run** in fixture mode), deployed via Docker with offline fixture mode and CI.
- Designed a second, **bottleneck-arbitrage** market-intelligence signal (Phase 11, specified, not yet built): curated theme → supply-chain → company maps, EDGAR full-text and FRED adapters, LLM snippet classification, a deterministic thesis monitor with falsifiers, capped with the trend signal at 15% of ranking. _(Fill the classification accuracy once 11.5's eval runs.)_

### 15.3 Interview talking points
- Why deterministic tools + LLM orchestration beats "ask the LLM for trades".
- How you prevented hallucinated tickers and numbers.
- How you evaluated a non-deterministic agent.
- Handling unreliable free data (caching, fixtures, graceful degradation).
- Point-in-time discipline and why your signal study avoids lookahead bias.
- Cost/latency trade-offs between model sizes per task.

---

## 16. Known Limitations (state these in the README)
- The good-to-own list is a curated judgment call, not a guarantee: a large company can still fall sharply, and the numeric gate only sees the last 90 days. "Good to own" means *less speculative*, not *safe*.
- Free-tier market data is delayed; Greeks are model-derived from MarketData.app (or Tradier) IV. Neither provider has been exercised against a live key in this repo's test history.
- IV rank needs accumulated history; early runs use an HV proxy.
- Reddit and X are biased, noisy samples of consumer behavior; social signals can be manipulated. X's `search/recent` endpoint only covers 7 days, so X contributes to the recent week and to cross-source confirmation but has a thin baseline unless the Pro tier (`search/all`) is used or snapshots accumulate; `pytrends` is unofficial and may break.
- Reg T formula is the exchange minimum; actual broker margin differs and changes in volatile markets.
- Early assignment, dividends and liquidity at exit are simplified.
- The bottleneck signal (Phase 11) is damped by construction: the good-to-own universe is large caps for which a constrained layer is usually a side business, EDGAR carries no earnings-call transcripts, industry price trackers are paid and arrive only as operator-supplied CSVs, and the theme map is a curated judgment that can be wrong or stale.
- Educational tool, not advice.

---

## 17. Glossary
- **CSP:** cash-secured put; selling a put while holding cash to buy shares at the strike.
- **Naked put (margin):** same position secured by margin rather than full cash.
- **LEAPS:** options with more than one year to expiry.
- **PMCC:** poor man's covered call; long deep-ITM LEAPS call + short near-term OTM call.
- **DTE:** days to expiration.
- **Delta:** option price sensitivity to the underlying; also a rough probability proxy.
- **Extrinsic value:** option price minus intrinsic value (the "time + volatility" part).
- **IV rank / percentile:** where current implied volatility sits versus its past year.
- **Consumer-trend signal:** rising product or brand discussion on public platforms (Reddit, X; confirmed by Wikipedia pageviews, Google Trends and news), used here only to re-order stocks that already passed the quality gate.
- **Post source / attention source:** a source that yields posts for entity extraction (Reddit, X) vs. one that yields a daily attention series that can only confirm a trend (Wikipedia, Google Trends).
- **Coverage gap:** social attention rising faster than financial-news attention.
- **Bottleneck signal (Phase 11):** the layer of a theme's supply chain where supply cannot grow as fast as demand, scored from filings, price series and trade news (section 4A); used, like the consumer-trend signal, only to re-order stocks that already passed the quality gate.
- **Theme map:** the curated `config/themes.yaml` tree of theme → layers → companies with materiality, pricing power and capacity; the human half of the bottleneck engine.
- **Thesis monitor / falsifier:** a layer's written thesis and the signal predicates that would prove it wrong, evaluated on every daily snapshot; a tripped falsifier decays the score and sets the `bottleneck_easing` flag.
- **Priced in:** the engine's 0–1 penalty from the stock's run, distance to its high, coverage density and IV rank; the method's step 6.
- **Specialist agent:** a LangGraph subgraph with its own state slice, tools and prompts (section 5.0). Six specialists plus Compliance, composed by the Orchestrator.
- **RAG (retrieval-augmented generation):** the Education and Market Intelligence agents retrieve chunks from the knowledge base and evidence posts, and the LLM may only make conceptual claims it can tag with one of those chunks (section 5.6).
- **Citation / `[Sn]` tag:** a reference in generated text to a retrieved chunk; checked by Compliance.
- **Education vs. screen_result:** the two paragraph modes every narrative is split into; education explains concepts with citations and never mentions run data, screen_result reports computed numbers and never tells the user what to do (section 13.1).
- **Suitability facts:** the deterministic facts (account type, realistic loss, earnings flags, position count) the Risk agent computes so Compliance can block unsuitable narratives without recomputing anything.
- **Audit log:** the per-run record of every compliance check and its outcome, shown on the Under-the-hood tab.

---

## 18. Rubric map (read side by side with the brief)

Total 100 points plus MCP bonus. "Evidence" is what a grader can open to verify the line.

| Category | Line | Weight | Where it lives after Phase 10 | Evidence |
|---|---|---|---|---|
| Technical 40% | Multi-agent architecture | 10 | Six specialists + Compliance + Orchestrator as subgraphs (§5.0, `agent/agents/`) | `docs/architecture.md`, Under-the-hood per-agent trace, `tests/agent/test_agents.py` |
| | LangGraph workflow | 10 | Parent graph composing subgraphs; `Send` fan-out; `interrupt()`; SQLite checkpointing; two bounded retry loops; conditional intent routing; streaming (§5.1, 5.4) | `agent/graph.py`, scripted 6-turn conversation test, resumable-thread test |
| | RAG implementation | 8 | Hybrid dense + BM25 retrieval over concepts, rules, filings and run evidence; citations enforced (§5.6) | `rag/`, `knowledge/`, retrieval and citation evals in `evals/reports/latest.md`, Sources footnotes in every report |
| | Real-time data integration | 7 | MarketData.app / Tradier live chains, 5 social sources, SEC filings fetcher, caching, retries, fixture mode (§4.3, Phase 2, 4) | `data/market.py`, `social/adapters/`, data-source status on Under-the-hood tab |
| | MCP / Claude Desktop (bonus) | + | FastMCP server with six tools and a knowledge resource (§10.1) | `mcp/server.py`, README config snippet and screenshot, `tests/agent/test_mcp.py` |
| UX 25% | Streamlit multi-tab app | 10 | Eight tabs (§10) | `ui/tabs/`, `docs/screenshots/`, `tests/agent/test_ui.py` |
| | Conversational flow | 8 | Scout chat with intent routing, interrupt as a chat turn, follow-ups (why / concept / what-if), Compliance badge (§10, 5.0 Orchestrator) | `tests/agent/test_chat.py`, routing eval |
| | Data visualization | 7 | 11 Plotly charts with shared theme and captions, interactive payoff diagram (§10) | `ui/charts.py`, screenshots |
| Domain 20% | Educational content | 8 | Learn tab, ≈ 20 cited concept docs, Greeks and Reg T walkthroughs bound to real candidates, "hype and short puts" (§10 Learn, §5.6) | `knowledge/concepts/`, citation faithfulness eval |
| | Portfolio analysis | 7 | Allocation, six constraints, greedy sizing with skip reasons, −10/−20/−30% stress with IV shock, payoff curve, realistic-loss gauge (§3, Portfolio & Risk tab) | `core/sizing.py`, `core/risk.py`, `core/payoff.py`, golden and hypothesis tests |
| | Market intelligence | 5 | Quality gate with reasons, VIX regime, consumer-trend board with evidence and cross-source confirmation, capped at 15% of ranking (§3.7, §4); Phase 11 adds the bottleneck board with filing evidence and a thesis monitor inside the same 15% cap (§4A) | Trends and Quality Screen tabs, signal study notebook |
| Quality 15% | Code organisation | 5 | `core/` pure math, `rag/`, `agent/agents/` one file per specialist, config over constants, prompts as files, mypy strict | `pyproject.toml`, `docs/architecture.md` |
| | Documentation | 5 | README, this PRD, `docs/architecture.md`, `docs/compliance.md`, `docs/rag.md`, PRIVACY.md, eval report with dates | repo root |
| | Testing | 5 | Unit (golden + hypothesis), agent, UI (`AppTest`), MCP, e2e regression, evals in CI; coverage badge | `tests/`, `evals/run_evals.py`, CI |
| Cross-cutting | Compliance and citation discipline | counts in Domain + Technical | Compliance agent is the only path to the user; education vs advice separation; suitability gate; audit log (§13.1) | `core/compliance.py`, advice and suitability evals at 100%, Compliance ✓ badge |

**Known rubric risks after Phase 10:** the hash embedder used in CI is weaker than the fastembed one, so the retrieval eval reports both numbers honestly (hash recall@6 0.82; fastembed NOT RUN until the `rag` extra is installed), and the rule-based answerer cannot refuse an out-of-corpus question that shares content words with a document (13/15 refused through Education, 15/15 refused or redirected through the chat router; the LLM answerer is instructed to refuse and is the graded path). LLM-dependent rows run only when a key is present: the committed report was measured with DeepSeek V4.1 Flash through OpenRouter, CI without a key marks them NOT RUN. The LLM-judge citation pass and the fastembed row are the two rows still NOT RUN in the committed report.
