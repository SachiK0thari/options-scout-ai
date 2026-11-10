# Privacy and Data-Handling Policy: OptionsScout AI

_Last updated: 2026-11-10_

OptionsScout AI is an open-source, non-commercial educational options screener. This document
describes what data the software collects, how it is used, how long it is kept, and how it is deleted.
It applies to the reference instance operated by the project author and to the code as published.

## 1. What the software is not
- It is not a commercial service. There is no revenue, advertising, paid tier, or sale of data.
- It is not investment advice and it never places trades or connects to a brokerage.
- It does not build profiles of, or infer characteristics about, any individual person.

## 2. Data entered by the user
The web form accepts a buying-power amount, a strategy choice, optional risk settings, optional ticker
lists and an optional market-data API key. These values are used for the single run that is requested.
The API key is held in memory only, is sent only as an authorisation header to the market-data
provider the user selected, and is never logged, cached, written to disk, or included in any report.

The other values **are** stored. Every conversation is saved as a thread in a local SQLite file,
`data/checkpoints.sqlite`, so that a follow-up question can refer to the earlier screen. A thread
holds what was typed, the profile (buying power, account type, risk settings, ticker lists), any
holdings and goal entered, the chat history, the screen's market snapshots and candidates, the
trend evidence of section 4, and the report. The file is not encrypted. A thread is deleted
**7 days** after its last activity, when the database next opens
(`agent.checkpoint_retention_days` in `config/settings.yaml`; `0` keeps every thread). To delete
everything at once, stop the app and remove `data/checkpoints.sqlite` and its `-wal` and `-shm`
files.

## 3. Market data
Delayed quotes, option chains and price history come from public or user-authorised providers. They are
cached locally (`data/cache.sqlite`) for at most 15 minutes for option chains and 24 hours for
earnings and dividend data; an expired entry is never served and is deleted the next time the cache
opens. The quotes and chains a screen used are also kept inside that conversation's thread (section
2) for the thread's lifetime. Market data contains no personal information.

## 4. Public social, news and filings data
The "consumer-trend" tiebreaker reads up to five public sources: public Reddit submissions, public X
posts, Wikipedia article pageviews, Google Trends search-interest indices and financial-news RSS
headlines. Each is switched on or off in `config/social_sources.yaml`. The "bottleneck" signal
(section 4.4) reads public SEC filings, public economic series and the same headline and forum
sources with its own queries, switched in `config/bottleneck_sources.yaml`. The published repository
ships with a synthetic offline corpus for both; live sources are enabled only by an operator who
supplies their own credentials and has the relevant provider's permission.

### 4.1 Reddit
- **Access:** public submissions are read either from the Arctic Shift archive
  (https://arctic-shift.photon-reddit.com, a third-party public mirror of Reddit with its own removal
  process) or through OAuth2 on the official Reddit Data API (PRAW) with an identifying user agent;
  `reddit.providers` in `config/social_sources.yaml` sets the order. Both are read-only API calls with
  an identifying user agent: no scraping of reddit.com pages, no write actions, no comments, votes,
  private messages or user-profile browsing. The archive exposes no author karma or account age, so
  those fields are empty for its posts.
- **Scope:** public submissions from the fixed list of subreddits in `config/subreddits.yaml`.
- **Fields read:** submission id, subreddit, timestamp, score, title (≤300 characters), body truncated
  to 400 characters, permalink. An opaque author id, karma and account age are read only to filter
  spam and brand-new accounts and to cap any single author's weight; they are discarded after filtering.
  Usernames are never stored, displayed or exported.
- **AI use:** a hosted language model reads each submission once, at inference time, to label product or
  brand names and sentiment. Reddit content is not used to train, fine-tune or build datasets or
  embedding stores for any model.
- **Retention:** raw submissions are held in memory during a run and in a local cache for at most one
  hour. Aggregates (daily mention counts and mean sentiment per product or brand) and up to five
  evidence items per entity (submission id, subreddit, score, date, ≤200-character excerpt, permalink)
  are stored as a dated snapshot. Every refresh writes a new snapshot built only from posts that are
  public at that moment, so content deleted or removed on Reddit does not carry into the next snapshot,
  and snapshots older than 48 hours are deleted automatically after every refresh
  (`trends.retention_hours` in `config/settings.yaml`). The trend signals a screen used, with
  their evidence items, are also kept inside that conversation's thread (section 2) and are deleted
  with it, at most 7 days after the conversation's last activity.
- **Sharing:** Reddit content is never shared, sold, redistributed, or exposed through any API or
  dataset. Reports contain only the short excerpts and links described above.
- **Removal requests:** send the submission permalink to the contact below; the item is removed from
  stored snapshots within 48 hours, and copies inside conversation threads expire with them within
  7 days. Requests covered by Reddit's own processes are escalated to Reddit.
- **Termination:** if Reddit access is revoked or the project stops, all cached and stored Reddit data
  is deleted immediately.

### 4.2 X
- **Access:** the official X API v2 search endpoints with an app bearer token supplied by the operator,
  under the X developer agreement. No scraping, no write actions, no direct messages, no follower
  graphs or profile browsing.
- **Scope:** public posts matching the fixed consumer and stock queries in `config/social_sources.yaml`,
  excluding reposts.
- **Fields read:** post id, timestamp, text truncated to 400 characters, like and repost counts,
  cashtags, and a permalink. An opaque author id, follower count and account age are read only to
  filter spam and brand-new accounts and to cap any single author's weight; handles and display names
  are never requested, stored, displayed or exported.
- **AI use, retention, sharing, removal, termination:** identical to section 4.1. X content is held in
  memory during a run, aggregated into dated snapshots with at most five ≤200-character evidence
  excerpts per entity, deleted after 48 hours (copies inside conversation threads within 7 days),
  never used for training, and removed within 48 hours on request (send the post link to the
  contact below).

### 4.3 Wikipedia pageviews, Google Trends and news RSS
Only aggregate daily view counts, aggregate 0–100 search-interest indices and public headline metadata
(title, source, date, link) are stored. No personal data is involved. Google Trends is read through an
unofficial client that the operator installs separately; no Google account is used.

### 4.4 SEC EDGAR, FRED and the bottleneck snapshots
The bottleneck-arbitrage signal reads three further kinds of public data, none of which concerns a
person:
- **SEC EDGAR full-text search** (`efts.sec.gov`, `www.sec.gov/Archives`): public company filings
  (Forms 10-K, 10-Q and 8-K). The software searches by supply-chain keywords, opens the matching
  filings and keeps windows of at most 400 characters around the keyword with the filer's ticker, the
  form, the filing date and the accession URL. Requests carry a descriptive User-Agent with the
  operator's contact address (`OPTIONS_SCOUT_CONTACT_EMAIL`), stay under the SEC's rate guidance and
  are cached locally for 24 hours. Filings are corporate documents; signatory names that appear in
  them are never extracted or stored.
- **FRED** (Federal Reserve Bank of St. Louis, `api.stlouisfed.org`): aggregate producer-price and
  industrial series, read with the operator's free API key and cached for 24 hours. Only series
  identifiers, dates and values are stored.
- **News RSS, industry subreddits and Google Trends** are read through the adapters of sections 4.1
  and 4.3 with the signal's own queries; the same fields, filters, retention and removal rules apply.
  No usernames, handles or author identifiers leave the pipeline.
- **Price-tracker CSV files** that an operator drops under `data/bottleneck_series/` are read locally,
  never fetched and never committed; their licence is the operator's responsibility.
- **AI use:** a hosted language model reads each snippet once, at inference time, to label it as a
  tightening or easing statement about a supply layer. Snippets are wrapped as data and an instruction
  inside a filing or headline cannot change the label or add a ticker; no content is used to train,
  fine-tune or build datasets or embedding stores for any model. Labels are cached locally by snippet
  hash.
- **Retention:** a dated snapshot (layer and company scores, the signals they were computed from, the
  thesis monitor's state and an evidence pack of at most five items per layer: a filing excerpt of at
  most 200 characters with its link, a series value, a headline with its link) is stored after every
  refresh in `data/bottleneck_snapshots.sqlite` and deleted automatically after **180 days**
  (`retention_days` in `config/bottleneck_score.yaml`). The longer retention, compared with the
  48 hours for social snapshots, exists because the thesis monitor and the signal study need a
  history, and is acceptable because the snapshots contain only public corporate documents,
  aggregate series and headline metadata: no personal data.
- **Sharing:** snapshots are served to the operator's own UI and API (`GET /v1/bottlenecks`) and
  appear in reports as short excerpts and links; they are never sold or redistributed.

## 5. Logs and observability
Structured logs record run ids, node timings, token counts and error messages, and are written to
the process's standard error; the software keeps no log file of its own. Credentials are removed
before anything is written: every log line, every error message stored with a run and every
data-source status passes through one redaction step that strips `apikey=`, `api_key=`, `token=`
and similar parameters, `Authorization` and bearer values, and the value of any environment
variable whose name ends in `KEY`, `TOKEN`, `SECRET` or `PASSWORD`. The HTTP client's own request
log, which would print full URLs, is switched off below warning level. The two providers that take a
key in the URL (Alpha Vantage and FRED) report errors by status code and host only. Logs never contain Reddit usernames, X handles or full post
text. A test in the suite runs a live-mode screen with fake keys and fails if any key appears in a
log line, an API response, a report or any file the run writes.

Tracing to LangSmith is **off** unless the operator sets both `OPTIONS_SCOUT_TRACING=langsmith` and
`LANGSMITH_API_KEY`; a key on its own turns nothing on. When it is on, run inputs and outputs are
hidden (`LANGSMITH_HIDE_INPUTS`, `LANGSMITH_HIDE_OUTPUTS`), so only run ids, timings and token
counts are sent, never a profile, holdings or a report.

## 6. Hosted demo
The hosted demo runs in offline fixture mode with synthetic data and does not contact Reddit, X,
Google, the SEC or FRED.

## 7. Contact
Questions or removal requests: dnesmozgawa767@gmail.com.
