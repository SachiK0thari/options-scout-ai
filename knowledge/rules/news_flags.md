---
id: rules-3-9-news-flags
title: 'Rule 3.9: News flags (News Desk agent)'
source: PRD.md section 3.9 and config/news.yaml
url: PRD.md#39-news-flags-news-desk-agent
kind: rules
level: intermediate
as_of: '2026-11-06'
---

# Rule 3.9 News flags (News Desk agent)

This document is generated from PRD.md section 3.9 and `config/news.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.9)

Logic in `core/news.py`, parameters in `config/news.yaml`. Headlines are data: they become flags on candidates and a brief per ticker, and they **never change a score or a ranking**.

1. **Calendar flags** apply to short options only (a cash-secured put or a PMCC short call; a LEAPS gets none):

| Flag | Fires when |
|---|---|
| `earnings_within_dte` | the next earnings date falls on or between the run date and the option's expiry |
| `ex_dividend_before_expiry` | PMCC short call only: an ex-dividend date falls on or between the run date and the expiry, so early assignment of the short call is possible |
| `ex_dividend_capture_window` | in addition, when that ex-dividend date is within the capture window before the expiry |

   No provider in this repo exposes ex-dividend dates, so the two ex-dividend flags fire only when a date is supplied.
2. **Headlines** are fetched per ticker over the lookback window, deduplicated by normalised title or URL (the newest copy is kept), weighted by recency as `0.5 ^ (age in days / half-life)` and marked `stale` beyond the stale threshold. A brief lists the heaviest items first, the more relevant first at equal weight, up to the per-ticker maximum.
3. **Classification** into `earnings`, `guidance`, `m_and_a`, `legal_regulatory`, `product`, `macro` or `other`, by the LLM classifier or, without a key, by keywords in a fixed priority order (guidance, macro, earnings, M&A, legal and regulatory, product). In the keyword classifier the relevance to a short-put holder follows the category: high for earnings, guidance, M&A and legal or regulatory news, medium for product news, low for macro and other. A headline that carries an instruction is labelled by the news it reports.
4. **Grounding** (compliance check 10): every quoted span in a news reply is a fetched headline, verbatim.

## Values in force (config/news.yaml)

| Parameter | Value in force |
|---|---|
| Recency half-life | 3 days (weight = 0.5 ^ (age / half-life)) |
| Stale marker | older than 7 days |
| Lookback window | headlines from the last 14 days |
| Headlines kept per ticker | 8 |
| Ex-dividend capture window | within 5 days before a short call's expiry |
| Live response cache | 30 minutes |
| Alpha Vantage NEWS_SENTIMENT | enabled |
| RSS (live fallback) | enabled |
