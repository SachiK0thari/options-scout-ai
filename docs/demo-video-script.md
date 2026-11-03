# OptionsScout AI: demo video script

**Format:** narrated live run, one take per scene, screen recording with voice-over.
**Target length:** 9:30 to 10:30. The architecture gets 20 seconds. Everything else is inside the app.
**Thesis the viewer should leave with:** every number is computed by tested Python, every sentence the model writes goes through a real compliance check before anyone sees it, and the conversation is routed between specialist agents rather than answered by one chatbot.

---

## 0. Read this before recording

### 0.1 What the script assumes exists

This script is written against the **Phase 10** design in [PRD.md](../PRD.md) (sections 5.0, 5.6, 10, 13.1). The following must be built and working before the record button is pressed:

| Scene | Depends on | PRD checklist item |
|---|---|---|
| 3, 4, 6, 7 | Scout tab chat (`ui/tabs/scout.py`) with `st.chat_input` | Phase 10, UI block |
| 3 | `route_node` with intents `new_screen / refine_profile / concept / why / what_if / off_topic` | Phase 10, conversation block |
| 3, 7 | Education agent: `concept_answer_node`, `[Sn]` citations, `knowledge/concepts/*.md` | Phase 10, RAG + Education blocks |
| 3, 7 | Compliance agent: eight checks, **Compliance ✓ badge with expander**, audit log on Under the hood | Phase 10, Compliance block |
| 4, 6 | `what_if` re-run with profile diff on a new thread | Phase 10, conversation block |
| 5 | Nothing new. Live MarketData.app path exists today in `data/market.py` | done (Phase 2, 9) |

If Phase 10 is not finished, use the **fallback cut** in section 9. Do not narrate features that are not on screen.

### 0.2 Pre-flight checklist (do all of these the day of recording)

- [ ] `.env`: `OPTIONS_SCOUT_LLM_MODE=live` with a working provider key. `OPTIONS_SCOUT_DATA_MODE` stays `fixture` so the first scenes do not spend market-data credits. The Data source picker in the app switches to live for scene 5 only.
- [ ] `make index` has been run so `data/knowledge.sqlite` exists. Use the `fastembed` embedder, not `hash`, so retrieval quality on camera matches the eval table.
- [ ] A **dollar-cost averaging** concept doc exists in `knowledge/concepts/` with a primary-source URL. It is not in the PRD's list of ~20 docs. Without it, the question in scene 7 correctly returns *"I don't have a source for that in my knowledge base."*, which is a different (also true) demo. Add the doc, or change the question to one that is in the corpus (for example "what does assignment mean?").
- [ ] Run the exact NVDA prompt from scene 7 **three times** in rehearsal. All three replies must reframe to education plus the licensed-advisor pointer, with the Compliance badge green. If any of the three gives advice-shaped text that passes compliance, fix `prompts/route_message.md` / `config/compliance.yaml` first. Never record around a flaky guardrail.
- [ ] Save a rehearsal thread where the Compliance agent **failed attempt 1 and passed attempt 2**. Threads persist in `data/checkpoints.sqlite`, so write the thread id down. Scene 8 reopens it. If no rehearsal run retried, scene 8 has a deterministic terminal fallback (8.3).
- [ ] MarketData.app free token with credits left. The free plan is roughly 100 credits a day and a chain costs one credit per contract, so **record scene 5 first in the day** or you will hit the 429 before you want to.
- [ ] A second, deliberately wrong token (any string) for the 401 shot.
- [ ] Browser window 1440 × 900, zoom 110%. Close every other tab. Light theme. Hide bookmarks bar.
- [ ] Have the §5.0 mermaid diagram rendered and open in a separate window (or a drawing tablet ready) for scene 2.
- [ ] Clear the chat so the Scout tab opens empty. Keep the rehearsal threads in the checkpointer; only the UI session state resets.

### 0.3 Rules for the voice-over

- Say what is on screen, then why it matters. One sentence each.
- Never say "recommend", "should buy", or "trade idea" in your own narration either. The app's language rules apply to the presenter. Use "candidate", "screened in", "meets the criteria".
- When a number appears on screen, point at it, do not read long lists aloud.
- If something fails on camera that is not the planned failure, keep rolling and say what happened. Cut later. Do not restart the take.

---

## 1. Cold open: the problem (0:00 – 0:40)

**On screen:** black slate, then a slow fade to a plain-text slide with three lines.

> "I have $50,000. Which stocks would I be happy to own if I got assigned?"
> "Is this option a good deal, or does it only look like one?"
> "Can I trust a model that writes its own numbers?"

**Narration:**

> Retail options tools fall into two camps. Either they are a spreadsheet of Greeks you have to interpret yourself, or they are a chatbot that sounds confident and quietly makes up a return figure. Neither is safe to put in front of someone with their savings on the line.
>
> OptionsScout is an educational screener built on a different rule: the language model never does math, and nothing it writes reaches the user until a compliance agent has checked it. I want to show you the whole loop running live, including where it fails and gets caught.

**Cut on:** "gets caught."

---

## 2. Architecture in twenty seconds (0:40 – 1:05)

**On screen:** the §5.0 diagram (Orchestrator → six specialists → Compliance → user). Trace the path with the cursor or a pen as you talk. Do not read the boxes.

**Narration (keep it to this, timed to the pointer):**

> One LangGraph parent graph. An orchestrator parses what you typed and classifies the intent. A new screen flows down the left: Market Data pulls quotes and runs a quality gate, Market Intelligence adds the consumer-trend signal, Strategy screens the chains, Portfolio sizes positions, Risk stress-tests them and can send sizing back up to three times.
>
> A concept question skips all of that and goes straight to the Education agent, which answers from a cited knowledge base.
>
> Every path ends at the same place: the Compliance agent. There is no edge from any writer to the UI. That is the design, and in a minute you will see the audit log that proves it ran.

**Cut on:** the cursor resting on the Compliance box.

---

## 3. One continuous conversation (1:05 – 3:40)

**On screen:** switch to the browser. Scout tab, empty chat, disclaimer banner visible at the top. Keep the Under the hood tab one click away.

### 3.1 Turn 1: a concept question → Education agent

**Type live:**

```
What is a cash-secured put, and what actually happens if I get assigned?
```

**What must appear:** an assistant turn with two or three short paragraphs, each sentence with a `[S1]`-style tag, a *Sources* list underneath (expect the OCC *Characteristics and Risks of Standardized Options* and the repo's own `cash_secured_put` concept doc), the one-line "Education, not advice" label, and a green **Compliance ✓** badge.

**Narration (while the answer streams):**

> The orchestrator classified that as a concept question, so only the Education agent ran. Watch the tags. Every definitional sentence carries a source marker, and the sources are listed underneath with links. That is not decoration. In a moment the compliance step will fail an answer that drops a tag.

**Action:** click the **Compliance ✓** badge to open the expander.

**Narration:**

> This is the compliance report for that one reply. Eight checks. Numbers, citations, education-only language, suitability, banned phrases, disclaimer, source freshness, no personal data. All passed, and this report is stored with the turn.

Close the expander.

### 3.2 Turn 2: a follow-up that routes to a different path and carries context

**Type live (use the word "that" on purpose):**

```
OK, run that for me. $50,000, cash account, conservative.
```

**What must appear:** a different kind of assistant turn. The orchestrator classified it as `new_screen`. The profile-confirmation card renders **inside the chat** with editable fields: Buying power 50,000 · Account cash · Risk conservative · **Strategies: csp**. That last field is the proof of context: the message never said "cash-secured put", the agent carried it from turn 1.

**Narration:**

> Different intent, different route. This went to the orchestrator's intake, not to Education. And look at Strategies. I did not type "cash-secured put" in this message. The thread remembered what "that" referred to. The run pauses here on a LangGraph interrupt so I can correct anything before money-shaped numbers are computed.

**Action:** click **Confirm**. Node progress streams as status lines in the chat (regime, allocation, trend scout, universe, per-ticker market data, screener, ranker, sizing, risk, explainer, compliance, report). Let it run; fixture mode finishes in about a second, so slow your narration rather than the app.

**Narration:**

> Each line is a specialist finishing. Sizing and Risk can loop. Explainer and Compliance can loop. The summary that appears at the end is the compliance-checked version, and it points me to the Candidates and Portfolio tabs rather than trying to be the whole report.

**What must appear:** a short summary turn, Compliance ✓ badge, and a line like "7 of 7 names passed the quality gate; see Candidates and Portfolio & Risk."

### 3.3 Turn 3: a "why" question over the report just produced

**Type live:**

```
Why is Nike ranked at the bottom?
```

**What must appear:** a `why`-routed answer that mixes two paragraph modes. One `education` paragraph explaining the quality gate with a `[Sn]` tag pointing at the generated rules doc (`knowledge/rules/quality_gate.md`). One `screen_result` paragraph quoting the run's own numbers for NKE (on fixtures: quality 46, 30-day vol 28%, 15% below its 90-day high). Compliance ✓.

**Narration:**

> Third intent in one conversation. This is a "why" question about the report we just produced, so the orchestrator sent it to Education with evidence retrieval over the current run. Notice the two kinds of sentence. The rule is cited from the knowledge base. The numbers are the run's own numbers, and the compliance step checked that every one of them exists in the computed payload. The model was not allowed to invent a 28 percent.

**Action:** click **Under the hood**. Scroll to the agent trace for this thread.

**Narration:**

> Three turns, three routes. Concept went to Education only. The screen walked every specialist. The why question went to Market Intelligence and Education. Same thread id throughout, so the context never left the checkpointer.

**Cut on:** the three intents visible in the trace.

---

## 4. Portfolio analysis with input typed live (3:40 – 5:00)

**On screen:** Scout tab still open.

**Type live:**

```
What if I had 30k in a margin account instead?
```

**What must appear:** a one-line diff turn ("buying_power 50,000 → 30,000 · account_type cash → margin · new thread …"), then streamed progress, then the summary with its badge.

**Narration:**

> A what-if is a fourth intent. The orchestrator diffs the profile, shows me exactly what changed, and runs the whole pipeline again on a new thread so the first result is not overwritten.

**Action:** click **Portfolio & Risk**. Walk the tab top to bottom. Point, do not read.

1. **Allocation donut.** Conservative baseline is 50% put collateral, 15% LEAPS, 35% cash. LEAPS was not requested, so that bucket is held as cash on screen.
2. **Sized positions table.** Contracts per candidate, capital used, margin used, and the **realistic loss at −30%** column.
3. **Constraint checks.** Six rows with value, limit, pass. Conservative on margin: margin usage limit 30%, loss per position 2% of account, per ticker 5%.
4. **Stress bars** at −10/−20/−30% with the IV shock.
5. **Candidates that did not fit** expander: each skipped candidate has a reason (per-ticker cap, sector cap, margin cap).

**Narration (over the walk):**

> This is what portfolio analysis means here. Buying power is split by the stated risk profile and the volatility regime. Candidates are sized greedily under six constraints, and anything that does not fit is listed with the constraint that stopped it, not silently dropped. Because this is a margin account now, the Reg T requirement sits right next to the loss at a 30 percent drop. The app never shows margin without showing that loss. That pairing is a compliance rule, not a layout choice.

**Cut on:** the skipped-candidates expander open.

---

## 5. Live market data, and what happens when it fails (5:00 – 6:30)

Record this scene **first in the day** (see pre-flight). Edit it into this position.

### 5.1 A real quote comes back

**Action:** open **Setup** tab → *Data source* expander → choose **MarketData.app (paste your API token)** → paste the working token into the password field. Read the caption aloud, it is short and it matters.

**Narration:**

> "Your token is used for this run only. It is never written to disk, logged, cached or shown in the report." That sentence is tested.

**Action:** set buying power 50,000, *Cash-secured puts*, click **Find candidates**. Progress bar runs noticeably slower than fixture mode. Let the viewer feel the difference.

**What must appear when it finishes:**
- Caption line: `data: live` and today's as-of timestamp.
- **Quality Screen** tab: prices and 30-day vol that differ from the fixture numbers you showed earlier. Point at SPY's price and compare it aloud to the fixture value from scene 3.
- **Under the hood** → data-source status: `market_data: marketdata`, per-ticker `ok`.
- The banner still says **delayed, for education only**.

**Narration:**

> Those are live quotes and live chains from MarketData.app, fetched with my own token. Compare SPY to the bundled snapshot from a minute ago, it moved. Greeks are recomputed from the live implied vol by the same pricing code the tests cover. And it is still labelled delayed, because the free tier is delayed, and the compliance disclaimer check requires that label whenever the provider is not real-time.

### 5.2 The failure path, on purpose

**Action:** *Data source* expander → replace the token with the wrong one → **Find candidates**.

**What must appear:** the run completes rather than crashing. Progress reaches the end. Then:
- Metrics row: `Stocks passing quality gate 0 / 7` (or similar), `Positions sized 0`.
- **Under the hood** → *Notes and degraded sources*: one line per ticker reading
  `market_data SPY: MarketDataError: MarketData.app rejected the API token (401 Unauthorized)`
  and one line `regime: VIX unavailable (...); using neutral defaults`.
- The plain-English summary says no candidate met the criteria and lists the data problem in the limitations paragraph. Compliance still passed, because an honest "nothing passed" is a valid report.

**Narration:**

> Wrong token. The run does not crash and it does not fall back to stale numbers and pretend. Each ticker records its own failure, the regime step falls back to neutral defaults and says so, and the report explains why there are no candidates. A rate limit is handled the same way: a 429 from the provider raises immediately with the message "credit or rate limit reached" instead of retrying into the wall, because a retry will not fix a spent budget. Only transport errors and 5xx responses get exponential backoff.

If you **actually hit the 429** during the day, record that instead. It is better footage. The message on screen will read `MarketData.app: credit or rate limit reached (429)`.

**Cut on:** the degraded-sources list.

---

## 6. Goal planning driven by a stated risk appetite (6:30 – 7:30)

Be precise about what "goal planning" means in this app: it turns a stated risk appetite, buying power and strategy choice into an allocation plan and risk limits. It does not do retirement-date math. Say that.

**On screen:** back to **Scout**. Switch the data source back to bundled sample data first (Setup tab) so the chat runs are fast.

**Type live:**

```
I'm aggressive, I have $100,000 in a margin account, and I want both puts and LEAPS. Plan it out.
```

**What must appear:** confirmation card with Risk **aggressive**, Strategies **csp, leaps**. Confirm. Then open **Portfolio & Risk** and put it beside what you saw in scene 4.

Point at these differences only:

| | conservative (scene 4) | aggressive (now) |
|---|---|---|
| CSP / LEAPS / cash split | 50 / 15 / 35 | 45 / 35 / 20 |
| Max margin usage | 30% | 50% |
| Max loss per position | 2% | 5% |
| Per-ticker cap | 5% | 10% |

Then the regime line: `VIX 17.51, 57th percentile, normal, no tilt` on fixtures. Explain the tilt rule in one sentence.

**Narration:**

> Same pipeline, different stated appetite. The plan changes in two places. The allocation moves twenty points from cash and puts into LEAPS. And every risk limit loosens, which you can see in the constraint table. One thing never changes: the cash reserve is never reduced by the volatility tilt. If the VIX were above its 70th percentile the plan would move ten points from LEAPS into put collateral, because buying expensive long calls in a high-vol regime is the thing this tool is built to discourage.
>
> To be clear about scope: this is planning in the sense of allocation and sizing under limits. It is not telling anyone what their retirement number is.

**Cut on:** the constraint table.

---

## 7. The compliance layer, two beats (7:30 – 9:00)

Still in **Scout**, same thread.

### 7.1 Beat one: compliance on normal traffic

**Type live:**

```
What's dollar-cost averaging?
```

**What must appear:** a short cited answer, `[S1]`, `[S2]` tags, *Sources* list with a real URL, the "Education, not advice" label, the disclaimer line at the end, Compliance ✓.

**Narration:**

> A boring question on purpose. There is nothing to refuse here, and that is the point: compliance is not a refusal filter that wakes up for dangerous prompts. It ran the same eight checks on this answer as on anything else. The disclaimer is attached. The sources are attached. Nothing in the answer tells me to do anything.

**Action:** open the badge expander, point at `check_citations: passed` and `check_disclaimer: passed`. Close it.

### 7.2 Beat two: a request that crosses the line

**Type live, exactly:**

```
Should I put my savings into NVDA right now?
```

**What must appear (this is what rehearsal verified three times):**
- The reply does **not** answer yes or no.
- It reframes: what the question actually involves (single-stock concentration, implied volatility, why "right now" is the part no tool can answer), each claim tagged to a source.
- It states, with the rule cited, that NVDA is not on the good-to-own list and would be evaluated against the same numeric gate if added.
- It closes with the licensed-advisor sentence and the one-line disclaimer.
- Compliance ✓.

**Narration:**

> This is the request most demos skip. The honest answer to "should I" is that this is not the kind of system that gets to say so, and the design makes that structural rather than polite. The reply explains what the question involves, points out that NVDA is deliberately not on the good-to-own list, cites the rule, and hands the decision to a licensed professional. Nothing here is a mood of the model. The compliance check would block a different answer, and that is the next thing I want to show you.

**Cut on:** the licensed-advisor sentence.

---

## 8. Proof it is a check, not a prompt (9:00 – 10:00)

This is the scene that separates the video from a recording of a chatbot being polite. Show the mechanism, not the manners.

### 8.1 The actual output of the compliance step

**Action:** open the **Compliance ✓** badge on the NVDA reply.

**What must appear:** the `ComplianceReport`: `passed: true`, then eight rows of `name · passed · severity · detail`. `check_education_only` and `check_language` should show detail like "0 directive phrases, 0 run identifiers in education paragraphs".

**Narration:**

> This is the object the agent produced, not a summary of it. Eight named checks with a pass flag and a severity. Six of them block. Two warn. It is deterministic code first, and the optional model judge is only allowed to add warnings, never to approve.

### 8.2 One that got caught

**Action:** click **Under the hood** → *Compliance audit log*. Select the rehearsal thread you saved in pre-flight (or scroll to it if the log shows every thread).

**What must appear:** two `compliance.check` events for the same turn.
- Attempt 1: `passed: false`, `check_language: FAIL — banned pattern "you should" at paragraph 2` (or whatever the real failing check was), and the `retry_feedback` string that was sent back to the Education agent.
- Attempt 2: `passed: true`.

**Narration:**

> Here is one from rehearsal. First draft, the model wrote "you should" about a specific candidate. Compliance blocked it, wrote the failure back to the Education agent as feedback, and the second draft passed. The user only ever saw the second draft. After two failures the system does not keep trying its luck; it falls back to a template that only echoes computed numbers and says it could not produce an explanation that passes compliance.

### 8.3 Deterministic fallback for 8.2 (use only if no rehearsal run retried)

Open a terminal beside the browser and run the check the graph calls, on a draft of the kind that fails. Say on camera that this is the same function, fed a draft that failed in rehearsal. Today's code (phases 0–9) exposes it as `verify_narrative`; after Phase 10 it is `core/compliance.py`. Both produce a structured result:

```
$ .venv/bin/python - <<'EOF'
from options_scout.agent.verifier import verify_narrative
disc = ("Educational screening tool. Not investment, tax or legal advice. Options involve "
        "significant risk, including loss exceeding the premium received on margin. Data may be "
        "delayed or inaccurate.")
payload = {"positions": [{"candidate_id": "CSP-COST-2026-12-18-850P",
                          "strike": 850, "mid": 9.4, "annualized_return": 0.1547}]}
draft = ("You should buy CSP-COST-2026-12-18-850P now. It is a great setup: the 850 strike pays "
         "about 12% annualized and is basically risk-free. " + disc)
print(verify_narrative(draft, payload, disclaimer=disc).model_dump())
EOF
```

Real output from the current code (recorded 2026-10-29):

```
{'passed': False, 'numbers_checked': 2, 'ungrounded_numbers': [],
 'banned_phrases_found': ['risk-free', 'you should buy'],
 'disclaimer_present': True,
 'cited_candidate_ids': ['CSP-COST-2026-12-18-850P'], 'attempts': 1}
```

Note for narration: the current banned-phrase list catches `you should buy` and `risk-free`. The invented `12%` is **not** flagged here because `0.12` happens to fall inside the number-matching tolerance after the payload's `0.1547` is expanded into display variants; the Phase 10 `check_numbers` with the stricter tolerance in `config/compliance.yaml` should catch it. Do not claim on camera that this snippet caught the 12 percent unless the output on your screen lists it under `ungrounded_numbers`.

Then run the rewritten sentence and show `passed: True`:

```
draft = ("The screen found CSP-COST-2026-12-18-850P, a cash-secured put at the 850 strike with a "
         "mid of 9.4 and an annualized return on collateral of 15.47%. " + disc)
```

**Narration (fallback version):**

> This is the same function the graph calls between the writer and the user. Fed a draft with "you should buy" and "risk-free", it fails and names the phrases. Fed the same facts written as what the screen found, it passes. The graph does this on every reply, and a fail sends the draft back with these exact strings as feedback.

---

## 9. Close (10:00 – 10:30)

**On screen:** return to the §5.0 diagram, cursor on the Compliance box, then fade to the repo README.

**Narration:**

> Four intents in one conversation, routed to different specialists with context carried across turns. Live quotes, and a run that stays honest when the data source fails. A plan that changes with the stated risk appetite. And a compliance agent that is the only path from the model to the screen, with a log that shows it catching a draft.
>
> This is an educational screener. It never places a trade, never connects to a brokerage, and never tells you what to do. The code, the evals and the knowledge base are in the repo.

**End slate:** repo URL, "Educational screening tool. Not investment, tax or legal advice."

---

## 10. Fallback cut for the current build (phases 0 to 9 only)

If Phase 10 is not done, the honest video is shorter and the compliance beat is narrower. Keep scenes 1, 2, 5 and 9 as written. Replace 3, 4, 6, 7 and 8 with:

- **Form run instead of chat.** Setup form: buying power 50,000, *Cash-secured puts*, conservative, cash. *Find candidates*. Walk the five result sections in order. Say clearly that the chat tab is the next phase; do not imply routing exists.
- **Portfolio analysis** from "How it fits your buying power": allocation donut, sized positions, constraint checks, stress chart, skipped candidates. Same narration as scene 4.
- **Risk appetite** by changing *Risk appetite* in *More options* to aggressive and re-running. Same table as scene 6.
- **Compliance** is the verifier caption above the plain-English summary: `Verifier: PASS · N numbers checked, 0 ungrounded · every number above was computed, not written by the model.` Then *Under the hood* → *Notes and degraded sources*, which lists `verifier: attempt 1 failed (banned phrases: ...)` whenever a retry happened. Then the terminal proof in 8.3, which works today exactly as printed.
- Do **not** attempt the "should I buy NVDA" beat on the current build. There is no chat surface, and typing it into the Setup form's ticker field only adds NVDA to the watchlist (where it fails the quality gate, which is a decent but different shot: show the *Excluded by the quality gate* expander with the reason).

---

## 11. Shot list and timing

| # | Scene | Start | Length | Surface | Must-have frame |
|---|---|---|---|---|---|
| 1 | Problem | 0:00 | 0:40 | slide | three questions |
| 2 | Architecture | 0:40 | 0:25 | diagram | cursor on Compliance box |
| 3 | Conversation, 3 turns | 1:05 | 2:35 | Scout, Under the hood | confirmation card showing `Strategies: csp`; three intents in trace |
| 4 | Portfolio what-if | 3:40 | 1:20 | Scout, Portfolio & Risk | diff line; skipped-candidates expander |
| 5 | Live data + failure | 5:00 | 1:30 | Setup, Quality, Under the hood | `data: live`; 401 lines in degraded sources |
| 6 | Risk appetite | 6:30 | 1:00 | Scout, Portfolio & Risk | constraint table 45/35/20 |
| 7 | Compliance two beats | 7:30 | 1:30 | Scout | tagged DCA answer; NVDA reframed with advisor line |
| 8 | Proof | 9:00 | 1:00 | badge expander, audit log or terminal | attempt 1 FAIL, attempt 2 PASS |
| 9 | Close | 10:00 | 0:30 | diagram, README | end slate |

## 12. Things that can go wrong on camera, and what to do

| Symptom | Cause | On-camera response |
|---|---|---|
| Turn 2 confirmation card shows `Strategies: csp, leaps` or empty | intake did not carry "that" from turn 1 | Edit the field in the card, say "I'll correct it here, that is what the interrupt is for", continue. Cut the context-carry narration line in edit. |
| DCA question returns "I don't have a source for that in my knowledge base." | concept doc missing | Keep it. Say: "and when the knowledge base has nothing, it says so rather than improvising." Then ask "what does assignment mean?" for the tagged-answer shot. |
| NVDA reply passes compliance but reads like advice | guardrail gap | Stop. Do not publish. Fix prompt/config, re-run the three-times check. |
| Live run hits 429 | daily credits spent | Better footage than the 401. Record it, narrate the 429 line in 5.2. |
| Compliance retried on a normal turn | model drifted | Great. Open the badge, show attempt count, skip to 8.2 using this thread. |
| Streamlit rerun flickers the chat | normal | Pause narration a beat; cut in edit. |
