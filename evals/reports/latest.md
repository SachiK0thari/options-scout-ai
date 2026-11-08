# OptionsScout AI: evaluation report

_Generated 2026-11-07 19:33 UTC · data mode `fixture` · LLM: openrouter (deepseek/deepseek-v4.1-flash / deepseek/deepseek-v4.1-flash)_

Numbers below were measured by `make eval` on this machine. Rows marked **NOT RUN** need a live LLM key (or the optional `fastembed` extra) and are reported as such rather than estimated.

| Section | Metric | Result | Target | Status | Detail |
|---|---|---|---|---|---|
| 11.1 Deterministic | Golden-value + property tests (tests/unit) | 391 passed | all pass | **PASS** |  |
| Quality | Offline test suite (unit + agent + API + UI + MCP) | 557 passed | all pass | **PASS** | 309s |
| Quality | Line coverage on core/, rag/, agent/ (pytest --cov, same run) | 94.6% | ≥ 85% | **PASS** | whole package 92.0% |
| 11.2 Entity extraction | F1 on 150 labeled posts (rule-based, no LLM) | P 0.90 / R 0.89 / F1 0.90 | F1 ≥ 0.80 | **PASS** | tp=159 fp=17 fn=20 |
| 11.2 Entity extraction | is_stock_talk accuracy (rule-based, no LLM) | 0.96 | report | **INFO** | n=159 |
| 11.2 Entity extraction | F1 on 150 labeled posts (LLM deepseek/deepseek-v4.1-flash) | P 0.72 / R 0.91 / F1 0.80 | F1 ≥ 0.80 | **PASS** | tp=163 fp=64 fn=16 |
| 11.2 Entity extraction | is_stock_talk accuracy (LLM deepseek/deepseek-v4.1-flash) | 0.98 | report | **INFO** | n=163 |
| 11.2 Resolution | Brand → ticker accuracy (100 names) | 100% | ≥ 90% | **PASS** | 0 misses |
| 11.2 Resolution | Hallucinated (non-SEC) tickers | 0 | 0 | **PASS** |  |
| 11.2 Profile parsing | Required-field accuracy (rule-based, no LLM) | 98% | ≥ 95% | **PASS** | 177/180 |
| 11.2 Profile parsing | Clarification routing accuracy (rule-based, no LLM) | 98% | ≥ 95% | **PASS** | 59/60 |
| 11.2 Profile parsing | Knowledge-level accuracy (rule-based, no LLM) | 100% | ≥ 90% | **PASS** | 60/60 (11 requests state a level, the rest must parse to none) |
| 11.2 Profile parsing | Required-field accuracy (LLM deepseek/deepseek-v4.1-flash) | 100% | ≥ 95% | **PASS** | 180/180 |
| 11.2 Profile parsing | Clarification routing accuracy (LLM deepseek/deepseek-v4.1-flash) | 98% | ≥ 95% | **PASS** | 59/60 |
| 11.2 Profile parsing | Knowledge-level accuracy (LLM deepseek/deepseek-v4.1-flash) | 98% | ≥ 90% | **PASS** | 59/60 (11 requests state a level, the rest must parse to none) |
| 11.2 Prompt injection | Runs where injected ticker influenced output (rule-based) | 0/30 | 0% | **PASS** |  |
| 11.2 Prompt injection | Runs where injected ticker influenced output (LLM) | 0/30 | 0% | **PASS** |  |
| 11.3 Agent | Numeric grounding rate (final narrative) | 100.0% | 100% | **PASS** | 284/284 numbers over 6 runs |
| 11.3 Agent | Narratives passing verifier on first attempt | 6/6 | report | **INFO** |  |
| 11.3 Agent | Constraint compliance | 6/6 | 100% | **PASS** |  |
| 11.3 Agent | Policy compliance (banned phrases absent, disclaimer present) | 6/6 | 100% | **PASS** |  |
| 11.3 Agent | Trajectory checks (expected nodes visited, retries bounded) | 6/6 | 100% | **PASS** |  |
| 11.3a Compliance | Compliance audit coverage (report text carries a passing ComplianceReport) | 6/6 | 100% | **PASS** |  |
| 11.3 Agent | Latency per run (fixture mode) | mean 1.09s · p95 2.84s | report | **INFO** |  |
| 11.3 Agent | Cost per run | mean $0.0000 · input tokens mean 0 | report | **INFO** | llm_mode=fixture |
| 11.3 Agent | Graceful degradation with social source disabled | ok | report | **PASS** |  |
| 11.3a Compliance | Education-vs-advice separation (check_language / check_education_only / check_citations) | 34/34 advice caught · 0/10 clean rejected | 100% caught, ≤ 1 false positive | **PASS** |  |
| 11.3a Compliance | Suitability gate (correct check name per case) | 20/20 | 100% | **PASS** |  |
| 11.3a Conversation | Intent routing accuracy (rule-based router) | 100/100 = 100% | ≥ 90% | **PASS** |  |
| 11.3a Conversation | Intent routing accuracy (LLM router) | 100/100 = 100% | ≥ 90% | **PASS** |  |
| 11.3a Retrieval | Retrieval quality: recall@6 on 60 labelled questions (hash embedder, CI default) | 0.83 (50/60) · MRR 0.60 | recall@6 ≥ 0.70 | **PASS** | document-level recall 53/60; chunk misses: rag-05, rag-07, rag-11, rag-16, rag-23, rag-25, rag-26, rag-27, rag-30, rag-58 |
| 11.3a Retrieval | Retrieval quality: recall@6 (fastembed bge-small-en-v1.5) | n/a | recall@6 ≥ 0.85 | **NOT RUN** | optional extra not installed: pip install -e '.[rag]' (downloads the model) |
| 11.3a Citations | Citation faithfulness: cited [Sn] tags that exist in the retrieved set (rule-based answerer) | 103/103 | 100% | **PASS** | over 60 answers |
| 11.3a Citations | Citation faithfulness: education paragraphs carrying a citation (rule-based answerer) | 103/103 | 100% | **PASS** |  |
| 11.3a Citations | Answers to the 60 questions passing Compliance | 60/60 | 100% | **PASS** | 0 answered with the no-source sentence |
| 11.3a Citations | LLM-judge: claim supported by the quoted chunk (20-sample subset) | n/a | report | **NOT RUN** | judge pass not implemented: needs the 20 human-rated samples to report agreement against |
| 11.3a Refusal | Unsupported-question refusal: fixed no-source sentence, no speculation (hash embedder, rule-based answerer) | 12/15 | 100% (LLM answerer); report (rule-based) | **INFO** | uns-04 (which stock should I buy right now) quoted collar, liquidity, vega; uns-09 (write me a poem about puts) quoted diversification, options-approval-levels, vertical-spreads; uns-11 (what is a mortgage rate lock) quoted filing-hon, savings-rate |
| 11.3a Refusal | Unsupported questions refused or redirected when asked through the chat router | 15/15 | report | **INFO** | off_topic redirect or the no-source sentence |
| 11.3a Conversation | Compliance on chat: assistant turns carrying a passing ComplianceReport (7-turn script) | 7/7 | 100% | **PASS** | intents: new_screen, new_screen, why, concept, what_if, goal, off_topic |
| 12.3 Goal planning | Goal feasibility verdicts and FIRE numbers on 29 labelled cases (15 FIRE, five variants) | 29/29 | 100% | **PASS** | deterministic: core/goals.py on cash alone at 4% |
| 12.3 Goal planning | Goal parsing: a goal kind recognised on the 10 goal messages (rule-based) | 10/10 | 100% | **PASS** |  |
| 12.5 News desk | Headline category accuracy on 70 labelled headlines (keyword classifier) | 70/70 = 100% | ≥ 85% | **PASS** |  |
| 12.5 News desk | Headlines with an embedded instruction still labelled by content (20, keyword) | 20/20 | 100% | **PASS** |  |
| 12.5 News desk | Headline category accuracy on 70 labelled headlines (LLM classifier) | 70/70 = 100% | ≥ 85% | **PASS** |  |
| 12.5 News desk | Headlines with an embedded instruction still labelled by content (20, LLM) | 20/20 | 100% | **PASS** |  |
| 11.2 Constraint classification | Direction accuracy on 100 hand-labelled filing and news snippets (rule-based stand-in) | 94/100 = 94% | ≥ 0.85 | **PASS** | bl-007→neutral; bl-010→neutral; bl-018→neutral; bl-020→neutral; bl-026→tightening; bl-036→neutral |
| 11.2 Constraint classification | Layer macro-F1 on 100 snippets, no search hint given (rule-based stand-in) | 0.93 | ≥ 0.80 | **PASS** |  |
| 11.2 Constraint classification | Side accuracy (customer / supplier / neutral) on 100 snippets (rule-based stand-in) | 98/100 = 98% | report | **INFO** |  |
| 11.2 Theme-map validation | Tickers in config/themes.yaml that exist in the SEC company list (33) | 33/33 | 100% | **PASS** |  |
| 11.2 Prompt injection | Fixture filings/headlines with an embedded instruction that steered the label (20, rule-based) | 0/20 | 0% | **PASS** |  |
| 11.2 Constraint classification | Direction accuracy on 100 hand-labelled filing and news snippets (LLM deepseek/deepseek-v4.1-flash) | 100/100 = 100% | ≥ 0.85 | **PASS** |  |
| 11.2 Constraint classification | Layer macro-F1 on 100 snippets, no search hint given (LLM deepseek/deepseek-v4.1-flash) | 0.99 | ≥ 0.80 | **PASS** |  |
| 11.2 Constraint classification | Side accuracy (customer / supplier / neutral) on 100 snippets (LLM deepseek/deepseek-v4.1-flash) | 95/100 = 95% | report | **INFO** |  |
| 11.2 Prompt injection | Fixture filings/headlines with an embedded instruction that steered the label (20, LLM) | 0/20 | 0% | **PASS** |  |
| 12.6 Tax & accounts | Tax questions routed to the Tax agent and citing the expected document (rule-based answerer) | routed 20/20 · cited 20/20 | ≥ 90% cited | **PASS** | every question cited its document |
| 12.6 Tax & accounts | Tax replies passing Compliance (check 11: disclaimer once, no rate, no instruction) | 20/20 · disclaimer once in 20/20 | 100% | **PASS** |  |
| 11.3 Agent | LLM-as-judge | see notes | report | **INFO** | judge prompt v1.0.0 |

## Signal study
See `notebooks/signal_study.ipynb`. With only a synthetic/fixture social corpus and no stored point-in-time history yet, no predictive claim is made: the notebook documents the methodology (point-in-time scores, forward 30/60/90-day returns vs SPY, decile spread with confidence intervals) and reports the result on the data available, which is a null/insufficient-data result until live snapshots accumulate.
