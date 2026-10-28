# OptionsScout AI — evaluation report

_Generated 2026-10-28 16:23 UTC · data mode `fixture` · LLM: none (rule-based stand-ins measured)_

Numbers below were measured by `make eval` on this machine. Rows marked **NOT RUN** need a live LLM key and are reported as such rather than estimated.

| Section | Metric | Result | Target | Status | Detail |
|---|---|---|---|---|---|
| 11.1 Deterministic | Golden-value + property tests (tests/unit) | 130 passed in 5.66s | all pass | **PASS** | 6.6s |
| 11.2 Entity extraction | F1 on 150 labeled posts (rule-based, no LLM) | P 0.90 / R 0.89 / F1 0.90 | F1 ≥ 0.80 | **PASS** | tp=159 fp=17 fn=20 |
| 11.2 Entity extraction | is_stock_talk accuracy (rule-based, no LLM) | 0.96 | report | **INFO** | n=159 |
| 11.2 Entity extraction | F1 (LLM extraction) | — | F1 ≥ 0.80 | **NOT RUN** | requires an LLM API key (OPENROUTER_API_KEY or ANTHROPIC_API_KEY) |
| 11.2 Resolution | Brand → ticker accuracy (100 names) | 100% | ≥ 90% | **PASS** | 0 misses |
| 11.2 Resolution | Hallucinated (non-SEC) tickers | 0 | 0 | **PASS** |  |
| 11.2 Profile parsing | Required-field accuracy (rule-based, no LLM) | 98% | ≥ 95% | **PASS** | 147/150 |
| 11.2 Profile parsing | Clarification routing accuracy (rule-based, no LLM) | 98% | ≥ 95% | **PASS** | 49/50 |
| 11.2 Profile parsing | Field accuracy (LLM parsing) | — | ≥ 95% | **NOT RUN** | requires an LLM API key (OPENROUTER_API_KEY or ANTHROPIC_API_KEY) |
| 11.2 Prompt injection | Runs where injected ticker influenced output (rule-based) | 0/30 | 0% | **PASS** |  |
| 11.2 Prompt injection | Injected ticker influence (LLM) | — | 0% | **NOT RUN** | requires an LLM API key (OPENROUTER_API_KEY or ANTHROPIC_API_KEY) |
| 11.3 Agent | Numeric grounding rate (final narrative) | 100.0% | 100% | **PASS** | 262/262 numbers over 6 runs |
| 11.3 Agent | Narratives passing verifier on first attempt | 6/6 | report | **INFO** |  |
| 11.3 Agent | Constraint compliance | 6/6 | 100% | **PASS** |  |
| 11.3 Agent | Policy compliance (banned phrases absent, disclaimer present) | 6/6 | 100% | **PASS** |  |
| 11.3 Agent | Trajectory checks (expected nodes visited, retries bounded) | 6/6 | 100% | **PASS** |  |
| 11.3 Agent | Latency per run (fixture mode) | mean 0.48s · p95 1.82s | report | **INFO** |  |
| 11.3 Agent | Cost per run | mean $0.0000 · input tokens mean 0 | report | **INFO** | llm_mode=fixture |
| 11.3 Agent | Graceful degradation with social source disabled | ok | report | **PASS** |  |
| 11.3 Agent | LLM-as-judge clarity/faithfulness (1–5) | — | report | **NOT RUN** | requires an LLM API key; 20 human-rated samples not yet collected |

## Signal study
See `notebooks/signal_study.ipynb`. With only a synthetic/fixture social corpus and no stored point-in-time history yet, no predictive claim is made: the notebook documents the methodology (point-in-time scores, forward 30/60/90-day returns vs SPY, decile spread with confidence intervals) and reports the result on the data available, which is a null/insufficient-data result until live snapshots accumulate.
