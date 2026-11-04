# OptionsScout AI: evaluation report

_Generated 2026-11-04 19:38 UTC · data mode `fixture` · LLM: openrouter (deepseek/deepseek-v4.1-flash / deepseek/deepseek-v4.1-flash)_

Numbers below were measured by `make eval` on this machine. Rows marked **NOT RUN** need a live LLM key (or the optional `fastembed` extra) and are reported as such rather than estimated.

| Section | Metric | Result | Target | Status | Detail |
|---|---|---|---|---|---|
| 11.1 Deterministic | Golden-value + property tests (tests/unit) | 263 passed | all pass | **PASS** |  |
| Quality | Offline test suite (unit + agent + API + UI + MCP) | 346 passed | all pass | **PASS** | 135s |
| Quality | Line coverage on core/, rag/, agent/ (pytest --cov, same run) | 94.7% | ≥ 85% | **PASS** | whole package 89.8% |
| 11.2 Entity extraction | F1 on 150 labeled posts (rule-based, no LLM) | P 0.90 / R 0.89 / F1 0.90 | F1 ≥ 0.80 | **PASS** | tp=159 fp=17 fn=20 |
| 11.2 Entity extraction | is_stock_talk accuracy (rule-based, no LLM) | 0.96 | report | **INFO** | n=159 |
| 11.2 Entity extraction | F1 on 150 labeled posts (LLM deepseek/deepseek-v4.1-flash) | P 0.71 / R 0.95 / F1 0.81 | F1 ≥ 0.80 | **PASS** | tp=170 fp=70 fn=9 |
| 11.2 Entity extraction | is_stock_talk accuracy (LLM deepseek/deepseek-v4.1-flash) | 0.96 | report | **INFO** | n=170 |
| 11.2 Resolution | Brand → ticker accuracy (100 names) | 100% | ≥ 90% | **PASS** | 0 misses |
| 11.2 Resolution | Hallucinated (non-SEC) tickers | 0 | 0 | **PASS** |  |
| 11.2 Profile parsing | Required-field accuracy (rule-based, no LLM) | 98% | ≥ 95% | **PASS** | 147/150 |
| 11.2 Profile parsing | Clarification routing accuracy (rule-based, no LLM) | 98% | ≥ 95% | **PASS** | 49/50 |
| 11.2 Profile parsing | Required-field accuracy (LLM deepseek/deepseek-v4.1-flash) | 100% | ≥ 95% | **PASS** | 150/150 |
| 11.2 Profile parsing | Clarification routing accuracy (LLM deepseek/deepseek-v4.1-flash) | 100% | ≥ 95% | **PASS** | 50/50 |
| 11.2 Prompt injection | Runs where injected ticker influenced output (rule-based) | 0/30 | 0% | **PASS** |  |
| 11.2 Prompt injection | Runs where injected ticker influenced output (LLM) | 0/30 | 0% | **PASS** |  |
| 11.3 Agent | Numeric grounding rate (final narrative) | 100.0% | 100% | **PASS** | 284/284 numbers over 6 runs |
| 11.3 Agent | Narratives passing verifier on first attempt | 6/6 | report | **INFO** |  |
| 11.3 Agent | Constraint compliance | 6/6 | 100% | **PASS** |  |
| 11.3 Agent | Policy compliance (banned phrases absent, disclaimer present) | 6/6 | 100% | **PASS** |  |
| 11.3 Agent | Trajectory checks (expected nodes visited, retries bounded) | 6/6 | 100% | **PASS** |  |
| 11.3a Compliance | Compliance audit coverage (report text carries a passing ComplianceReport) | 6/6 | 100% | **PASS** |  |
| 11.3 Agent | Latency per run (fixture mode) | mean 0.97s · p95 2.66s | report | **INFO** |  |
| 11.3 Agent | Cost per run | mean $0.0000 · input tokens mean 0 | report | **INFO** | llm_mode=fixture |
| 11.3 Agent | Graceful degradation with social source disabled | ok | report | **PASS** |  |
| 11.3a Compliance | Education-vs-advice separation (check_language / check_education_only / check_citations) | 34/34 advice caught · 0/10 clean rejected | 100% caught, ≤ 1 false positive | **PASS** |  |
| 11.3a Compliance | Suitability gate (correct check name per case) | 20/20 | 100% | **PASS** |  |
| 11.3a Conversation | Intent routing accuracy (rule-based router) | 60/60 = 100% | ≥ 90% | **PASS** |  |
| 11.3a Conversation | Intent routing accuracy (LLM router) | 60/60 = 100% | ≥ 90% | **PASS** |  |
| 11.3a Retrieval | Retrieval quality: recall@6 on 40 labelled questions (hash embedder, CI default) | 0.82 (33/40) · MRR 0.69 | recall@6 ≥ 0.70 | **PASS** | document-level recall 37/40; chunk misses: rag-07, rag-08, rag-16, rag-25, rag-26, rag-27, rag-30 |
| 11.3a Retrieval | Retrieval quality: recall@6 (fastembed bge-small-en-v1.5) | n/a | recall@6 ≥ 0.85 | **NOT RUN** | optional extra not installed: pip install -e '.[rag]' (downloads the model) |
| 11.3a Citations | Citation faithfulness: cited [Sn] tags that exist in the retrieved set (rule-based answerer) | 73/73 | 100% | **PASS** | over 40 answers |
| 11.3a Citations | Citation faithfulness: education paragraphs carrying a citation (rule-based answerer) | 73/73 | 100% | **PASS** |  |
| 11.3a Citations | Answers to the 40 questions passing Compliance | 40/40 | 100% | **PASS** | 0 answered with the no-source sentence |
| 11.3a Citations | LLM-judge: claim supported by the quoted chunk (20-sample subset) | n/a | report | **NOT RUN** | judge pass not implemented: needs the 20 human-rated samples to report agreement against |
| 11.3a Refusal | Unsupported-question refusal: fixed no-source sentence, no speculation (hash embedder, rule-based answerer) | 13/15 | 100% (LLM answerer); report (rule-based) | **INFO** | uns-04 (which stock should I buy right now) quoted liquidity, vega; uns-14 (how are option gains taxed) quoted rolling, theta |
| 11.3a Refusal | Unsupported questions refused or redirected when asked through the chat router | 15/15 | report | **INFO** | off_topic redirect or the no-source sentence |
| 11.3a Conversation | Compliance on chat: assistant turns carrying a passing ComplianceReport (6-turn script) | 6/6 | 100% | **PASS** | intents: new_screen, new_screen, why, concept, what_if, off_topic |
| 11.3 Agent | LLM-as-judge | see notes | report | **INFO** | judge prompt v1.0.0 |

## Signal study
See `notebooks/signal_study.ipynb`. With only a synthetic/fixture social corpus and no stored point-in-time history yet, no predictive claim is made: the notebook documents the methodology (point-in-time scores, forward 30/60/90-day returns vs SPY, decile spread with confidence intervals) and reports the result on the data available, which is a null/insufficient-data result until live snapshots accumulate.
