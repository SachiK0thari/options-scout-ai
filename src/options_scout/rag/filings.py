"""SEC filing excerpts for ``knowledge/filings/<TICKER>.md`` (public domain text).

The pure parts (HTML → text, locating *Item 1A. Risk Factors* or a fund prospectus's *Principal
Risks*, truncating to a word budget, building the :class:`Document`) live here and are unit-tested
offline. :class:`EdgarClient` is the only thing that touches the network and is used by
``scripts/fetch_filings.py``. SEC asks for a descriptive User-Agent with a contact address and no
more than 10 requests per second; the client sends ``OPTIONS_SCOUT_CONTACT_EMAIL`` and sleeps
between requests.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Any

from options_scout.rag.models import Document

MAX_WORDS = 3000
TRUNCATION_NOTE = "[Excerpt truncated at {n:,} words; the full section is at the source URL.]"

# Fund issuers (unit investment trusts) file no 10-K; their risk disclosure is the prospectus.
ETF_CIKS: dict[str, int] = {"SPY": 884394, "QQQ": 1067839}
FORMS_10K: tuple[str, ...] = ("10-K", "10-K405", "10-KT")
FORMS_PROSPECTUS: tuple[str, ...] = ("485BPOS", "497")

_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul"}
_SKIP_TAGS = {"script", "style", "ix:header", "head", "title"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n" if tag == "br" else "\n\n")
        elif tag == "td":
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS and tag != "br":
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Visible text with paragraphs separated by blank lines; page numbers and ToC noise removed."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    raw = "".join(parser.parts).replace("\xa0", " ")
    lines: list[str] = []
    for line in raw.splitlines():
        s = " ".join(line.split())
        if not s or re.fullmatch(r"\d{1,3}", s) or s.lower() == "table of contents":
            s = ""
        if s or (lines and lines[-1]):
            lines.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# start patterns are anchored to a line start so a cross-reference inside a sentence never wins
_ITEM_1A = re.compile(r"^\s*item\s*1a\s*[.:\-—–]*\s*risk\s+factors", re.IGNORECASE | re.MULTILINE)
_ITEM_1A_END = re.compile(
    r"item\s*1b\s*[.:\-—–]*\s*unresolved\s+staff\s+comments|item\s*1c\s*[.:\-—–]*\s*cybersecurity"
    r"|item\s*2\s*[.:\-—–]*\s*properties",
    re.IGNORECASE,
)
_PRINCIPAL_RISKS = re.compile(
    r"^\s*principal\s+risks(?:\s+of\s+investing[^\n]*)?$", re.IGNORECASE | re.MULTILINE
)
_PRINCIPAL_RISKS_END = re.compile(
    r"\n\s*(?:performance|fund\s+performance|portfolio\s+holdings\s+information|management\b"
    r"|purchase\s+and\s+sale\s+of\s+(?:fund\s+)?shares|additional\s+information)",
    re.IGNORECASE,
)


def extract_section(text: str, start: re.Pattern[str], end: re.Pattern[str]) -> str | None:
    """Longest span between a start match and the first end match after it. Tables of contents
    produce short spans, the real section produces the long one."""
    best: str | None = None
    for s in start.finditer(text):
        e = end.search(text, s.end())
        span = text[s.start() : e.start()] if e else text[s.start() :]
        if best is None or len(span) > len(best):
            best = span
    return best.strip() if best and len(best.split()) >= 200 else None


def extract_item_1a(text: str) -> str | None:
    return extract_section(text, _ITEM_1A, _ITEM_1A_END)


def extract_principal_risks(text: str) -> str | None:
    return extract_section(text, _PRINCIPAL_RISKS, _PRINCIPAL_RISKS_END)


def truncate_words(text: str, max_words: int = MAX_WORDS) -> str:
    words = text.split()
    note_words = len(TRUNCATION_NOTE.format(n=max_words).split())
    if len(words) <= max_words:
        return text
    budget = max_words - note_words
    cut = " ".join(words[:budget])
    end = max(cut.rfind(". "), cut.rfind(".\n"))
    if end > len(cut) // 2:
        cut = cut[: end + 1]
    # keep paragraph breaks that survived the word split
    kept = text[: text.find(cut.split()[-1], len(cut) - 200) + len(cut.split()[-1])]
    body = kept if kept.strip() and kept.count("\n") >= cut.count("\n") else cut
    return body.rstrip() + "\n\n" + TRUNCATION_NOTE.format(n=max_words)


@dataclass(frozen=True)
class FilingRef:
    cik: int
    company: str
    form: str
    filed: date
    accession: str
    primary_document: str

    @property
    def url(self) -> str:
        acc = self.accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{self.cik}/{acc}/{self.primary_document}"

    @property
    def index_url(self) -> str:
        return f"https://www.sec.gov/Archives/edgar/data/{self.cik}/{self.accession}-index.htm"


def filing_document(ticker: str, ref: FilingRef, excerpt: str, *, section: str) -> Document:
    """Build the knowledge document; the whole document (intro + excerpt) stays ≤ ``MAX_WORDS``."""
    ticker = ticker.upper()
    is_10k = ref.form in FORMS_10K
    what = "Item 1A, Risk Factors" if is_10k else "Principal Risks"
    intro = (
        f"Excerpt from the {ref.form} filed by {ref.company} with the U.S. Securities and "
        f"Exchange Commission on {ref.filed.isoformat()} ({section}). SEC filings are public "
        f"domain; this is a verbatim excerpt limited to {MAX_WORDS:,} words for the knowledge base "
        "and is not current-year guidance. Risk factors describe what could go wrong with the "
        "business, which is exactly what a put seller who may be assigned shares, or a LEAPS buyer "
        f"who owns upside for a year or more, should read before trading options on {ticker}."
    )
    head = f"# {ticker}: {ref.company} {ref.form} {what}\n\n{intro}\n\n## {what} (excerpt)\n\n"
    body = head + truncate_words(excerpt, MAX_WORDS - len(head.split()))
    return Document(
        id=f"filing-{ticker.lower()}",
        title=f"{ref.company} {ref.form}: {what} ({ref.filed.year})",
        source=f"SEC EDGAR {ref.form} filed {ref.filed.isoformat()}",
        url=ref.url,
        kind="filings",
        as_of=ref.filed,
        body=body,
        path=f"knowledge/filings/{ticker}.md",
    )


class EdgarClient:
    """Minimal EDGAR reader: submissions JSON → latest filing of a form → primary document."""

    def __init__(self, contact: str | None = None, min_interval: float = 0.2) -> None:
        import httpx

        contact = contact or os.environ.get("OPTIONS_SCOUT_CONTACT_EMAIL", "contact@example.com")
        self._client = httpx.Client(
            timeout=60.0,
            headers={
                "User-Agent": f"options-scout-ai/0.1 {contact}",
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=True,
        )
        self._min_interval = min_interval
        self._last = 0.0

    def _get(self, url: str) -> Any:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        resp = self._client.get(url)
        self._last = time.monotonic()
        resp.raise_for_status()
        return resp

    def latest_filing(self, cik: int, forms: tuple[str, ...]) -> FilingRef | None:
        data = self._get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
        recent = data["filings"]["recent"]
        rows = zip(
            recent["form"],
            recent["filingDate"],
            recent["accessionNumber"],
            recent["primaryDocument"],
            strict=False,
        )
        for form, filed, acc, doc in rows:  # newest first
            if form in forms and doc:
                return FilingRef(
                    cik=cik,
                    company=str(data["name"]).strip(),
                    form=form,
                    filed=date.fromisoformat(filed),
                    accession=acc,
                    primary_document=doc,
                )
        return None

    def document_text(self, ref: FilingRef) -> str:
        return html_to_text(self._get(ref.url).text)

    def close(self) -> None:
        self._client.close()
