# How the capstone brief maps onto OptionsScout AI

The capstone brief ("AI Finance Assistant: democratizing financial literacy through intelligent conversational AI") prescribes six agents, a repository layout, a `config.yaml`, a `requirements.txt`, a set of technologies and a list of deliverables. OptionsScout AI satisfies each line while keeping its own theme: *the path from "what is a stock" to "selling my first cash-secured put", with the math done for me and the risks stated.* This page is the crosswalk a grader can read side by side with the brief. The rubric-line map with evidence links is PRD section 18.

## The six agents

Eleven compiled LangGraph subgraphs are composed by [`src/options_scout/agent/graph.py`](../src/options_scout/agent/graph.py): an Orchestrator, nine specialists and a Compliance agent. The brief's six map as follows (one page per agent in [architecture.md](architecture.md)):

| Brief agent | What the brief asks | OptionsScout specialist(s) | File(s) | Reached by |
|---|---|---|---|---|
| Finance Q&A Agent | general financial education queries, RAG with source attribution | **Education**: cited concept answers over 124 documents in five collections, report narratives, the three-stage learning path, glossary tooltips, Greeks and Reg T walkthroughs bound to a real candidate | `agent/agents/education.py` | `concept` / `why` intents, Learn tab, MCP `explain_term` |
| Portfolio Analysis Agent | reviews and analyses user portfolios: total value, allocation %, expense ratios, diversification score, risk | **Portfolio** (holdings valued at the run's prices, allocation by ticker and sector, HHI diversification score, expense ratios, beta-weighted exposure, covered-call lots, concentration after assignment; allocation of buying power; greedy sizing under seven constraints) + **Risk** (constraint checks, −10/−20/−30% stress with IV shock, suitability facts) | `agent/agents/portfolio.py`, `risk.py`; `core/holdings.py`, `allocation.py`, `sizing.py`, `risk.py` | `holdings` intent, Portfolio & Risk tab, API `holdings`, MCP `analyze_holdings` |
| Market Analysis Agent | real-time market insights | **Market Data** (delayed live quotes and chains from MarketData.app or Tradier, the VIX regime, the good-to-own quality gate, the market overview strip with data age) + **Market Intelligence** (consumer-trend board over Reddit, X, Wikipedia pageviews, Google Trends and news RSS, with evidence; the bottleneck board over SEC filings, FRED series and headlines with its thesis monitor, Phase 11) | `agent/agents/market_data.py`, `market_intelligence.py` | every screen; Quality Screen, Candidates and Trends & News tabs; MCP `quality_check`, `screen_options` |
| Goal Planning Agent | financial goal setting and planning with projection algorithms, "keeping risk appetite in mind" | **Goal Planning**: income, growth and FIRE goals (lean, regular, fat, coast, barista) checked against the screened portfolio's expected yield under the risk profile's cap; verdict, three levers, four-path projection, FIRE number, coast balance, years to FI, income coverage | `agent/agents/goal_planning.py`, `core/goals.py` | `goal` intent, Goals tab, MCP `plan_goal` |
| News Synthesizer Agent | summarises and contextualises financial news | **News Desk**: per-ticker briefs from Alpha Vantage `NEWS_SENTIMENT` (RSS fallback), headlines labelled by category and relevance to a short-option holder, calendar flags on screened candidates; headlines never change the ranking | `agent/agents/news_desk.py`, `social/adapters/alphavantage_news.py`, `core/news.py` | `news` intent, every screen, Trends & News tab, MCP `news_brief` |
| Tax Education Agent | explains tax concepts and account types | **Tax & Accounts**: cited answers over the 14-document `tax` collection, illustrated with the thread's screened put (assignment basis, LEAPS holding period, wash-sale window, Section 1256 status), account chooser; never a rate the reader will pay | `agent/agents/tax.py`, `core/tax.py` | `tax` intent, Learn tab's Tax & Accounts page, MCP `explain_tax_term` |
| (not in the brief) | | **Orchestrator** (intent routing over ten intents, profile parsing, human-in-the-loop confirmation), **Strategy** (the CSP, LEAPS and PMCC screeners and the ranker), **Compliance** (eleven deterministic checks, the only path to the user) | `orchestrator.py`, `strategy.py`, `compliance.py` | every turn |

**Data flow the brief prescribes** (User Query → Workflow Router → Agent(s) → RAG Retrieval → LLM Processing → Response Generation → UI) is the parent graph: `route_node` classifies the turn into one of ten intents, the parent graph routes to the specialist(s), the specialist retrieves from the knowledge base, the LLM writes from a payload of computed numbers and numbered sources, and the Compliance agent checks the text before the UI, the API or the MCP client sees it. The one addition is that last step: no text reaches the user without a `ComplianceReport`.

## Required prototype features

| Brief | Where |
|---|---|
| Web interface for conversation | Scout tab (`ui/tabs/scout.py`): the profile-confirmation interrupt renders as an editable form inside the chat, progress streams per node, every assistant turn carries a Compliance ✓ badge; `POST /v1/chat` exposes the same session over server-sent events |
| Portfolio analysis of user input | *Your holdings* on the Portfolio & Risk tab, the `holdings` intent, `holdings` on `POST /v1/recommend` and `/v1/screen`, MCP `analyze_holdings` |
| Real-time market data lookup | MarketData.app or Tradier (bring-your-own key, per run) with cache, backoff and fixture fallback; the market overview strip states the provider and the data age |
| Plan financial goals keeping risk appetite in mind | Goals tab and the `goal` intent: the required return is compared with the expected yield the screened portfolio can produce under the profile's cap (`max_assumed_return` in `config/goals.yaml`: conservative 6%, balanced 9%, aggressive 12% a year), and the verdict names what has to change |
| Multi-turn conversations with different agents | one thread per conversation in the SQLite checkpointer; the scripted seven-turn conversation in `tests/agent/test_chat.py` visits five agents; the 100-row routing dataset covers all ten intents |
| 50–100 knowledge articles, vector indexing, category filtering, source attribution | 124 documents in five collections: 79 written articles (37 `concepts`, 28 `basics`, 14 `tax`), 35 `filings` excerpts (verbatim 10-K Item 1A risk factors from SEC EDGAR), and 10 `rules` pages generated from the PRD and config. Hybrid dense + BM25 index in SQLite, `kind` and reading-`level` filters, `[Sn]` citations enforced by Compliance ([rag.md](rag.md)) |
| Caching, rate limits, API failures, data freshness indicators | per-type TTL cache namespaced per provider, exponential backoff on transport errors and 5xx, an immediate error on 401 / 429 rather than a retry into a spent budget, fixture fallback, per-ticker error notes, the strip's data age |
| MCP server for Claude Desktop (optional) | `src/options_scout/mcp/server.py`: ten tools and three knowledge resource collections; README "Use it from Claude Desktop" |
| Demo video, 5–10 minutes | [demo-video-script.md](demo-video-script.md); the recording is step 12.10 |

## The prescribed layout and ours

The brief's tree is a flat `src/` with seven folders plus `config.yaml` and `requirements.txt`. OptionsScout keeps an installable package (`src/options_scout/`) with typed config files, which is the same structure one level deeper:

| Brief | OptionsScout | Why |
|---|---|---|
| `src/agents/` | `src/options_scout/agent/agents/` (one file per specialist) and `agent/nodes/` (one file per node) | the agents are LangGraph subgraphs; their nodes are shared building blocks, so they live beside them |
| `src/core/` | `src/options_scout/core/` (pricing, margin, screeners, quality, ranking, allocation, sizing, risk, payoff, goals, news, tax, holdings, compliance, report, models) | pure math and the compliance checks, `mypy --strict`, no I/O |
| `src/data/` | `src/options_scout/data/` (market data providers, cache, fixtures) and `src/options_scout/social/` (the consumer-trend and news adapters) | market data and social data have different terms of use and retention rules, so they are separate packages |
| `src/rag/` | `src/options_scout/rag/` with the corpus in `knowledge/` | the corpus is content, not code; it is committed next to the pipeline that indexes it |
| `src/web_app/` | `ui/` (Streamlit shell, one module per tab, shared charts and theme) and `src/options_scout/api/` (FastAPI) | the UI imports the package like any client; the API is a second client of the same graph |
| `src/utils/` | `src/options_scout/config.py`, `observability.py`, `llm/` (provider table, prompt loader, rule-based stand-ins) | named for what they do rather than "utils" |
| `src/workflow/` | `src/options_scout/agent/graph.py` (the parent graph), `agent/state.py`, `agent/chat.py` (the conversation session) | the LangGraph workflow |
| `tests/` | `tests/unit`, `tests/agent`, `tests/integration` (network, opt-in), `tests/fixtures` | 594 offline tests; coverage on `core/`, `rag/`, `agent/`, `bottleneck/` is 95.2% |
| `config.yaml` | `config/*.yaml`, one file per concern (`settings`, `risk_profiles`, `screener_rules`, `quality_universe`, `social_score`, `social_sources`, `subreddits`, `rag`, `compliance`, `goals`, `news`, `tax`, `holdings`), each loaded into a Pydantic model by `config.py`; environment variables prefixed `OPTIONS_SCOUT_` override the top-level settings | a thousand-line YAML would hide the thresholds the knowledge base cites; one file per concern keeps a diff reviewable and lets `scripts/build_rules_docs.py` publish each rule file's values |
| `requirements.txt` | `pyproject.toml` is the source of truth (pinned dependencies, extras `dev`, `mcp`, `rag`, `trends`); `requirements.txt` is **exported** from it by `make requirements` and committed for graders and plain-pip users (`pip install -r requirements.txt && pip install -e .`) | one pin list, two formats |
| `README.md` | `README.md` plus `PRD.md` (the build spec and working agreement) and `docs/` | the brief's "technical design document" is [architecture.md](architecture.md) with [rag.md](rag.md) and [compliance.md](compliance.md) |

## Technology choices the brief lists, and ours

The brief allows different technologies if the reasoning is documented. The reasoning in one place:

| Brief component | Brief's options | OptionsScout | Why |
|---|---|---|---|
| Multi-agent system | LangChain / LangGraph / CrewAI | **LangGraph** 1.2 (`StateGraph`, subgraphs, `Send`, `interrupt`, SQLite checkpointer) without LangChain chat models | LangGraph gives the typed state, the fan-out and the human-in-the-loop interrupt the design needs; provider SDKs are called directly for structured outputs and usage accounting (README "Tech decisions") |
| Language model | Google Gemini / OpenAI GPT / Claude Sonnet | **OpenRouter by default** (DeepSeek V4.1 Flash for every task, JSON-schema structured outputs), **Anthropic as the second provider** (Claude Haiku 5.5 for parsing and extraction, Claude Opus 5.5 for the narrative); fixture mode replays cached outputs and rule-based stand-ins cover every LLM step | one OpenRouter key reaches many cheap models, including Gemini models if a grader wants to try one; **no native Gemini provider** is implemented, on purpose (the provider table in `llm/client.py` has two entries and a third would duplicate the OpenAI-compatible path). The LLM has five jobs and no arithmetic, so model choice changes prose quality, never a number |
| Vector database | FAISS / Chroma / Pinecone | **SQLite + numpy cosine + BM25** (`rag/store.py`, `rag/bm25.py`), hybrid reciprocal-rank fusion | the corpus is about a thousand chunks; a dot product over a numpy array is faster than a round trip to a vector service and needs no second process. The `Embedder` protocol and the store are the two seams if the corpus ever outgrows them |
| Market data | Alpha Vantage / yFinance | **MarketData.app or Tradier** for quotes, chains and history (bring-your-own key, delayed on the free tiers); **Alpha Vantage** for news and sentiment (`NEWS_SENTIMENT`) | yFinance is an unofficial Yahoo scraper that broke and rate-limited during development; Alpha Vantage's free tier has no option chains, which this app cannot do without, so it is integrated where it is the best source (news). Both market providers run with cache, backoff and fixtures; see README "Tech decisions" and "Known limitations" |
| Web interface | Streamlit / Gradio / React | **Streamlit**, nine tabs, Plotly charts with one theme and captions; **FastAPI** beside it | the brief's default; the API exists so the same graph serves Claude Desktop, scripts and a future front end |
| State management | LangGraph / CrewAI | LangGraph checkpointer (SQLite), one thread per conversation, `chat_history` on the thread | resumable, inspectable (`GET /v1/threads/{id}`), and the interrupt needs it |

## Deliverables checklist

| Brief deliverable | Where |
|---|---|
| Architecture overview, setup, API documentation, usage examples, troubleshooting | README: "Architecture", "Quickstart", "API", "Use it from Claude Desktop", "Troubleshooting" |
| Technical design document: architecture decisions, agent communication protocols, RAG details, performance | [architecture.md](architecture.md) (decisions, protocol, performance), [rag.md](rag.md), [compliance.md](compliance.md) |
| Docker configuration, environment setup files, sample data | `Dockerfile`, `docker-compose.yml`, `.env.example`, `tests/fixtures/` (recorded market data, synthetic social corpus, cached LLM outputs, news) |
| Performance benchmarks | `make bench` → [`evals/reports/bench.md`](../evals/reports/bench.md); correctness and latency rows in [`evals/reports/latest.md`](../evals/reports/latest.md) from `make eval` |
| Test suite with 80%+ coverage | 594 offline tests; `make test-cov` fails below 85% on `core/`, `rag/`, `agent/`, `bottleneck/` (95.2% measured); CI runs lint, tests, coverage and the eval suite on every push |
| Demo video | [demo-video-script.md](demo-video-script.md); recording is step 12.10 |

## Stated on purpose: what is not built

- No brokerage connection, no order placement, no tax liability computation, no personalised tax or investment advice. Every agent ends in Compliance and every reply keeps the disclaimer.
- No native Gemini provider (see above). No voice or mobile interface; the brief's future directions (voice, mobile, Monte Carlo, social features, automated investing) are listed under README "Future directions" with what each would need.
- The bottleneck-arbitrage signal (PRD section 4A, Phase 11) is built: a second Market Intelligence board over SEC filings, FRED series and headlines with a deterministic thesis monitor, capped with the trend signal at 15% of the ranking; it earns innovation points on top of the required work.
