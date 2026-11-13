---
id: bottleneck-arbitrage
title: "Bottleneck arbitrage: what a supply-constraint signal can and cannot do for a short put"
source: "SEC EDGAR full-text search; Federal Reserve Bank of St. Louis, FRED; OCC disclosure document chapter X; PRD.md sections 3.7 and 4A"
url: https://www.sec.gov/edgar/search/
kind: concepts
level: intermediate
as_of: 2026-11-13
---

# Bottleneck arbitrage: a shortage signal and what it means for a short put

A **bottleneck** is the layer of a supply chain where supply cannot grow as fast as demand. The method starts from a large, well-funded theme, such as the AI data-center build-out or electrification, writes out every layer the theme needs (power, memory, cooling, networking, grid equipment) and asks of each: can supply keep up? The signs are long lead times and waitlists, rising prices, few suppliers and new capacity that takes years to build. Companies selling into that layer gain volume and pricing power at once.

This app computes a bottleneck score as its second Market Intelligence signal. It reads company filings through the SEC's EDGAR full-text search (10-K and 10-Q risk factors, 8-K releases), producer-price series from FRED and trade headlines for each layer's keywords. A language model classifies each short snippet as *tightening* or *easing* and as *customer* or *supplier*; every number after that is computed in Python from the labelled counts, the price series and a curated theme map that records how material the layer is to each company.

## A shortage is not a trade: why the signal re-orders only

The bottleneck score cannot put a stock on the list. The universe is the curated good-to-own list, every name must pass the deterministic quality gate, and the score then carries {{ranking.bottleneck_pct}} of the final ranking. The two Market Intelligence signals together are capped at 15%, behind the option's own economics and the stock's quality score. A pure play off the list appears on the board marked *not on the good-to-own list* and is skipped; a user may add it, and it then faces the same gate as everything else.

The score is also damped on purpose. For the large, profitable companies on the list the constrained layer is usually a side business, so the curated *materiality* field is low or medium and the company score is a fraction of the layer score. A *priced-in* penalty (the stock's run relative to SPY, its distance to the 52-week high, news coverage and IV rank) lowers it further when the story is already widely held.

## Why price deceleration and new supply are the risks for a short put

A put writer collects a fixed premium and takes on the stock's downside below the strike (OCC disclosure document, chapter X). Shortages are cyclical: high prices call forth new supply, and the stocks of constrained suppliers usually turn before the price data does. In memory, shipping and commodity shortages the stock often peaks while prices still rise but *more slowly*. A rich premium on a shortage name late in its cycle is the same bait as a hype premium: elevated implied volatility inflates what the writer collects and the chance of being assigned shares at a level the next quarter's prices no longer support.

The engine therefore treats two signals as penalties. `price_deceleration` measures how much the layer's price rise is slowing; `supply_response` counts easing items about new fabs, expansions and new entrants. When either exceeds its threshold, or a falsifier trips, the candidate carries the `bottleneck_easing` flag. The flag never removes a candidate from the screen. It is shown beside the row, and for a conservative profile the narrative must name it in the same sentence as the candidate. The app states the flag; it does not tell the reader what to do about it.

## What the thesis monitor shows

Each layer carries a one- or two-sentence **thesis** and a list of **falsifiers**: predicates on computed signals, such as *price deceleration above 0.5*, that must hold for a set number of consecutive daily snapshots. A daily job stores a dated snapshot of every signal (the method's journal, kept by the machine) and evaluates the falsifiers against it. The board shows each falsifier as *holding* or *tripped since* a date. When any falsifier trips, company scores in that layer are halved, the easing flag is set and the layer is labelled *thesis weakening*. These words are reports of state, not instructions. Under each layer the board links the evidence it read: the filing excerpt with its EDGAR link, the price point with its FRED series id, the headline about new capacity.

The signal study in the repository reports the historical relationship between the score and forward returns with the same caveats as the consumer-trend result; no predictive claim is made.

## Sources

- SEC, EDGAR full-text search: https://www.sec.gov/edgar/search/
- Federal Reserve Bank of St. Louis, FRED (producer-price indexes): https://fred.stlouisfed.org/
- OCC, *Characteristics and Risks of Standardized Options*, chapter X, on the risks of writing puts: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Design in force in this app: PRD.md sections 3.7 (ranking weights, signal cap) and 4A (the engine); the method is `bottleneck-arbitrage.md` at the repository root.
