# Knowledge base and retrieval (RAG)

Retrieval exists in OptionsScout AI for one reason: **every educational, goal, tax or market-intelligence claim the app makes must be traceable to a source the user can read.** Numbers still come only from computed payloads; retrieval supplies concepts, rules and evidence, never prices. This page describes the corpus, its licences, the pipeline, how the agents use it, how it is evaluated, and how to add a document. The specification is PRD section 5.6; the code is [`src/options_scout/rag/`](../src/options_scout/rag/).

## The corpus

Everything lives under [`knowledge/`](../knowledge/) as Markdown with YAML front-matter. The seven fields are mandatory and validated when the corpus loads (`rag/corpus.py`):

```yaml
---
id: cash-secured-put            # [a-z0-9][a-z0-9_-]*, unique across the corpus
title: "Cash-secured put (CSP): selling a put while holding the cash to buy the shares"
source: "OCC, Characteristics and Risks of Standardized Options, chapter X; PRD.md section 3.3"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts                  # concepts | basics | tax | rules | filings (must match the folder)
level: intermediate             # beginner | intermediate | advanced (the reading level)
as_of: 2026-11-03
---
```

| Collection | Count | What it is | Where it comes from | Licence / terms |
|---|---|---|---|---|
| `concepts/` | 37 documents, 300–800 words each | the options education the Learn tab and the Education agent teach: options basics, cash-secured puts, naked puts on margin, LEAPS, PMCC, assignment, early assignment and dividends, the four Greeks, extrinsic value, IV rank, probability OTM, Reg T margin, earnings risk, liquidity, rolling, the VIX regime, covered calls, the wheel, collars and vertical spreads (labelled *not screened by this app*), open interest vs volume, fill quality, exercise styles, expiration cycles, 0DTE risk, skew and term structure, HV vs IV, approval levels, the OCC, exit rules, the sizing debate, *why hype is a risk for short puts*, *bottleneck arbitrage: what a supply-constraint signal can and cannot do for a short put* (Phase 11: what a bottleneck is, why the signal re-orders only, why price deceleration and new supply are the risks for a short put, what the thesis monitor shows), *how this app's quality gate works* | authored in this repository | MIT with the repo. Each document **cites its primary source by URL**: the OCC's *Characteristics and Risks of Standardized Options*, FINRA Rule 4210 and investor pages, Cboe, eCFR (Regulation T), SEC. The copyrighted OCC booklet is linked, never vendored. |
| `basics/` | 28 documents, all `beginner` | investing for beginners, on-theme: what a stock and an ETF are, index funds, dividends and ex-dates, market cap, P/E, bid and ask, order types, T+1 settlement, cash vs margin accounts, compound growth, diversification, concentration risk, beta, expense ratios, emergency fund first, risk tolerance, this app's risk profiles, drawdown, the VIX, T-bills, inflation, dollar-cost averaging, rebalancing, SIPC, reading a 10-K, FIRE and safe withdrawal rates, savings rate. Each ends with a *Where this shows up in OptionsScout* section | authored here | MIT. Each cites SEC investor.gov, FINRA, TreasuryDirect, SIPC or the Bogleheads wiki by URL. |
| `tax/` | 14 documents | tax mechanics and account types for a CSP, LEAPS or PMCC writer: short-put premium taxation, assignment cost basis, wash sales and options, LEAPS holding period, exercise vs sale, qualified covered calls and the straddle rules, Section 1256 (and why SPY/QQQ options are not), Form 1099-B and 8949, short vs long term, account types for options, options in an IRA, early withdrawal, Reg T vs portfolio margin, pattern day trading. None states a rate a reader will pay; each carries the sentence *This is education, not tax advice …* | authored here | MIT. Each cites IRS Publication 550, a Tax Topic, the statute or FINRA by URL. |
| `rules/` | 10 documents | the rules in force with a *Values in force* table read from the typed config, so a "why was X excluded" or "does my goal fit" answer can cite the exact threshold: the seven screening rules (PRD §3.1–3.7) and the goal feasibility, news flag and holdings concentration rules (§3.8–3.10) | **generated** by `scripts/build_rules_docs.py` (run by `make index`) from the PRD sections and `config/*.yaml`; a test fails if the committed copy is stale | MIT with the repo |
| `filings/` | 35 documents, ≤ 3,000 words each | SEC 10-K *Item 1A Risk Factors* excerpts for 33 names of the good-to-own universe; for SPY and QQQ (unit investment trusts that file no 10-K) the *Principal Risks* section of the latest 485BPOS prospectus. A bare *Risk Factors* heading (MCD, HON) falls back to the last such heading; a ticker whose new registrant has no 10-K yet (XOM) falls back to the predecessor CIK | `scripts/fetch_filings.py` through the EDGAR adapter (`social/adapters/sec.py`), the testable half in `rag/filings.py` | SEC filings are **public domain**. The script sends the descriptive User-Agent the SEC asks for (`OPTIONS_SCOUT_CONTACT_EMAIL`) and stores excerpts and links, not whole filings. |
| runtime `evidence` | per run, in memory | the trend scout's evidence posts for the current run, indexed per thread by the Market Intelligence agent so a *why is COST ranked above WMT* answer can cite the actual posts | `agent/nodes/evidence_retrieval.py` | post excerpts only, no usernames or handles; stored snapshots are purged after 48 hours ([PRIVACY.md](../PRIVACY.md)). Reddit's free tier is non-commercial use; X and Google Trends terms apply to the live adapters. |

The committed corpus is **<!-- n:docs -->124<!-- /n --> documents and <!-- n:chunks -->1,080<!-- /n --> chunks**; `make index` builds it offline in about a third of a second with the default embedder (`evals/reports/bench.md`). Category-based filtering, which the brief asks for, is the `kind` filter (one collection) and the `level` cap (reading level) described below; the Learn tab's glossary filters on both.

## The pipeline

```
knowledge/**/*.md ──corpus.py──▶ Document ──chunking.py──▶ Chunk ──embeddings.py──▶ vector ─┐
                                                                 └──bm25.py──▶ BM25 index ───┤
                                                                                              ▼
                                                             store.py (SQLite + numpy cosine) ──▶ retriever.py (RRF) ──▶ Citation [S1]…[Sn]
```

- **Chunking** (`chunking.py`): heading-aware. A document is split at its Markdown headings, each section into windows of at most 400 tokens (≈ 300 words) with 15% overlap. A chunk id is `<doc_id>#<n>` and depends only on the document text and the parameters, so re-indexing never renumbers a citation. *Sources* / *References* sections (link lists) are not chunked. Each chunk carries its document's `kind` and `level`.
- **Embedders** (`embeddings.py`, one `Embedder` protocol): `HashEmbedder` is deterministic signed feature hashing of unigrams and bigrams (2,048 dimensions, no download, identical on every machine) and is the default for tests, CI and `make demo`. `FastEmbedEmbedder` wraps `BAAI/bge-small-en-v1.5` through `fastembed` for real semantic search (`pip install -e ".[rag]"`, about 130 MB). Both return unit vectors, so cosine is a dot product. The two share one tokenizer with a stop-word list, so a query made only of stop-words matches nothing.
- **Store** (`store.py`): one SQLite table `chunks(id, doc_id, text, meta_json, vector)`; cosine search in numpy (the corpus is small). The store remembers the embedder and the corpus fingerprint and rebuilds itself when either changes.
- **Lexical ranking** (`bm25.py`): Okapi BM25 (`rank_bm25`) over the same tokens.
- **Retriever** (`retriever.py`): a chunk is eligible when its dense cosine reaches the **similarity floor** for the embedder in use (`hash: 0.12`, `fastembed: 0.45`; hash cosines run lower), when it is in the requested `kind` (if any), when its `level` is within `max_level` (if any) and, with the lexical hash embedder, when it **shares at least one content word** with the query (`require_shared_term`, on for `hash`, off for `fastembed`). That last rule exists because a bag-of-words vector that shares no word can only clear the floor by hash collision; before it, *what is the weather in Boston* cited the VIX document. Eligible chunks are ranked by weighted **reciprocal-rank fusion** of the dense and BM25 orderings (`rrf_k: 60`, collection weights in `rag.yaml`, filings at 0.8) plus a small **title boost** (`title_boost: 0.01`, the share of the document's title head found in the query, so "what is a cash-secured put" cites *Cash-secured put (CSP)* before *The wheel*, whose body mentions the term as often), and the top `top_k` (6) become `Citation(chunk_id, doc_id, title, url, quote, kind, tag, as_of)` objects numbered `[S1]…[Sn]`.
- **Reading-level cap** (`retrieve_capped`, Phase 12): the profile's knowledge level sets a cap (`level_cap`: a beginner gets `max_level="intermediate"`). The cap is a preference, not a wall. Documents within it lead; when the best match in the corpus is above the cap (a beginner asking *what is gamma*), the above-cap hits follow in up to half of the slots, so the question is answered from the right document without that document ever being `[S1]` when an easier one matched. With nothing under the cap the uncapped result is returned.
- **Empty result**: a query with nothing eligible returns no hits. The Education agent then does not call the LLM at all and answers with the fixed sentence *"I don't have a source for that in my knowledge base."*

Settings are in [`config/rag.yaml`](../config/rag.yaml); `OPTIONS_SCOUT_RAG_EMBEDDER=hash|fastembed` overrides the embedder per run.

```bash
make index                                                   # regenerate knowledge/rules + rebuild data/knowledge.sqlite
python -m options_scout.rag.retriever "what is assignment"   # 6 cited chunks with dense and BM25 scores
python -m options_scout.rag.retriever --kind rules "why was NKE excluded"
python -m options_scout.rag.retriever --kind tax "can a short put trigger a wash sale"
python -m options_scout.rag.retriever "what is a put" --max-level beginner
OPTIONS_SCOUT_RAG_EMBEDDER=fastembed make index              # semantic embeddings (optional extra)
```

## How the agents use it

Four agents retrieve; each chooses its sources differently (`agent/nodes/knowledge_retrieval.py`, `goal_explainer.py`, `holdings_reply.py`, `tax_retrieval.py`):

| Text | Agent | Query | Sources attached |
|---|---|---|---|
| **Screening report** | Education | there is no question, so the queries are derived from the payload: the strategies screened ("what is a cash-secured put", "what is assignment", "what is a LEAPS call"…), the account type (Reg T for margin accounts), the quality-gate exclusion reasons present, the flags raised, the trend board, the regime | one document per concept, its **lead chunk** (the definition), capped at `report_sources` (6), within the reader's level cap |
| **Concept question** (`concept`) | Education | the question itself, plus the run's evidence collection | up to `top_k` chunks under the level cap |
| **Why question** (`why`) | Education | the question, the rule it is really about (the gate for exclusions, the ranking for order, the constraints for skipped positions) | `[S1]` is a synthetic *This run's screen* chunk of computed facts (gate outcomes with reasons, ranking, skipped candidates, positions) with the reserved kind `run`, which the answerers key on instead of the title, then the governing rule document, then matching evidence posts |
| **Goal reply** (`goal`) | Goal Planning | fixed queries for the concepts the plan rests on: compound growth, the app's risk profiles, FIRE and safe withdrawal rates, savings rate | `kind="basics"`, up to three chunks per query; check 9 then requires the withdrawal rate to be sourced |
| **Holdings reply** (`holdings`) | Portfolio | diversification, concentration risk, expense ratios, beta | `kind="basics"`, two chunks per query, attached to the deterministic reply |
| **Tax reply** (`tax`) | Tax & Accounts | the question as asked **and** its expansion into the documents' vocabulary ("assigned" → cost basis, "6781" → Section 1256), fused at document level (`fuse_documents`) | `kind="tax"` first, one chunk per document, `concepts` as the fallback (a bare "Reg T" is an options concept, "portfolio margin" is a tax-collection account question) |

The prompt receives the sources as a numbered block (`<source id="S1" title=… url=… kind=…>`), and the structured output is a `Narrative` of paragraphs tagged `education` (must cite) or `screen_result` (numbers only). Compliance then verifies every tag against the retrieved set (`check_citations`) and that education paragraphs carry no run data (`check_education_only`); see [compliance.md](compliance.md). The report ends with a **Sources** footnote list, the chat shows citations under each reply, the Learn tab shows each document with its source URL, and the MCP resources `knowledge://concepts`, `knowledge://basics` and `knowledge://tax` serve the same documents to Claude Desktop.

## Evaluation

`make eval` measures retrieval and its use (PRD section 11.3a) and writes [`evals/reports/latest.md`](../evals/reports/latest.md). The committed report (<!-- n:report.date -->2026-11-14<!-- /n -->). Each set has a dev split (the questions the retriever and answerer were tuned on, many reusing a document's title words) and a held-out test split (questions a beginner would ask in their own words, written by someone who had not seen the retriever):

| Eval | Dataset | Metric | Result |
|---|---|---|---|
| Retrieval quality | [`dev/rag_questions.jsonl`](../evals/datasets/dev/rag_questions.jsonl) (<!-- n:n.dev.rag_questions -->63<!-- /n --> questions) and [`test/rag_questions.jsonl`](../evals/datasets/test/rag_questions.jsonl) (<!-- n:n.test.rag_questions -->45<!-- /n -->), each labelled with the chunk ids that answer it | recall@6 and MRR, hash embedder (target ≥ 0.70) and fastembed when the `rag` extra is installed (target ≥ 0.85); document-level recall in the report | hash: held-out <!-- n:recall.hash.test -->0.47 (21/45) · MRR 0.28<!-- /n -->, dev <!-- n:recall.hash.dev -->0.83 (52/63) · MRR 0.60<!-- /n -->; fastembed: held-out <!-- n:recall.fastembed.test -->0.69 (31/45) · MRR 0.43<!-- /n -->, dev <!-- n:recall.fastembed.dev -->0.94 (59/63) · MRR 0.71<!-- /n --> |
| Citation tags resolve | Education answers to the same questions | % of cited `[Sn]` tags that name a retrieved source | held-out <!-- n:cite.tags.test -->78/78 = 100%<!-- /n -->, dev <!-- n:cite.tags.dev -->111/111 = 100%<!-- /n --> |
| Citation faithfulness | Education answers to the same questions | % of answers whose cited sentences share enough words with the chunk they cite and whose quotations occur in it (the W16 check; lexical, not a semantic judge) | held-out <!-- n:cite.faithful.test -->45/45 = 100%<!-- /n -->, dev <!-- n:cite.faithful.dev -->63/63 = 100%<!-- /n --> |
| Unsupported-question refusal | [`dev/unsupported_questions.jsonl`](../evals/datasets/dev/unsupported_questions.jsonl): <!-- n:n.dev.unsupported_questions -->15<!-- /n --> questions outside the corpus (forecasts, personal advice, off-domain) | % answered with the fixed no-source sentence through the Education path, and % refused or redirected through the chat router | <!-- n:refusal -->12/15<!-- /n --> through Education with the rule-based answerer (misses listed in the report), <!-- n:refusal.chat -->15/15<!-- /n --> through the chat router |
| Tax retrieval | [`dev/tax_questions.jsonl`](../evals/datasets/dev/tax_questions.jsonl) (<!-- n:n.dev.tax_questions -->20<!-- /n -->) and [`test/tax_questions.jsonl`](../evals/datasets/test/tax_questions.jsonl) (<!-- n:n.test.tax_questions -->20<!-- /n -->), each naming the tax document that answers it | routed to the Tax agent; expected document cited; reply passes check 11 | cited: held-out <!-- n:tax.cited.test -->14/20 = 70%<!-- /n -->, dev <!-- n:tax.cited.dev -->20/20 = 100%<!-- /n --> |

The unit tests (`tests/unit/test_rag.py`) hold the contract: stable chunk ids, a deterministic hash embedder, the labelled document in the top-k for twelve sample questions, an empty result below the floor and for questions sharing no content word, the `kind` filter and the `level` cap, an idempotent store rebuild, the document contracts (word range, a primary-source URL, no banned phrases, the basics' closing section, the tax disclaimer), the filings word cap and the staleness check on the ten generated rule documents.

## How to add a document

1. **Write it** under `knowledge/<collection>/<slug>.md` with the seven front-matter fields (`kind` must equal the folder, `level` is its reading level). Keep concepts between 300 and 800 words, cite at least one primary source by URL (in `url:` or in a closing `## Sources` section), define terms before using them, and avoid the banned language in `config/compliance.yaml`: the text will be quoted verbatim inside cited education paragraphs, and `tests/unit/test_compliance.py::test_concept_docs_pass_the_language_check_as_cited_education` scans concepts, basics and tax. A `basics/` document ends with *Where this shows up in OptionsScout*; a `tax/` document carries the tax disclaimer sentence and states no rate.
2. **Rebuild**: `make index`. The store detects the corpus change on its own, but the command also regenerates `knowledge/rules/` and prints the chunk count.
3. **Label a question** for it in `evals/datasets/dev/rag_questions.jsonl` (`question`, `kind`, `doc_id`, `relevant_chunks`); a tax document also gets a row in `tax_questions.jsonl`. Chunk ids are `<doc_id>#<n>`; `python -m options_scout.rag.retriever "<your question>"` prints them.
4. **Run** `make test` and `make eval`. The Learn tab's glossary and learning path list every document automatically by collection and level, the glossary tooltips resolve against the corpus, and the MCP resource `knowledge://<collection>/<id>` serves it.

To refresh the generated rule documents after a config or PRD change, run `make index` and commit `knowledge/rules/`. To refresh filings, run `OPTIONS_SCOUT_CONTACT_EMAIL=you@example.com .venv/bin/python scripts/fetch_filings.py [TICKER ...]` in live data mode and commit the Markdown; the test suite caps each at 3,000 words.

## Limits, stated plainly

- The hash embedder is lexical. It cannot tell "shares a word with the answer" from "answers the question", so an unsupported question that happens to share content words with a document (*which stock should I buy right now* against the collar and liquidity documents) gets a cited excerpt from that document instead of the refusal when no LLM is available to judge relevance. The eval reports this honestly (12/15); the fastembed embedder and the LLM answerer (which is instructed to refuse when the sources do not answer) are the remedy.
- The corpus is curated and on-theme. It covers investing basics, the strategies this app screens, the rules it applies and the tax mechanics of writing them, not finance in general.
- Filings are excerpts of one section of one filing and carry an `as_of` date; Compliance warns when a cited filing or rule document is older than 400 days.
- The reading-level cap is a preference: an advanced document can still be cited to a beginner when nothing easier matches, in a later slot. The vocabulary rule in the prompts is what makes the prose itself beginner-friendly in live LLM mode; in fixture mode the deterministic writer's wording does not change with the level.
- Retrieval never supplies numbers about the current run. Those come from the computed payload, and Compliance rejects any number that does not.
