"""Fetch SEC risk-factor excerpts into knowledge/filings/<TICKER>.md (public domain text).

Usage: OPTIONS_SCOUT_CONTACT_EMAIL=you@example.com .venv/bin/python scripts/fetch_filings.py [TICKER ...]

Default tickers are the ten demo fixtures. Tickers are resolved to a CIK through the existing
``social/adapters/sec.py`` adapter (fixture copy of SEC's company_tickers.json, live refresh when
OPTIONS_SCOUT_DATA_MODE=live); fund issuers that file no 10-K (SPY, QQQ) fall back to the
"Principal Risks" section of their latest prospectus (485BPOS). Each excerpt is capped at 3,000
words. Network access is the only reason this is a script and not part of `make index`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from options_scout.config import load_config, load_env
from options_scout.data.fixtures import DEMO_TICKERS
from options_scout.rag.corpus import render_document
from options_scout.rag.filings import (
    ETF_CIKS,
    FORMS_10K,
    FORMS_PROSPECTUS,
    PREDECESSOR_CIKS,
    EdgarClient,
    extract_item_1a,
    extract_principal_risks,
    filing_document,
)
from options_scout.social.adapters.sec import SECAdapter


def main(argv: list[str]) -> int:
    load_env()
    cfg = load_config()
    tickers = [t.upper() for t in argv] or list(DEMO_TICKERS)
    sec = SECAdapter(
        cfg.settings.data_mode,
        cfg.paths.fixtures_dir / "sec_company_tickers.json",
        cfg.paths.cache_db.parent / "sec_company_tickers.json",
    )
    out_dir = cfg.rag.knowledge_dir / "filings"
    out_dir.mkdir(parents=True, exist_ok=True)
    client = EdgarClient()
    failures = 0
    try:
        for ticker in tickers:
            company = sec.companies().get(ticker)
            cik = company.cik if company else ETF_CIKS.get(ticker)
            if cik is None:
                print(f"{ticker}: no CIK known (not in company_tickers.json, not an ETF we map)")
                failures += 1
                continue
            ref = client.latest_filing(cik, FORMS_10K)
            if ref is None and ticker in PREDECESSOR_CIKS:  # new registrant, no 10-K yet
                cik = PREDECESSOR_CIKS[ticker]
                ref = client.latest_filing(cik, FORMS_10K)
            section = "Item 1A"
            excerpt = extract_item_1a(client.document_text(ref)) if ref is not None else None
            if excerpt is None:  # fund issuers: full prospectus first, then supplements
                section = "Principal Risks"
                for form in FORMS_PROSPECTUS:
                    ref = client.latest_filing(cik, (form,))
                    if ref is not None:
                        excerpt = extract_principal_risks(client.document_text(ref))
                    if excerpt is not None:
                        break
            if ref is None or excerpt is None:
                print(f"{ticker}: no 10-K Item 1A or prospectus Principal Risks section found")
                failures += 1
                continue
            doc = filing_document(ticker, ref, excerpt, section=section)
            path = out_dir / f"{ticker}.md"
            path.write_text(render_document(doc), encoding="utf-8")
            print(
                f"{ticker}: {ref.form} filed {ref.filed} → {path.relative_to(cfg.root)} ({doc.word_count:,} words)"
            )
    finally:
        client.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
