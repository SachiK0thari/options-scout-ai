# OptionsScout AI: demo video script

**Format:** narrated live run, one take per scene, screen recording with voice-over.
**Target length:** 9:30 to 10:30. The architecture gets twenty seconds. Everything else is inside the app.
**Thesis the viewer should leave with:** every number is computed by tested Python, every sentence the model writes goes through a real compliance check before anyone sees it, and the conversation is routed between nine specialist agents rather than answered by one chatbot.

The brief asks the video to show multi-turn conversations with different agents, portfolio analysis, real-time market data and goal planning. Scenes 3, 11, 5 and 8 are those four; scenes 9 and 10 show the News Desk and the Tax & Accounts agents; scenes 6 and 7 show the compliance layer catching a draft.

---

## 0. Read this before recording

### 0.1 What the script assumes exists

This script is written against the **Phase 12** build ([PRD.md](../PRD.md) sections 5.0, 5.6, 10, 13.1 and the Phase 12 checklist; the per-agent reference is [architecture.md](architecture.md)). Everything below is built and tested as of 2026-11-06:

| Scene | Depends on | Where it is |
|---|---|---|
| 3, 4, 6, 8, 9, 10, 11 | Scout tab chat (`ui/tabs/scout.py`) with `st.chat_input`, the ten intents in `route_node`, the Compliance ✓ badge with its expander | `agent/nodes/route.py`, `ui/tabs/scout.py` |
| 3, 6 | Education agent: `concept_answer_node`, `[Sn]` citations over the five knowledge collections | `agent/agents/education.py`, `knowledge/` |
| 4 | `what_if` re-run with the profile diff on a new thread; Portfolio & Risk tab | `agent/nodes/what_if.py`, `ui/tabs/portfolio.py` |
| 5 | the live MarketData.app path, the market overview strip with data age | `data/market.py`, `ui/components/market_strip.py` |
| 6, 7 | Compliance agent: eleven checks, audit log on Under the hood | `core/compliance.py`, `ui/tabs/under_the_hood.py` |
| 8 | Goal Planning agent, Goals tab, compliance check 9 | `agent/agents/goal_planning.py`, `ui/tabs/goals.py` |
| 9 | News Desk agent, the 📰 marker on Candidates, the News board on Trends & News, check 10 | `agent/agents/news_desk.py`, `ui/tabs/trends.py` |
| 10 | Tax & Accounts agent, the Learn tab's Tax & Accounts page, check 11 | `agent/agents/tax.py`, `ui/tabs/learn.py` |
| 11 | holdings input on the Portfolio & Risk tab, the `holdings` intent, the seventh constraint | `agent/nodes/holdings_*.py`, `core/holdings.py` |

Do not narrate features that are not on screen.

### 0.2 Pre-flight checklist (do all of these the day of recording)

- [ ] `.env`: `OPTIONS_SCOUT_LLM_MODE=live` with a working `OPENROUTER_API_KEY`. `OPTIONS_SCOUT_DATA_MODE` stays `fixture` so the first scenes do not spend market-data credits. The Data source picker in the app switches to live for scene 5 only.
- [ ] `make index` has been run so `data/knowledge.sqlite` exists. Use the `fastembed` embedder (`pip install -e ".[rag]"`, `OPTIONS_SCOUT_RAG_EMBEDDER=fastembed`), not `hash`, so retrieval quality on camera matches the better eval row.
- [ ] `ALPHAVANTAGE_API_KEY` set if you want live headlines in scene 9; the fixture headlines for the ten demo tickers are fine too and never rate-limit. Decide before recording and say which on camera.
- [ ] Run the exact NVDA prompt from scene 6 **three times** in rehearsal. All three replies must reframe to education plus the licensed-advisor pointer, with the Compliance badge green. If any of the three gives advice-shaped text that passes compliance, fix `prompts/route_message.md` / `config/compliance.yaml` first. Never record around a flaky guardrail.
- [ ] Run the scene 8 goal turn in rehearsal and confirm the verdict is **does not fit** on $60,000 conservative (the required return is 8% a year, above the conservative cap of 6% in `config/goals.yaml`, so the verdict does not depend on the screened yield). If a fixture change has moved the yield, change the target to a figure that still does not fit and update the narration.
- [ ] Save a rehearsal thread where the Compliance agent **failed attempt 1 and passed attempt 2**. Threads persist in `data/checkpoints.sqlite`, so write the thread id down. Scene 7 reopens it. If no rehearsal run retried, scene 7 has a deterministic terminal fallback (7.3).
- [ ] MarketData.app token with credits left. With the default historical chain feed a ticker costs a few credits (its whole previous-session chain is one request at about one credit per 1,000 contracts), but the free plan is roughly 100 credits a day, so **record scene 5 first in the day**. A run that would overspend is cut to the tickers the credits cover, with a note.
- [ ] A second, deliberately wrong token (any string) for the 401 shot.
- [ ] Browser window 1440 × 900, zoom 110%. Close every other tab. Light theme. Hide bookmarks bar.
- [ ] Have the README's mermaid diagram rendered and open in a separate window for scene 2.
- [ ] Clear the chat so the Scout tab opens empty. Keep the rehearsal threads in the checkpointer; only the UI session state resets.

### 0.3 Rules for the voice-over

- Say what is on screen, then why it matters. One sentence each.
- Never say "recommend", "should buy", or "trade idea" in your own narration either. The app's language rules apply to the presenter. Use "candidate", "screened in", "meets the criteria".
- When a number appears on screen, point at it, do not read long lists aloud.
- If something fails on camera that is not the planned failure, keep rolling and say what happened. Cut later. Do not restart the take.

### 0.4 Pick the amount: $50,000 or $100,000

The script works at either amount. Pick one before recording and use it everywhere **AMOUNT** appears (scenes 1, 3.2 and 5.1). The what-if in scene 4 is the same sentence for both: a $60,000 margin account.

The figures below are what the bundled fixtures (session 2026-10-27) produce for the scene 3 profile: cash account, conservative, **cash-secured puts only**. They were measured on 2026-11-12. They do not depend on the model, because every number is computed, so a live-LLM take shows the same figures in different words. Live data in scene 5 will differ.

| What appears | AMOUNT = $50,000 | AMOUNT = $100,000 |
|---|---|---|
| Allocation (50% puts / 15% LEAPS / 35% cash) | $25,000 / $7,500 / $17,500 | $50,000 / $15,000 / $35,000 |
| Quality gate (scene 3.2) | 7 of 7 passed, 0 excluded | same |
| Candidates | 5 cash-secured puts: SPY ×2, QQQ ×2, NKE; NKE ranks 5th of 5 | same |
| Sized after turn 2 | **1** × CSP-NKE-2026-11-20-35P, $3,444 cash to secure, realistic loss $814 | **2** × CSP-NKE-2026-11-20-35P, $6,887 cash to secure, realistic loss $1,629 |
| Sizing warnings | one-stock portfolio (all NKE); SPY and QQQ did not fit, the top-ranked SPY 735 put fits from **$960,716**; 14% of the put budget used | same, 14% of the put budget used |
| Scene 4 diff line | 50,000 → 60,000 · cash → margin | 100,000 → 60,000 · cash → margin |
| Scene 4 sized (identical for both) | 1 × NKE 35 put: Reg T **$552** beside a realistic loss of **$814**; 8 constraint rows, all pass; 4 SPY/QQQ puts skipped on *max loss per position* | same |
| Scene 11 before/after bar | NKE 0% → 2% of holdings plus buying power, against the 25% conservative cap | same |

Two things decide whether this table holds on camera:

- **The confirmation card must say `Strategies: csp`.** If the live model does not carry "that" from turn 1 and the card shows csp, leaps and pmcc, edit it to csp before **Confirm** (see section 14). Left at all three, the figures change: the screen also lists 9 LEAPS, NKE's best line ranks 9th of 14 rather than last (which breaks the scene 3.3 question), and $100,000 also sizes 1 NKE LEAPS. Rechecked 2026-11-12 after the LEAPS ranking moved to the model probability (W25), which put NKE among the five best underlyings; before that change nothing was sized at either amount.
- **Do not change the scene 4 amount to $30,000.** A $30,000 margin account sizes nothing: NKE's $814 loss is more than the conservative 2% per-position limit ($600). If you want the "too small" refusal on camera, record it as an extra take, not as scene 4.

---

## 1. Cold open: the problem (0:00 – 0:30)

**On screen:** black slate, then a slow fade to a plain-text slide with three lines.

> "I have $AMOUNT. Which stocks would I be happy to own if I got assigned?"
> "Is this option a good deal, or does it only look like one?"
> "Can I trust a model that writes its own numbers?"

**Narration:**

> Retail options tools fall into two camps. Either they are a spreadsheet of Greeks you have to interpret yourself, or they are a chatbot that sounds confident and quietly makes up a return figure. Neither is safe to put in front of someone with their savings on the line.
>
> OptionsScout is an educational screener built on a different rule: the language model never does math, and nothing it writes reaches the user until a compliance agent has checked it. I want to show you the whole loop running live, including where it fails and gets caught.

**Cut on:** "gets caught."

---

## 2. Architecture in twenty seconds (0:30 – 0:50)

**On screen:** the README diagram (Orchestrator → nine specialists → Compliance → user). Trace the path with the cursor as you talk. Do not read the boxes.

**Narration (keep it to this, timed to the pointer):**

> One LangGraph parent graph, eleven subgraphs. An orchestrator classifies what you typed into one of ten intents. A screen flows down the left: Market Data, Strategy, News Desk, Portfolio, Risk, with Risk able to send sizing back. A question goes straight to its specialist: Education, Goal Planning, Tax. Every path ends at the Compliance agent. There is no edge from any writer to the screen.

**Cut on:** the cursor resting on the Compliance box.

---

## 3. One continuous conversation (0:50 – 2:50)

**On screen:** switch to the browser. Scout tab, empty chat, disclaimer banner visible at the top. Keep the Under the hood tab one click away.

### 3.1 Turn 1: a concept question → Education agent

**Type live:**

```
What is a cash-secured put, and what actually happens if I get assigned?
```

**What must appear:** an assistant turn with two or three short paragraphs, each definitional sentence with a `[S1]`-style tag, a *Sources* list underneath (expect the repo's own *Cash-secured put* and *Assignment* documents with the OCC link), the one-line "Education, not advice" label, and a green **Compliance ✓** badge.

**Narration (while the answer streams):**

> The orchestrator classified that as a concept question, so only the Education agent ran. Every definitional sentence carries a source marker, and the sources are listed underneath with links. In a minute the compliance step will fail an answer that drops a tag.

**Action:** click the **Compliance ✓** badge to open the expander.

**Narration:**

> Eleven checks. Numbers, citations, education-only language, suitability, banned phrases, disclaimer, source freshness, no personal data, and three rules for goal, news and tax replies that pass trivially here because this is none of those. All passed, and this report is stored with the turn.

Close the expander.

### 3.2 Turn 2: a follow-up that routes to a different path and carries context

**Type live (use the word "that" on purpose):**

```
OK, run that for me. $AMOUNT, cash account, conservative. I'm a beginner.
```

**What must appear:** the orchestrator classified it as `new_screen`. The profile-confirmation card renders **inside the chat** with editable fields: Buying power AMOUNT · Account cash · Risk conservative · **Strategies: csp** · **Experience: beginner**. The strategies field is the proof of context: the message never said "cash-secured put", the agent carried it from turn 1.

**Narration:**

> Different intent, different route. This went to the orchestrator's intake, not to Education. Look at Strategies: I did not type "cash-secured put" in this message, the thread remembered what "that" referred to. And "beginner" became the profile's knowledge level, which changes which documents get cited and how the tables read. The run pauses here on a LangGraph interrupt so I can correct anything before money-shaped numbers are computed.

**Action:** click **Confirm**. Node progress streams as status lines in the chat (regime, trend scout, universe, per-ticker market data, screener, ranker, news desk, sizing, risk, explainer, compliance, report). Fixture mode finishes in about a second, so slow your narration rather than the app.

**What must appear:** a short summary turn, Compliance ✓ badge, and a line like "7 underlying(s) passed the good-to-own gate and 0 were excluded; the screen found 5 cash-secured put candidate(s) and sized 1 position(s)" (2 at $100,000; see 0.4).

**Action:** click **Candidates**. Point at the market strip (SPY, QQQ, VIX with its regime, T-bill, "fixture, recorded 2026-10-27") and at the plain-language column headers. Hover one header to show its glossary tooltip.

**Narration:**

> Beginner profile, so the table shows "cash to secure" and "chance it expires worthless" instead of delta and probability OTM, and every header has a one-sentence definition tied to a Learn page. The strip at the top says where the data came from and how old it is.

### 3.3 Turn 3: a "why" question over the report just produced

**Back on Scout. Type live:**

```
Why is Nike ranked at the bottom?
```

**What must appear:** a `why`-routed answer that mixes two paragraph modes. One `education` paragraph explaining the quality gate with a `[Sn]` tag pointing at the generated rules document (`knowledge/rules/quality_gate.md`). One `screen_result` paragraph quoting the run's own numbers for NKE (on fixtures: quality 46, 30-day vol 28%, 15% below its 90-day high). Compliance ✓.

**Narration:**

> Third intent in one conversation. The rule is cited from the knowledge base. The numbers are the run's own numbers, and the compliance step checked that every one of them exists in the computed payload. The model was not allowed to invent a 28 percent.

**Action:** click **Under the hood**. Scroll to the agent trace for this thread.

**Narration:**

> Three turns, three routes, one thread id. The context never left the checkpointer.

**Cut on:** the three intents visible in the trace.

---

## 4. What-if, and a portfolio sized under constraints (2:50 – 3:40)

**On screen:** Scout tab still open.

**Type live:**

```
What if I had 60k in a margin account instead?
```

**What must appear:** a one-line diff turn ("buying power: 50,000 → 60,000; account value: 50,000 → 60,000; account type: cash → margin", or 100,000 → 60,000 if AMOUNT is $100,000), the note that a new screen runs on a separate thread, then streamed progress, then the summary with its badge.

**Narration:**

> A what-if diffs the profile, shows me exactly what changed, and runs the whole pipeline again on a new thread so the first result is not overwritten.

**Action:** click **Portfolio & Risk**. Walk the lower half top to bottom. Point, do not read.

1. **Allocation donut.** Conservative baseline is 50% put collateral, 15% LEAPS, 35% cash: $30,000, $9,000 and $21,000 of $60,000. LEAPS was not requested, so that bucket is held as cash.
2. **Sized positions table**: one row, 1 × CSP-NKE-2026-11-20-35P, with the **realistic loss at −30%** ($814) beside the Reg T margin used ($552).
3. **Constraint checks**: eight rows with value, limit, pass (margin usage is the extra row a margin account adds).
4. **Warnings**: "Every sized position is on NKE, so this is a one-stock portfolio even though the limits passed", and the SPY 735 put that fits from $960,716.
5. **Candidates that did not fit** expander: the four SPY and QQQ puts, each stopped by *max loss per position*.

**Narration (over the walk):**

> Buying power is split by the stated risk profile and the volatility regime. Candidates are sized greedily under the constraints, and anything that does not fit is listed with the reason, not silently dropped. Here the higher-ranked SPY and QQQ puts would each lose more in a 30 percent drop than this profile allows on one position, so only the Nike put fits, and the app says plainly that one stock is not a diversified portfolio even though every limit passed. Because this is a margin account now, the Reg T requirement sits next to the loss at a 30 percent drop. The app never shows margin without showing that loss. That pairing is a compliance rule, not a layout choice.

**Cut on:** the skipped-candidates expander open.

---

## 5. Live market data, and what happens when it fails (3:40 – 4:50)

Record this scene **first in the day** (see pre-flight). Edit it into this position.

### 5.1 A real quote comes back

**Action:** open **Setup** → *Data source* expander → choose **MarketData.app (paste your API token)** → paste the working token. Read the caption aloud.

**Narration:**

> "Your token is used for this run only. It is never written to disk, logged, cached or shown in the report." That sentence is tested.

**Action:** set buying power to AMOUNT, *Cash-secured puts*, click **Find candidates**. The progress bar runs noticeably slower than fixture mode.

**What must appear when it finishes:**
- **Quality Screen** tab: the strip now reads `delayed quotes, fetched 14:02 UTC (12 min ago)` or similar, with `marketdata` as the provider, and prices that differ from the fixture numbers. Point at SPY and compare it aloud to the fixture value from scene 3.
- **Under the hood** → data-source status: `market_data: marketdata`, per-ticker `ok`.
- The banner still says **delayed, for education only**.

**Narration:**

> Live quotes and live chains from MarketData.app, fetched with my own token, and the strip says exactly how old they are. Greeks are recomputed from the live implied vol by the same pricing code the tests cover. It is still labelled delayed, because the free tier is delayed, and the disclaimer check requires that label whenever the provider is not real-time.

### 5.2 The failure path, on purpose

**Action:** *Data source* expander → replace the token with the wrong one → **Find candidates**.

**What must appear:** the run completes rather than crashing. Metrics row: `Stocks passing quality gate 0 / 7`, `Positions sized 0`. **Under the hood** → *Notes and degraded sources*: one line per ticker reading `market_data SPY: MarketDataError: MarketData.app rejected the API token (401 Unauthorized)` and one line `regime: VIX unavailable (...); using neutral defaults`. The summary says no candidate met the criteria and names the data problem. Compliance still passed, because an honest "nothing passed" is a valid report.

**Narration:**

> Wrong token. The run does not crash and it does not fall back to stale numbers and pretend. Each ticker records its own failure, the regime step falls back to neutral defaults and says so, and the report explains why there are no candidates. A rate limit is handled the same way: a 429 raises immediately with "credit or rate limit reached" instead of retrying into the wall, because a retry will not fix a spent budget.

If you **actually hit the 429** during the day, record that instead. It is better footage.

**Cut on:** the degraded-sources list. Switch the data source back to bundled sample data before the next scene.

---

## 6. The compliance layer, two beats (4:50 – 5:50)

**On screen:** back to **Scout**, the original thread.

### 6.1 Beat one: compliance on normal traffic

**Type live:**

```
What's dollar-cost averaging?
```

**What must appear:** a short cited answer with `[S1]`, `[S2]` tags (the *basics* collection's dollar-cost averaging document, with its SEC investor.gov link), the "Education, not advice" label, the disclaimer line, Compliance ✓.

**Narration:**

> A boring question on purpose. There is nothing to refuse here, and that is the point: compliance is not a refusal filter that wakes up for dangerous prompts. It ran the same eleven checks on this answer as on anything else.

### 6.2 Beat two: a request that crosses the line

**Type live, exactly:**

```
Should I put my savings into NVDA right now?
```

**What must appear (this is what rehearsal verified three times):**
- The reply does **not** answer yes or no.
- It reframes: what the question involves (single-stock concentration, implied volatility, why "right now" is the part no tool can answer), each claim tagged to a source.
- It states, with the rule cited, that NVDA is not on the good-to-own list and would be evaluated against the same numeric gate if added.
- It closes with the licensed-advisor sentence and the one-line disclaimer.
- Compliance ✓.

**Narration:**

> The honest answer to "should I" is that this is not the kind of system that gets to say so, and the design makes that structural rather than polite. Nothing here is a mood of the model. The compliance check would block a different answer, and that is the next thing I want to show you.

**Cut on:** the licensed-advisor sentence.

---

## 7. Proof it is a check, not a prompt (5:50 – 6:30)

### 7.1 The actual output of the compliance step

**Action:** open the **Compliance ✓** badge on the NVDA reply.

**What must appear:** the `ComplianceReport`: `passed: true`, then eleven rows of `name · passed · severity · detail`.

**Narration:**

> This is the object the agent produced, not a summary of it. Eleven named checks with a pass flag and a severity. Ten of them block, one warns. It is deterministic code; the optional model judge is only allowed to add warnings, never to approve.

### 7.2 One that got caught

**Action:** click **Under the hood** → *Compliance audit log*. Select the rehearsal thread you saved in pre-flight.

**What must appear:** two `compliance.check` events for the same turn. Attempt 1: `passed: false`, `check_language: FAIL — banned pattern "you should" at paragraph 2` (or whatever the real failing check was), and the `retry_feedback` string that was sent back to the writer. Attempt 2: `passed: true`.

**Narration:**

> First draft, the model wrote "you should" about a specific candidate. Compliance blocked it, wrote the failure back to the Education agent as feedback, and the second draft passed. The user only ever saw the second draft. After two failures the system falls back to a template that only echoes computed numbers and says it could not produce an explanation that passes compliance.

### 7.3 Deterministic fallback for 7.2 (use only if no rehearsal run retried)

Open a terminal beside the browser and run the check the graph calls, on a draft of the kind that fails. Say on camera that this is the same function, fed a draft that failed in rehearsal.

```
$ .venv/bin/python - <<'PY'
from options_scout.config import load_config
from options_scout.core.compliance import run_compliance
from options_scout.core.models import Narrative, Paragraph
cfg = load_config()
disc = cfg.settings.disclaimer
payload = {"positions": [{"candidate_id": "CSP-COST-2026-12-18-850P", "strike": 850,
                          "premium": 940, "realistic_loss": 12345}],
           "risk": {"stress_drop_pct": 30}}
def check(text):
    n = Narrative(paragraphs=[Paragraph(mode="screen_result", text=text),
                              Paragraph(mode="notice", text=disc)])
    r = run_compliance(n, payload=payload, sources=[], facts=None, cfg=cfg.compliance,
                       disclaimer=disc, text_kind="answer", run_tickers=["COST"], delayed_data=False)
    print(r.passed, [c.name + ": " + c.detail for c in r.checks if not c.passed])
check("You should buy CSP-COST-2026-12-18-850P now. It is a great setup: the 850 strike pays "
      "about 9% annualized and is basically risk-free.")
check("The screen found CSP-COST-2026-12-18-850P, a cash-secured put at the 850 strike collecting "
      "940 of premium; its realistic loss after a 30% drop is 12345. Education, not advice.")
PY
```

Output from the current code (recorded 2026-11-12, after W14):

```
False ['check_numbers: 2 numbers checked, not grounded: 9%', 'check_education_only: paragraph 1: short option CSP-COST-2026-12-18-850P described without its own realistic loss', "check_language: paragraph 1: certainty ('risk-free'); paragraph 1: directive ('You should'); paragraph 1: superlative ('great setup')"]
True []
```

Note for narration: the invented 9% is caught by `check_numbers` because no payload number is within 1% of it. A number that happens to appear inside a candidate id (the `12` of `2026-12-18`) would pass the numeric check, which is why the education-only and language checks exist beside it. Run the snippet once in rehearsal and keep the terminal output; do not claim on camera anything the output on your screen does not show.

**Narration (fallback version):**

> This is the same function the graph calls between the writer and the user. Fed a draft with "you should buy", "great setup", "risk-free", an invented 9 percent and a short option named without its loss, it fails and names each problem. Fed the same facts written as what the screen found, it passes. A fail sends the draft back with these exact strings as feedback.

---

## 8. Goal planning against a stated risk appetite (6:30 – 7:30)

Be precise about what goal planning means here: a stated income or growth target is checked against the yield the screened portfolio can produce under the risk profile's cap, and the reply says what has to change. It is not a retirement calculator that promises a number.

**On screen:** **Scout**. Start a fresh thread with `$60,000 cash account, conservative, cash-secured puts` and confirm (the rehearsal fixed the figures).

**Type live:**

```
I want $400 a month from this account.
```

**What must appear:** a goal turn that states the verdict in words, **does not fit**, with the required return (8% a year on $60,000) against the expected yield of the sized puts and the conservative cap of 6%; three levers (a lower target, a larger balance, a longer horizon or a different profile) with numbers; a cited education paragraph on compound growth or the app's risk profiles from the *basics* collection; Compliance ✓ with check 9 listed as `goal_narrative`.

**Action:** click **Goals**. Point at the verdict metrics, the four-path projection (stress, base, best, diversified assumption) with the target line, and the levers.

**Narration:**

> Goal planning here means one honest question: does this goal fit this account under this risk profile? Four hundred a month on sixty thousand needs eight percent a year. The conservative profile caps what a plan may assume at six, and the screened puts, after the stress adjustment, give less than that. So the verdict is "does not fit", and the three levers say what would change it. Every figure on this chart was computed; the model wrote the sentences, and compliance check nine made sure it said "would", never "will", and named the stress path next to the base path.

**Type live:**

```
I spend 48k a year, have 220k and add 2k a month. When could I lean FIRE?
```

**What must appear:** the FIRE card: variant **lean**, the expense target, the FIRE number at a 4% withdrawal rate, years to FI, the coast balance, and the **income coverage** line saying what share of the expenses the options income could cover and how much buying power full coverage would need; the reply names the variant and says the 4% figure comes from diversified-portfolio research; Compliance ✓.

**Narration:**

> Lean FIRE on these numbers is a date, not a promise, and the card says what the four percent rule rests on: research on diversified portfolios, which an options-income account is not. That caveat is a compliance rule, not a footnote.

**Cut on:** the FIRE card.

---

## 9. News as context, never as a signal (7:30 – 8:00)

**On screen:** **Candidates** tab of the current thread. Find a row with the 📰 marker (on fixtures, a name with earnings inside the option's life).

**Narration:**

> This candidate carries a news flag: an earnings date falls inside the option's life. The flag comes from calendar arithmetic, not from a headline.

**Action:** click **Trends & News** → *News desk*. Point at the ticker's headlines with their category, relevance and sentiment labels.

**Type live on Scout:**

```
Any news on COST and NKE?
```

**What must appear:** a brief per ticker quoting one or two headlines verbatim with publisher and date, the calendar flags on the screened puts, Compliance ✓ with check 10 as `news_grounding`.

**Narration:**

> The News Desk labels headlines for a put writer: earnings, guidance, corporate action, macro. It quotes them verbatim, and compliance check ten verifies every quoted span against the fetched items, so the brief cannot put words in a publisher's mouth. Headlines never change the ranking. They are context for a human, not a signal for the screen.

**Cut on:** the news brief with its badge.

---

## 10. Tax education with the candidate's own numbers (8:00 – 8:40)

**On screen:** **Scout**, same thread.

**Type live:**

```
What happens to my taxes if one of those puts is assigned?
```

**What must appear:** a cited answer from the *tax* collection (assignment cost basis, premium taxation) with the screened put's numbers: the strike, the premium, and the resulting cost basis per share; the long-term threshold date for the shares; the wash-sale window; the tax disclaimer sentence exactly once; Compliance ✓ with check 11 as `tax_reply`.

**Action:** click **Learn** → *Tax & Accounts*. Point at the assignment-basis calculator bound to the same put and the account chooser table.

**Narration:**

> The Tax and Accounts agent explains mechanics and illustrates them with this screen's own put: strike, premium, cost basis if assigned, the date the shares would turn long-term. It never states the rate you would pay, it never tells you to file anything, and the disclaimer appears exactly once. Those three are compliance check eleven. The account chooser is the other half of the brief's tax agent: which account type allows which strategy, cited to FINRA and the IRS.

**Cut on:** the calculator.

---

## 11. Portfolio analysis of what you already own (8:40 – 9:30)

**On screen:** **Portfolio & Risk** → *Your holdings* editor at the top.

**Type live into the editor (or into Scout):**

```
200 AAPL at 150, 10 COST at 800, 40 SPY
```

**What must appear:** the positions valued at the run's prices; metrics for total value, the diversification score (100 × (1 − HHI)), the blended expense ratio and beta-weighted exposure; the allocation donut by ticker and the sector bar; the **before / after assignment** bar showing what each screened put would do to a ticker's share of holdings plus buying power against the profile's cap; Scout's reply with its badge.

**Narration:**

> Portfolio analysis of what I already own. Three positions typed in plain text, valued at the run's prices: allocation, sector weights, a diversification score and expense ratios. The bar that matters is this one: if the screened Nike put were assigned, Nike would go from nothing to two percent of everything I hold plus my buying power. The conservative cap is twenty-five percent, so here it does not bind, but if it did, the sizing step would cut the contracts. That is the seventh constraint, and it only exists because I told the app what I own.

On fixtures (both amounts, after the scene 4 what-if): $110,128 across AAPL 63%, SPY 28%, COST 9%; diversification score 52; the NKE 35 put takes NKE from 0% to 2% against the 25% cap. **Beta shows as blank on fixtures**, with the note "beta not computed: no dated SPY closes": the bundled closes carry no dates, and beta is now computed only on closes joined by date (W25), so it is left out rather than guessed. In a live-data take it appears for holdings with at least 60 shared daily returns, each with its 95% range, and the beta-weighted exposure is stated with its range ("estimated from daily returns").

**Action:** scroll to the constraint checks and point at the seventh row.

**Cut on:** the before / after bar.

---

## 12. Close (9:30 – 10:00)

**On screen:** return to the README diagram, cursor on the Compliance box, then fade to the repo README.

**Narration:**

> Ten intents in one conversation, routed to nine specialists with context carried across turns. Live quotes, and a run that stays honest when the data source fails. A goal checked against a computed yield, news quoted verbatim, tax mechanics illustrated with your own candidate, and a portfolio analysis that changes how the screen sizes. And one compliance agent that is the only path from the model to the screen, with a log that shows it catching a draft.
>
> This is an educational screener. It never places a trade, never connects to a brokerage, and never tells you what to do. The code, the evals, the benchmarks and the knowledge base are in the repo.

**End slate:** repo URL, "Educational screening tool. Not investment, tax or legal advice."

---

## 13. Shot list and timing

| # | Scene | Start | Length | Surface | Must-have frame |
|---|---|---|---|---|---|
| 1 | Problem | 0:00 | 0:30 | slide | three questions |
| 2 | Architecture | 0:30 | 0:20 | diagram | cursor on Compliance box |
| 3 | Conversation, 3 turns | 0:50 | 2:00 | Scout, Candidates, Under the hood | confirmation card showing `Strategies: csp` and `Experience: beginner`; glossary tooltip; three intents in trace |
| 4 | What-if, constraints | 2:50 | 0:50 | Scout, Portfolio & Risk | diff line; skipped-candidates expander |
| 5 | Live data + failure | 3:40 | 1:10 | Setup, Quality Screen, Under the hood | strip with `delayed quotes, fetched …`; 401 lines in degraded sources |
| 6 | Compliance two beats | 4:50 | 1:00 | Scout | tagged DCA answer; NVDA reframed with advisor line |
| 7 | Proof | 5:50 | 0:40 | badge expander, audit log or terminal | attempt 1 FAIL, attempt 2 PASS |
| 8 | Goals | 6:30 | 1:00 | Scout, Goals | "does not fit" verdict with levers; FIRE card with coverage line |
| 9 | News | 7:30 | 0:30 | Candidates, Trends & News, Scout | 📰 marker; brief quoting a headline with check 10 in the badge |
| 10 | Tax | 8:00 | 0:40 | Scout, Learn | basis illustration with the put's numbers; calculator |
| 11 | Holdings | 8:40 | 0:50 | Portfolio & Risk | before / after assignment bar against the cap; seventh constraint row |
| 12 | Close | 9:30 | 0:30 | diagram, README | end slate |

## 14. Things that can go wrong on camera, and what to do

| Symptom | Cause | On-camera response |
|---|---|---|
| Turn 2 confirmation card shows `Strategies: csp, leaps` or empty | intake did not carry "that" from turn 1 | Edit the field in the card, say "I'll correct it here, that is what the interrupt is for", continue. Cut the context-carry narration line in edit. Do not skip the edit: with LEAPS and PMCC left in, the table in section 0.4 no longer holds and Nike is not at the bottom for scene 3.3. |
| Portfolio & Risk says "This account is too small for this universe … fits from $960,716" | the scene 4 amount was changed to $30,000 | Narrate it, the refusal is honest. Then re-run with strategies csp and $60,000 margin for the scene 4 walk. |
| A question returns "I don't have a source for that in my knowledge base." | the question shares no content word with any document | Keep it. Say: "and when the knowledge base has nothing, it says so rather than improvising." Then rephrase with the document's own term. |
| NVDA reply passes compliance but reads like advice | guardrail gap | Stop. Do not publish. Fix prompt/config, re-run the three-times check. |
| Live run hits 429 | daily credits spent | Better footage than the 401. Record it, narrate the 429 line in 5.2. |
| Compliance retried on a normal turn | model drifted | Great. Open the badge, show the attempt count, skip to 7.2 using this thread. |
| The goal verdict is "stretch" or "fits" instead of "does not fit" | the fixture yield or the target moved | Narrate the verdict that is on screen; the point is that the verdict is computed. Fix the target in the script afterwards. |
| The news brief says "No headlines in the last N days" | Alpha Vantage rate-limited and the RSS fallback found nothing for the ticker | Say so: "the source is rate-limited and the brief says so rather than inventing a headline." Switch to fixture headlines for the take. |
| The holdings editor drops a symbol | the symbol is not in the SEC company list | Say: "ZZZZ is not a listed company, so it was dropped rather than guessed." |
| Streamlit rerun flickers the chat | normal | Pause narration a beat; cut in edit. |
