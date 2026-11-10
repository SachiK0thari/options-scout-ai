# OptionsScout AI: performance benchmarks

_Generated 2026-11-09 23:59 UTC by `make bench` · data mode `fixture` · LLM mode `fixture` · embedder `hash-2048` · Darwin arm64, Python 3.12.0_

Measured on this machine, offline. Fixture mode replays market data and LLM outputs, so these are the costs of the code (graph overhead, deterministic math, retrieval, compliance checks), not of a network or a model. Live mode adds the provider's latency per call; see README "Tech decisions" for the cache TTLs that bound it.

## Screens (full pipeline, six requests)

- Wall-clock per screen: mean **1.22 s**, p95 **3.15 s**, min 0.38 s, max 3.15 s
- Tokens per screen: mean 0 in / 0 out · cost per screen: mean $0.0000

| Request | Wall | Candidates | Positions | Tokens in / out | Cost | Compliance attempts |
|---|---|---|---|---|---|---|
| I have $50,000 of buying power in a margin account, balanced risk tolerance. CSPs and a few LEAPS/PMCC. | 3.15 s | 14 | 1 | 0 / 0 | $0.0000 | 1 |
| $100k cash account, conservative. Only cash-secured puts. I like COST and NKE, skip TSLA. | 0.74 s | 5 | 1 | 0 / 0 | $0.0000 | 1 |
| 250k portfolio margin, aggressive, all strategies, watchlist AAPL MSFT SPY. | 1.12 s | 14 | 2 | 0 / 0 | $0.0000 | 1 |
| Roth IRA with 40k, cautious, CSPs and LEAPS please. | 0.79 s | 14 | 0 | 0 / 0 | $0.0000 | 1 |
| I've got about 75 grand in a margin account, moderate risk, PMCC ideas plus CSPs. | 1.12 s | 14 | 2 | 0 / 0 | $0.0000 | 1 |
| $1.2M margin account, balanced. Exclude QQQ and SPY. | 0.38 s | 6 | 5 | 0 / 0 | $0.0000 | 1 |

## Latency per specialist (ms, over the six screens; an agent's retries are summed)

| Agent | Mean | p95 | Max | Share of the mean screen |
|---|---|---|---|---|
| `orchestrator_agent` | 3 ms | 4 ms | 4 ms | 0% |
| `market_intelligence_agent` | 315 ms | 1,844 ms | 1,844 ms | 27% |
| `market_data_agent` | 103 ms | 145 ms | 145 ms | 9% |
| `strategy_agent` | 288 ms | 478 ms | 478 ms | 25% |
| `news_desk_agent` | 81 ms | 91 ms | 91 ms | 7% |
| `portfolio_agent` | 87 ms | 142 ms | 142 ms | 8% |
| `risk_agent` | 77 ms | 87 ms | 87 ms | 7% |
| `education_agent` | 113 ms | 247 ms | 247 ms | 10% |
| `compliance_agent` | 91 ms | 136 ms | 136 ms | 8% |

## Slowest nodes (mean ms over the runs that visited them)

| Node | Mean | Max | Visits |
|---|---|---|---|
| `trend_scout_node` | 306 ms | 1,834 ms | 6 |
| `screener_node` | 235 ms | 427 ms | 6 |
| `knowledge_retrieval_node` | 78 ms | 202 ms | 6 |
| `market_data_node` | 45 ms | 80 ms | 6 |
| `news_fetch_node` | 31 ms | 51 ms | 6 |
| `news_classify_node` | 12 ms | 24 ms | 6 |
| `compliance_node` | 5 ms | 10 ms | 6 |
| `explainer_node` | 2 ms | 4 ms | 6 |

## Chat turns on a finished screen's thread (each through Compliance)

| Intent | Turn | Wall | Compliance | Attempts | Citations |
|---|---|---|---|---|---|
| `goal` | I want $400 a month from this account | 0.48 s | pass | 1 | 2 |
| `holdings` | 200 AAPL at 150, 10 COST at 800, 40 SPY | 0.50 s | pass | 1 | 1 |
| `news` | any news on COST and NKE? | 0.51 s | pass | 1 | 1 |
| `tax` | what happens to my taxes if one of those puts is assigned? | 0.50 s | pass | 1 | 1 |
| `concept` | what is assignment | 0.02 s | pass | 1 | 2 |

## Market-data cache (per-run cache across the six screens)

- Hits **516**, misses **110**, hit rate **82%** (the first screen is cold; TTLs in `config/settings.yaml` `cache_ttl_seconds`: 15 min for quotes and chains, 1 h for history, 24 h for earnings and dividends)

## Retrieval (knowledge base)

- Corpus: 124 documents, 1,074 chunks; index build (chunk + embed + store) **0.32 s** with the `hash-2048` embedder
- Query latency over 63 labelled questions (dense + BM25 + fusion): mean **1.2 ms**, p95 **1.7 ms**

## How to read this

- Market Data fans out one `Send` per ticker; in live mode each ticker is one quote, one chain and one history call, cached per provider namespace, so a second screen within 15 minutes pays only for the tickers the first did not touch.
- Education and the Phase 12 writers are where the LLM latency lands in live mode (one structured call per text, plus up to two Compliance retries); everything before them is deterministic.
- `make eval` reports the same latency row (11.3 Agent) beside correctness; this file is the breakdown. Re-run after changing the graph, a prompt or the retriever.
