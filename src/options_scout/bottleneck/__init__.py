"""Bottleneck Arbitrage engine (PRD section 4A): the second Market Intelligence signal.

It re-orders stocks that already passed the quality gate; it never adds one. Step 11.1 shipped the
curated theme map (``themes.py``), its typed loader and the configuration; step 11.2 the adapters
(``adapters/``), the snippet windowing and dedupe (``snippets.py``), the source registry
(``sources.py``) and the corpus fetcher with its CLI (``pipeline.py``). Classification, signals,
the score and the thesis monitor follow in step 11.3; the agent node in 11.4.
"""
