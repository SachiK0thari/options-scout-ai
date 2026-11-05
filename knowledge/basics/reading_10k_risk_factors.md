---
id: reading-10k-risk-factors
title: "Reading a 10-K's risk factors (Item 1A) as a put seller who may own the shares"
source: "SEC EDGAR full-text search; Form 10-K, Item 1A Risk Factors (Regulation S-K Item 105)"
url: https://www.sec.gov/edgar/search/
kind: basics
level: beginner
as_of: 2026-11-04
---

# Reading a 10-K's risk factors

A **Form 10-K** is the annual report that every company with securities registered with the SEC must file. It contains the audited financial statements, a description of the business, management's discussion of results, and a section the SEC requires under Regulation S-K: **Item 1A, Risk Factors**. Item 1A is where the company lists, in its own words and under legal liability for omissions, the things that could materially hurt its business, its stock price or both. It is the one part of a filing written to tell the reader what could go wrong.

## Where to find it

All filings are free on the SEC's **EDGAR** system. The full-text search at sec.gov/edgar/search lets a reader type a company name or ticker and a phrase, restrict to form type 10-K, and jump to the matching passage. A search for a ticker with the phrase "risk factors" and a date range of the past year returns the latest annual report; opening the document and finding "Item 1A" in the table of contents lands on the section. Large companies' risk factor sections run from a few pages to more than twenty.

## How to read it as a put seller

A cash-secured put writer has agreed to buy the shares at the strike if the price falls below it. The question Item 1A answers is: what would have to happen for that fall to be large and lasting rather than small and temporary? Three habits help.

First, read for change. Companies repeat most risk factors year after year, so the sentences that are new or newly specific carry the information. A risk that moved from "we may face competition" to "a named competitor launched a product in our largest segment" is a risk that has arrived.

Second, map each risk to the gap between strike and price. A put sold 10% below the market with 40 days to expiry is exposed to events that can move the stock more than 10% in six weeks: a regulatory decision, a lost customer that accounts for a stated percentage of revenue, a debt maturity. Item 1A often states the size of a concentration ("one customer accounted for 23% of net sales"), and that number is what a 30% stress test is about.

Third, read the sections on customer concentration, debt, litigation and key-person dependence as an owner would, because assignment makes the writer an owner. The premium does not change the answer to "would I want to hold this company through the risk it just described".

## What can go wrong

Risk factors are written by lawyers to be comprehensive, so they list everything from pandemics to the weather, and the signal is buried in boilerplate. They are also backward-looking by the time they are read: a 10-K filed in February describes risks as of the fiscal year end. The section cannot tell a reader the probability of any risk, only its existence. And no filing describes the risk of a market-wide decline, which is the one most likely to cause assignment across several puts at once.

## Where this shows up in OptionsScout

The knowledge base includes a `knowledge/filings/` collection with one document per name in the quality universe, each a verbatim excerpt of up to 3,000 words from that company's latest 10-K Item 1A, built by a script that reads the filing from EDGAR, records the filing date and the accession URL in the front-matter, and labels the document `kind: filings`, `level: advanced`. When the Scout chat answers a question about a candidate's risks, the retrieval step can cite the company's own words with the EDGAR URL, and the Compliance agent checks that any risk the narrative names appears in a retrieved passage. The excerpts are not current-year guidance and are refreshed when the next 10-K is filed.

## Sources

- SEC EDGAR full-text search: https://www.sec.gov/edgar/search/
- SEC investor.gov, Stocks, on the information available to shareholders: https://www.investor.gov/introduction-investing/investing-basics/investment-products/stocks
- OptionsScout `knowledge/filings/` collection, one Item 1A excerpt per universe name, each citing its own EDGAR filing URL.
