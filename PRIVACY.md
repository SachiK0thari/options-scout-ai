# Privacy and Data-Handling Policy: OptionsScout AI

_Last updated: 2026-10-28_

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
Profiles are not persisted unless the user explicitly opts in.

## 3. Market data
Delayed quotes, option chains and price history come from public or user-authorised providers. They are
cached locally (SQLite) for at most 15 minutes for option chains and 24 hours for earnings and
dividend data. Market data contains no personal information.

## 4. Public social and news data
The "consumer-trend" tiebreaker reads three public sources: Wikipedia article pageviews, financial-news
RSS headlines, and public Reddit submissions. The published repository ships with a synthetic offline
corpus; live sources are enabled only by an operator who supplies their own credentials and has the
relevant provider's permission.

### 4.1 Reddit
- **Access:** OAuth2 through the official Reddit Data API (PRAW) with an identifying user agent.
  No scraping, no write actions, no comments, votes, private messages or user-profile browsing.
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
  (`trends.retention_hours` in `config/settings.yaml`).
- **Sharing:** Reddit content is never shared, sold, redistributed, or exposed through any API or
  dataset. Reports contain only the short excerpts and links described above.
- **Removal requests:** send the submission permalink to the contact below; the item is removed from
  stored snapshots within 48 hours. Requests covered by Reddit's own processes are escalated to Reddit.
- **Termination:** if Reddit access is revoked or the project stops, all cached and stored Reddit data
  is deleted immediately.

### 4.2 Wikipedia pageviews and news RSS
Only aggregate daily view counts and public headline metadata (title, source, date, link) are stored.
No personal data is involved.

## 5. Logs and observability
Structured logs and traces record run ids, node timings, token counts and error messages. They never
contain API keys, Reddit usernames, or full post text.

## 6. Hosted demo
The hosted demo runs in offline fixture mode with synthetic data and does not contact Reddit.

## 7. Contact
Questions or removal requests: dnesmozgawa767@gmail.com.
