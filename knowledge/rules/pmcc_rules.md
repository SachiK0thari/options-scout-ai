---
id: rules-3-5-pmcc-rules
title: 'Rule 3.5: PMCC short call rules'
source: PRD.md section 3.5 and config/screener_rules.yaml
url: PRD.md#35-pmcc-short-call-rules
kind: rules
as_of: '2026-11-03'
---

# Rule 3.5 PMCC short call rules

This document is generated from PRD.md section 3.5 and `config/screener_rules.yaml` by `scripts/build_rules_docs.py`; the values below are the ones in force for every screen this app runs.

## Specification (PRD.md section 3.5)

- DTE 30–45, call delta 0.20–0.30, expiry before the LEAPS expiry.
- **Safety rule:** short strike ≥ LEAPS strike + net debit paid for the LEAPS. Reject any pairing that fails.
- Net delta of the pair = LEAPS delta − short call delta.

## Values in force (config/screener_rules.yaml)

| Rule | Value in force |
|---|---|
| Short call days to expiry | 30–45 (fallback 21–60) |
| Short call delta | 0.2–0.3 |
| Expiry | before the LEAPS expiry |
| Safety rule | short strike ≥ LEAPS strike + net debit paid for the LEAPS (always on) |
| Net delta | LEAPS delta − short call delta |
