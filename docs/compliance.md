# Compliance: the rules in plain English

Everything OptionsScout AI produces is **education and a screen, never advice**. The Compliance agent ([`src/options_scout/core/compliance.py`](../src/options_scout/core/compliance.py), wired in [`agent/agents/compliance.py`](../src/options_scout/agent/agents/compliance.py)) is the only path from any text the LLM wrote to the user: the report narrative, every chat reply (concept, why, goal, holdings, news, tax, what-if, redirect), every answer on the Learn, Goals and Portfolio tabs and every MCP tool that returns text (`explain_term`, `plan_goal`, `analyze_holdings`, `news_brief`, `explain_tax_term`, the `screen_options` narrative) carry its `ComplianceReport` and an audit id. It is deterministic. An optional LLM judge could only add warnings; nothing an LLM says can approve a text. The thresholds and patterns live in [`config/compliance.yaml`](../config/compliance.yaml); the specification is PRD section 13.1.

The examples in this page are not illustrative prose: [`tests/unit/test_docs_examples.py`](../tests/unit/test_docs_examples.py) runs every sentence in the two tables below through the named check and fails if the verdict printed here is wrong.

## Two kinds of paragraph

Every writer (the Education agent, the Goal Planning explainer, the News Desk brief, the Tax & Accounts answer, the holdings reply) tags every paragraph it writes with a `mode`:

| Mode | What it is for | May contain | May not contain |
|---|---|---|---|
| `education` | "Here is how a cash-secured put works and what assignment means." | definitions, mechanics, rules, quoted from a retrieved source and tagged `[Sn]` | candidate ids, tickers from the current run, run-specific numbers, directives |
| `screen_result` | "The screen found candidate CSP-COST-… with these computed numbers." | only numbers present in the computed payload, phrased as what the screen (or the goal math, the holdings valuation, the news fetch) found | directives, superlatives, certainty, urgency; a short option without its realistic loss |
| `notice` | the disclaimer and data caveats | the fixed texts | anything else |

The separation is the core rule: an education paragraph can never quietly turn into a recommendation about this run, and a result paragraph can never invent a number or tell the reader what to do.

**The writer does not get to choose the rules by choosing the label (W16).** Every paragraph records who wrote it (`Paragraph.written_by`): `LLMClient` marks each paragraph a model wrote, live or replayed, and the field is not in the schema the model is given, so a model cannot claim to be the app. The modes of the app's own paragraphs (the deterministic writers, fixed replies, the withheld notice) are trusted. For a model's paragraphs the mode follows the content:

- A model `notice` must consist only of fixed texts: the disclaimer, the reminder *Education, not advice.*, the tax disclaimer, *I don't have a source for that in my knowledge base.* and the delayed-data sentence, written out or as their slots (`{{ disclaimer }}`, `{{ delayed_data_notice }}`), plus the sizer's warnings as `{{risk.warnings[i]}}` slots after an optional bold label. Any other notice is checked as `education` by every check: it then needs a citation and may not name the run's tickers, ids or numbers.
- Every sentence of a model `screen_result` must name something from the run: a slot, a candidate id, a run ticker, a figure (which check 1 grounds), a named part of the run's output (`citations.run_terms`: the quality screen, the trend or bottleneck board, excluded, sized, skipped, the stress test…; "screen" alone does not count) or, in a goal reply, the verdict word or FIRE variant. A sentence that names none of these is a general claim and must carry an `[Sn]` tag, which check 2 then verifies like an education sentence. A sentence that is part of one of the fixed texts ("these are screened candidates that meet the configured criteria, not recommendations") is the app's own caveat and is exempt.

## The eleven checks

Each check returns `ComplianceCheck(name, passed, severity, detail, locations)`. A **block** failure fails the text; a **warn** failure is recorded and shown but does not block. Checks 9 to 11 pass trivially on texts that are not their kind (a report or a concept answer carries no goal plan, headlines or tax facts in its payload).

| # | Check | In plain English | Severity |
|---|---|---|---|
| 1 | `check_numbers` | **Report narratives (slot mode, W14):** the writer never types a figure. It names payload fields as slots (`{{positions[CSP-…].realistic_loss\|money}}`) and `core/grounding.py` fills them in; every paragraph keeps its template. Slot filters: `money`, `pct` (implied for a field named `*_pct`), `percent`, `abs`, `count`, and `list` (a list of text items such as flags or `quality_screen.passed_tickers`, joined with commas). A digit or number word typed in a `screen_result` or `notice` paragraph fails (except the names of fixed measures listed in `grounding.literal_allow`: "30–45 DTE", "30-day realised volatility", "90-day high", "fewer than 30 IV snapshots"), as does an unknown slot, a slot into `sources` or `question`, a slot in an `education` paragraph, or text that differs from its rendered template. **Every other text (free-text mode):** each figure, parsed with its unit (`3M`, `5k`, `10x`, `%`), number words up to ninety-nine and multipliers (*double*), must match a payload value of the same kind and sign (`+3140` is not `-3140`; `40%` is not a count of 40), within a 1% rounding tolerance and no absolute tolerance. `screen_result` and `notice` figures are grounded by the run's own data only, never by the user's question or retrieved text. **Both modes:** every candidate id a `screen_result` or `notice` paragraph names must be one the run's data lists (the payload, or this app's run facts for a chat reply), so an invented contract fails; next to a dangerous label (maximum loss, realistic loss, breakeven, premium, collateral, margin, probability, annualised return; `config/compliance.yaml` → `grounding`) the nearest figure in the clause must be that label's field, of the candidate the sentence names; a percent given as a dollar label's value ("the realistic loss is 45%") fails, while one that sets the scenario ("at a 30% drop") does not. | block |
| 2 | `check_citations` | Every `[Sn]` tag must point at a source that was actually retrieved for this text; every `education` paragraph (and every demoted notice) must carry at least one tag, and so must a model's `screen_result` sentence that names nothing from the run. **Quotations (W16):** every span of twelve characters or more in double quotes, single quotes or guillemets must occur, compared as lower-case words after the language normalisation, in the text of a source the paragraph cites; a `screen_result` or `notice` may also quote the run's own data (a reason "as given"), and an elision `...` splits the quote into parts that must each occur. Quotations are read on the template, so a quoted slot (a value the app filled in) is not checked. A quoted glossary term of `allow_terms` (`"sell to open"`) names an order and is not a quotation. **Support (W16):** each cited sentence with at least four content words must share half of them (stemmed, a short stop list removed, negations kept) with the title and text of the chunk its tags name (else the paragraph's tags). This blocks citing an unrelated article; it does not catch a careful paraphrase of a falsehood, which needs the LLM judge (not run). Thresholds in `config/compliance.yaml` → `citations`. A quoted citation may not be empty. | block |
| 3 | `check_education_only` | No candidate id, run ticker or run-specific number (≥ 1,000) in an `education` paragraph (the user's own question is never run data). Any `screen_result` paragraph that names a short option (a CSP or a PMCC short call) must state that option's own realistic loss in the same paragraph: in a templated paragraph, a slot of its `realistic_loss` (a skipped candidate's `realistic_loss_per_contract`; a PMCC short call is covered by its pair's); in free text, a figure matching it, from the payload or this app's run facts. The words "realistic loss" alone, or another option's figure, state nobody's loss. Before the check, the report explainer adds each missing one as a slot and records the repair in `narrative_patches`. Every paragraph has a known mode. | block |
| 4 | `check_suitability` | Facts computed by the Risk agent, never recomputed here: no margin used in a cash account; no position's realistic loss above the profile's per-position limit; not more positions than the profile allows; no PMCC unless LEAPS were requested; buying power at or above the configured minimum for each strategy present; for a conservative profile, a candidate with earnings before expiry must be described with that fact in the same sentence; no naked-put language for a cash account; margin leverage never described as an opportunity to a conservative profile. | block |
| 5 | `check_language` | None of the banned patterns in any paragraph: **certainty** (guaranteed, risk-free, can't lose, will profit…), **directives** addressed to the reader (you should, I recommend, buy/sell/open/roll the put…), **superlatives** of quality (best trade, great setup, no-brainer…), **urgency** (don't miss, before it's too late, buy now…). Inside a *cited* `education` paragraph, quoted terminology (`"sell to open"`) and "X is the term for…" definitions are exempt, and so is the phrase "risk-free rate". | block |
| 6 | `check_disclaimer` | The full disclaimer appears exactly once. A chat reply that names a specific option must close with the one-line reminder *Education, not advice.* A report narrative must say the market data is delayed. | block |
| 7 | `check_sources_fresh` | A cited rule document, SEC filing or bottleneck evidence item (a filing excerpt, price point or headline from the board's evidence pack) older than `max_age_days` (400) is flagged "(source may be out of date)". A cited bottleneck board whose snapshot `as_of` is older than `max_snapshot_age_days` (7) is flagged "(bottleneck snapshot may be out of date)": the daily job has not re-measured the constraint. Both ages are measured against the run's data clock. | warn |
| 8 | `check_no_pii` | No social-media handles (`@name`, `u/name`, `r/name`) or email addresses from posts in the text. | block |
| 9 | `goal_narrative` | Goal replies only (Phase 12). The verdict is stated in words (*fits*, *stretch* or *does not fit*); whenever a projection figure appears the **stress path** is named beside it; no projected figure is promised (*would*, never *will reach / hit / have / grow / be worth / cover*); a FIRE reply names its variant (lean, regular, fat, coast, barista), mentions the withdrawal rate and sources it to diversified-portfolio research. `config/compliance.yaml` → `goal`. | block |
| 10 | `news_grounding` | News replies only (Phase 12). Every quoted span of twelve characters or more in a non-education paragraph must be a headline the News Desk actually fetched, compared after normalisation. A brief may summarise in its own words; it may not put words in a publisher's mouth. Cited `education` paragraphs are exempt because check 2 verifies their quotes against the retrieved chunks. | block |
| 11 | `tax_reply` | Tax replies only (Phase 12). The tax disclaimer sentence appears exactly once; no rate a reader will pay is stated ("taxed at 37%", "15% bracket"); no filing instruction is given in the imperative ("Report the sale…", "File your…"). Account-type claims live in cited education paragraphs, which check 2 covers. `config/compliance.yaml` → `tax`. | block |

## What happens on a failure

1. **A suitability failure on facts skips the rewrites.** When `check_suitability` fails with a code that describes the sized portfolio itself (`margin_on_cash`, `loss_over_limit`, `too_many_positions`, `pmcc_without_leaps`, `buying_power_below_minimum`), rewriting the prose cannot change it, so the run goes straight to the withheld path in step 4. Every other code is about wording and takes the normal retry: a flag the text must state (`earnings_unflagged_conservative`, `earnings_unknown_unflagged`, `bottleneck_easing_unflagged_conservative`, and since W6 `single_name_unstated`, `ranking_not_followed_unstated` and `account_too_small_unstated`, which require the narrative to say that the portfolio is on one stock, that higher-ranked names did not fit, or that the account is too small) or language it must not use (`naked_language_on_cash`, `leverage_as_opportunity`). The fact codes are an explicit list (`FACT_SUITABILITY_CODES`), so a new code defaults to the retry.
2. The failing checks' details are joined into `retry_feedback` and the writer that produced the text is asked to rewrite with that feedback in its prompt: the Education agent for reports and concept answers, the Goal Planning writer on a goal turn, the News Desk, the Tax & Accounts agent or the Portfolio agent on theirs. At most **two** retries (`agent.max_explainer_retries`); each retry re-enters at the writer, with the sources and the math it already has.
3. After the retries, a **report** written by a live model first keeps the model's last attempt with its failing paragraphs dropped, when every blocking failure names a paragraph and at most two paragraphs (and at most a quarter of them) fail. A dropped paragraph's section (allocation, quality screen, trends, bottlenecks, positions, risk or warnings, by the payload area its slots read) comes back as the deterministic narrative's paragraph for it when no kept paragraph covers it; otherwise deterministic paragraphs are added only where the full check still finds something missing, such as the disclaimer. At most one is added per dropped paragraph. The result is checked again and released as `narrative_source: "mixed"`, with `rules_paragraphs` and `narrative_patches` in the run metadata. Otherwise the report falls back to the deterministic template narrative, which writes every figure as a slot (the same path the model takes) and attaches cited glossary excerpts for the education paragraphs; the fallback is checked again. A **chat reply or specialist answer** is replaced by the fixed sentence *"I can show the computed results but could not produce an explanation that passes compliance."*, also re-checked.
4. **A report whose final check still fails is withheld, never released.** Its narrative becomes the fixed notice *"This screen was withheld: the sized portfolio does not suit the stated account."* followed by the reason codes and the failed check names; the sized positions and the goal plan built on them are removed; the candidate tables and the constraint checks stay, because they are computed facts. The report carries `withheld: true` and `withheld_reasons`, and the failing `ComplianceReport` stays attached and on the audit log. `GET /v1/runs/{id}` reports status `withheld` without the portfolio; `GET /v1/runs/{id}/report` answers **409** with the notice, the reason codes and the failed checks; the MCP `screen_options` tool returns an error with the same; the chat turn is the notice, which is itself checked and passes; and the Scout tab shows an assistant turn's text only when its badge passes.
5. Every evaluation, pass or fail, is appended to the run's `audit_log` and logged as a `compliance.check` event. The Under-the-hood tab shows the trail; every chat turn shows a **Compliance ✓** badge listing the eleven outcomes.

A text can therefore reach the user in exactly one state: with a passing `ComplianceReport` attached. The withheld notice is the only text a failing screen produces, and it says that the screen failed. `answer_question`, `ask_specialist`, `GET /v1/runs/{id}/report`, the chat session and the MCP server refuse to return text whose audit log did not grow in that turn.

## Accepted and rejected sentences

The sentences below are checked as a model wrote them (`written_by="model"`) against a fixed payload: one sized position `CSP-COST-2026-12-18-850P` (strike 850, premium 1,250, realistic loss 12,345), seven tickers passed and three excluded, one retrieved source tagged `[S1]`, run tickers COST and NKE. Each row names the check it illustrates; the other checks may pass or fail independently.

<!-- examples:start -->
| # | Sentence | Mode | Check | Verdict |
|---|---|---|---|---|
| 1 | CSP-COST-2026-12-18-850P met the criteria; its realistic loss is 12345. | screen_result | check_language | accepted |
| 2 | You should sell CSP-COST-2026-12-18-850P here; realistic loss 12345. | screen_result | check_language | rejected |
| 3 | CSP-COST-2026-12-18-850P is a great trade with a realistic loss of 12345. | screen_result | check_language | rejected |
| 4 | The premium is guaranteed income; realistic loss 12345. | screen_result | check_language | rejected |
| 5 | Don't miss this one: the screen found CSP-COST-2026-12-18-850P with a realistic loss of 12345. | screen_result | check_language | rejected |
| 6 | A cash-secured put obliges the writer to buy 100 shares per contract at the strike if assigned [S1]. | education | check_language | accepted |
| 7 | The order "sell to open" is how a put writer opens the position [S1]. | education | check_language | accepted |
| 8 | Sell-to-open is the term for the order a put writer places; sell the put before Friday [S1]. | education | check_language | rejected |
| 9 | The model drifts at the risk-free rate minus the dividend yield, not at an expected return [S1]. | education | check_language | accepted |
| 10 | This is a risk-free way to collect premium; realistic loss 12345. | screen_result | check_language | rejected |
| 11 | A cash-secured put on COST obliges the writer to buy the shares at the strike [S1]. | education | check_education_only | rejected |
| 12 | The 12345 realistic loss is what the collateral protects against [S1]. | education | check_education_only | rejected |
| 13 | CSP-COST-2026-12-18-850P met the criteria and collects 1250 of premium. | screen_result | check_education_only | rejected |
| 14 | CSP-COST-2026-12-18-850P met the criteria; the realistic loss at expiry after a 30% drop is 12345. | screen_result | check_education_only | accepted |
| 15 | Assignment is the process by which an option writer is selected to fulfil the obligation of an exercised contract. | education | check_citations | rejected |
| 16 | Assignment is the process by which an option writer is selected to fulfil the obligation of an exercised contract [S1]. | education | check_citations | accepted |
| 17 | Regulation T sets the exchange minimum for an uncovered put [S4]. | education | check_citations | rejected |
| 18 | The screen found CSP-COST-2026-12-18-850P with a realistic loss of about 12000. | screen_result | check_numbers | rejected |
| 19 | The screen found CSP-COST-2026-12-18-850P with a realistic loss of 12345. | screen_result | check_numbers | accepted |
| 20 | Reddit user u/kirkland_fan posted that the rotisserie chicken is back in stock. | screen_result | check_no_pii | rejected |
| 21 | A Reddit post reported that the rotisserie chicken is back in stock. | screen_result | check_no_pii | accepted |
| 22 | The power layer's thesis is weakening: its supply-response falsifier tripped since the last two snapshots, so company scores in that layer were halved and new supply is arriving. | screen_result | check_language | accepted |
| 23 | CSP-COST-2026-12-18-850P met the criteria and carries the bottleneck_easing flag (thesis weakening in its layer); its realistic loss is 12345. | screen_result | check_language | accepted |
| 24 | NKE is the pick of this screen. Put most of the account in the NKE 35 put. | notice | check_citations | rejected |
| 25 | Selling puts is how professionals earn steady income; assignment is rare and losses are small. | screen_result | check_citations | rejected |
| 26 | LEAPS calls cannot expire worthless because they are long-dated [S1]. | education | check_citations | rejected |
| 27 | The OCC states: "cash-secured puts have never produced a loss for disciplined sellers" [S1]. | education | check_citations | rejected |
| 28 | The OCC describes assignment as "the process by which an option writer is selected" [S1]. | education | check_citations | accepted |
<!-- examples:end -->

Why each rejected row fails:

- **2, 3, 4, 5, 10**: a directive ("you should"), a superlative ("great trade"), certainty ("guaranteed", "risk-free") and urgency ("don't miss") are banned in every mode.
- **22, 23** (accepted): the thesis monitor's vocabulary (*holding*, *tripped since*, *thesis weakening*, *easing*, *new supply*) reports the state of a supply constraint and matches no banned pattern; the board never says exit, sell or take profits, so no allow-list entry was needed when the Phase 11 words were reviewed.
- **7 vs 8**: inside a cited education paragraph the exact glossary terms of `allow_terms` (*sell to open*, *buy to open*, *sell to close*, *buy to close*, *buy the call*) are exempt, quoted or not. Nothing else is: no quoted span and no "X is the term for…" clause, so the imperative "sell the put before Friday" in row 8 fails even after a definition (W15).
- **Normalisation (W15)**: every pattern runs on `normalise_for_language(text)`: NFKC, zero-width and soft-hyphen characters deleted, curly quotes and dashes to ASCII, accents stripped, look-alike Cyrillic and Greek letters folded to Latin, HTML tags and Markdown emphasis removed, whitespace collapsed. "You\u00a0*should*", "guaran\u200bteed" and "Y\u043eu sh\u043euld" are caught like the plain words. A paragraph that is mostly non-Latin script, or whose function words are mostly another language's, fails as `non_english`: the product is English-only.
- **11, 12**: an education paragraph may teach what a cash-secured put is; it may not mention this run's tickers or this run's numbers, or it has become advice about this screen.
- **13**: a short option is never described without its realistic loss; the reader must see what a 30% drop costs next to the premium.
- **15, 17**: definitional claims must be traceable to a retrieved source. Row 17 cites a tag that was never retrieved.
- **18**: 12,000 is not within 1% of any payload number. The LLM may not round a loss into a smaller-sounding one.
- **20**: usernames from social posts never appear in user-facing text (see [PRIVACY.md](../PRIVACY.md)).
- **24**: a model-written `notice` that is not a fixed text is checked as `education`, and it cites nothing. (It also names a run ticker, which check 3 rejects.)
- **25**: labelled `screen_result`, but no sentence names anything from the run, so it is a general claim and needs a citation.
- **26**: the tag exists, but the cited Assignment source shares almost none of the sentence's words: it is not what the source says.
- **27 vs 28**: a quotation must occur in the cited source. Row 28 copies the source's words; row 27 puts invented words in the OCC's mouth.

## The Phase 12 checks: goal, news and tax replies

These rows are checked as chat replies (`text_kind="answer"`) against three small payloads: a **goal plan** whose verdict is *stretch* with a ten-year projection ending at 150,000 on the base path and 120,000 on the stress path (the *FIRE* rows add a lean-FIRE plan at a 4% withdrawal rate); a **news** payload holding two fetched headlines, *Costco raises membership fee for the first time since 2017* and *Nike reports quarterly results after the bell*; and a **tax** payload with the question *what if I get assigned*. The tax disclaimer sentence is the one in `config/compliance.yaml`.

<!-- phase12-examples:start -->
| # | Sentence | Mode | Check | Verdict |
|---|---|---|---|---|
| 22 | This goal is a stretch: the required return is 8.0% a year against a stress-adjusted yield of 5.2%; in 10 years the balance would reach 120000 on the stress path and 150000 on the base path. | screen_result | goal_narrative | accepted |
| 23 | On the base path the balance will reach 150000 in 10 years. | screen_result | goal_narrative | rejected |
| 24 | This goal fits; the base path would end near 150000 and the stress path near 120000. | screen_result | goal_narrative | accepted |
| 25 | This goal fits; the balance will grow to 150000 on the base path and 120000 on the stress path. | screen_result | goal_narrative | rejected |
| 26 | Lean FIRE does not fit yet: at a 4% withdrawal rate, the figure diversified-portfolio research supports, the FIRE number is 1200000; the stress path would reach 120000 and the base path 150000. | screen_result | goal_narrative (FIRE) | accepted |
| 27 | This plan fits: at a 4% withdrawal rate the FIRE number is 1200000; the stress path would reach 120000 and the base path 150000. | screen_result | goal_narrative (FIRE) | rejected |
| 28 | Costco: "Costco raises membership fee for the first time since 2017" (Reuters, 2026-11-03), a corporate action of medium relevance to a put writer. | screen_result | news_grounding | accepted |
| 29 | Costco: "Costco cuts its membership fee" (Reuters, 2026-11-03), a corporate action of medium relevance to a put writer. | screen_result | news_grounding | rejected |
| 30 | Nike reports quarterly results after the bell, so the screened put carries the earnings flag; its realistic loss is 12345. | screen_result | news_grounding | accepted |
| 31 | An earnings date inside the option's life is what this app calls "earnings inside the DTE window" [S1]. | education | news_grounding | accepted |
| 32 | If the put is assigned, the premium received lowers the cost basis of the shares [S1]. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited. | education | tax_reply | accepted |
| 33 | If the put is assigned, the premium received lowers the cost basis of the shares [S1]. | education | tax_reply | rejected |
| 34 | A short-term gain is taxed at 37% for most readers [S1]. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited. | education | tax_reply | rejected |
| 35 | Report the sale on Form 8949 and attach it to the return [S1]. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited. | education | tax_reply | rejected |
<!-- phase12-examples:end -->

Why each rejected row fails:

- **23**: no verdict word, a projection without the stress path beside it, and "will reach" promises a figure. Three problems, one rejection.
- **25**: the verdict and the stress path are there, but "will grow" is a promise; the reply has to say "would".
- **27**: a FIRE reply must name its variant ("lean") and say that the withdrawal rate comes from diversified-portfolio research, because an options-income portfolio is not the diversified portfolio that research studied.
- **29**: the quoted words are not a headline the News Desk fetched. Row 30 shows the same news paraphrased without quotation marks, which is allowed; row 31 shows a quoted phrase in a cited education paragraph, which check 2 governs instead.
- **33**: the tax disclaimer sentence is missing. It must appear exactly once, so a reply that quotes a tax document's own copy of it and adds its own is also rejected (the rule-based writer strips the quoted copy for that reason).
- **34**: "taxed at 37%" states a rate the reader will pay. The documents explain *which* rate applies (short- or long-term, Section 1256's 60/40 split) and send the reader to the IRS publication for the number.
- **35**: "Report the sale…" is a filing instruction in the imperative. The reply may explain that Form 8949 is where brokers' 1099-B figures are reconciled; it may not tell the reader to file anything.

## Suitability examples

`check_suitability` reads `SuitabilityFacts` computed by the Risk agent and the text. The reason codes, with the synthetic case in [`evals/datasets/dev/suitability_cases.jsonl`](../evals/datasets/dev/suitability_cases.jsonl) that exercises each:

| Reason code | Rejected when | Example case |
|---|---|---|
| `margin_on_cash` | `account_type == cash` and `margin_used > 0` | a margin-sized put described to a cash account |
| `loss_over_limit` | worst position's realistic loss / account value > the profile's per-position limit | 3.5% loss for a conservative profile (limit 2%) |
| `too_many_positions` | `position_count > max_positions` | nine positions, limit eight |
| `pmcc_without_leaps` | a PMCC is present but LEAPS were not requested | CSP-only request, PMCC in the text |
| `buying_power_below_minimum` | buying power below `suitability.min_buying_power` for a strategy present | a CSP described to a $2,000 account |
| `earnings_unflagged_conservative` | conservative profile, a candidate has earnings before expiry and the sentence naming it does not say so | earnings inside DTE, flag omitted |
| `naked_language_on_cash` | "naked" or "uncovered put" in text for a cash account | "the naked put collects…" |
| `leverage_as_opportunity` | conservative profile and margin or leverage described as an opportunity, boost, enhancement | "margin frees up capital to boost returns" |

`make eval` measures the gate on 20 such cases (target: the correct reason code every time), the education-vs-advice separation on 34 advice-seeded and 10 clean narratives (target: 100% caught, at most one false positive), the goal replies of 29 labelled cases, 20 tax replies under check 11 and every chat turn of the scripted conversation. The latest numbers are in [`evals/reports/latest.md`](../evals/reports/latest.md).

## How to change a rule

- Add or edit a banned pattern or an allow-list entry in `config/compliance.yaml` (regexes compile at load time; a bad pattern fails `load_config`).
- Change suitability minimums under `suitability.min_buying_power`.
- Change the per-position loss limits in `config/risk_profiles.yaml`; the Risk agent carries them into `SuitabilityFacts`.
- Change the goal rules under `goal` (`require_status`, `require_stress_path`, `fire_requires_withdrawal_source`, `promise_pattern`) and the tax rules under `tax` (`disclaimer`, `forbid_rates`; the rate and imperative patterns have defaults in `config.py` and can be overridden there).
- Add a row to one of the tables above for any new behaviour; the docs test will hold you to it.
