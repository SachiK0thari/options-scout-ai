"""Phase 10 step 10.2: knowledge base and retrieval layer (PRD section 5.6). Offline only."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from options_scout.config import AppConfig
from options_scout.rag import filings
from options_scout.rag.chunking import ChunkParams, chunk_document, chunk_documents, split_sections
from options_scout.rag.corpus import load_corpus, parse_document, render_document
from options_scout.rag.embeddings import HashEmbedder, make_embedder, tokenize
from options_scout.rag.index import build_index
from options_scout.rag.models import Citation, Document, quote_of
from options_scout.rag.retriever import KnowledgeRetriever, chunk_params, format_result
from options_scout.rag.rules_docs import prd_sections, render_rules_docs, stale_rules_docs
from options_scout.rag.store import KnowledgeStore
from tests.conftest import REPO_ROOT

KNOWLEDGE = REPO_ROOT / "knowledge"

# question → document id whose chunk must appear in the top-k (PRD: 10 sample questions)
SAMPLE_QUESTIONS: list[tuple[str, str]] = [
    ("what is assignment", "assignment"),
    ("what is a cash-secured put", "cash-secured-put"),
    ("how does a poor man's covered call work", "pmcc"),
    ("what does delta measure", "delta"),
    ("explain theta and time decay", "theta"),
    ("what is extrinsic value of a LEAPS", "extrinsic-value"),
    ("what is IV rank", "iv-rank"),
    ("how is the Reg T margin requirement for a naked put computed", "reg-t-margin"),
    ("why is hype a risk for short puts", "hype-short-puts"),
    ("what is a bottleneck in a supply chain", "bottleneck-arbitrage"),  # Phase 11, step 11.5
    ("how does the quality gate work", "quality-gate"),
    ("what are the CSP screener rules in force", "rules-3-3-csp-screener"),
    ("Apple risk factors supply chain", "filing-aapl"),
]


@pytest.fixture(scope="module")
def corpus() -> list[Document]:
    return load_corpus(KNOWLEDGE)


@pytest.fixture(scope="module")
def retriever(tmp_path_factory: pytest.TempPathFactory) -> KnowledgeRetriever:
    """Hash-embedder index of the committed corpus in a temp store (never touches data/)."""
    from options_scout.config import load_config

    cfg = load_config(REPO_ROOT)
    rag = cfg.rag.model_copy(
        update={"embedder": "hash", "index_db": tmp_path_factory.mktemp("rag") / "k.sqlite"}
    )
    embedder = make_embedder(rag)
    chunks = chunk_documents(load_corpus(rag.knowledge_dir), chunk_params(rag))
    store = KnowledgeStore(rag.index_db)
    store.rebuild(chunks, embedder)
    return KnowledgeRetriever(store, embedder, rag)


# ------------------------------------------------------------------------------------ corpus


def test_corpus_has_the_five_committed_collections(corpus: list[Document]) -> None:
    kinds = {d.kind for d in corpus}
    assert kinds == {"concepts", "basics", "tax", "rules", "filings"}
    ids = [d.id for d in corpus]
    assert len(ids) == len(set(ids))


def test_concept_docs_meet_the_prd_contract(corpus: list[Document]) -> None:
    concepts = [d for d in corpus if d.kind == "concepts"]
    assert len(concepts) >= 18  # "≈ 20 docs"
    for d in concepts:
        assert 300 <= d.word_count <= 800, (d.id, d.word_count)
        has_url = d.url.startswith("http") or "http" in d.body
        assert has_url, f"{d.id} cites no primary-source URL"
        assert isinstance(d.as_of, date)
    required = {
        "quality-gate",
        "hype-short-puts",
        "bottleneck-arbitrage",
        "cash-secured-put",
        "assignment",
        "leaps",
        "pmcc",
    }
    assert required <= {d.id for d in concepts}


def test_filings_cover_the_demo_tickers_under_the_word_cap(corpus: list[Document]) -> None:
    from options_scout.data.fixtures import DEMO_TICKERS

    found = {d.id for d in corpus if d.kind == "filings"}
    assert found >= {f"filing-{t.lower()}" for t in DEMO_TICKERS}
    for d in corpus:
        if d.kind == "filings":
            assert re.fullmatch(r"filing-[a-z]+", d.id), d.id
            assert d.level == "advanced", d.id
            assert d.word_count <= filings.MAX_WORDS, (d.id, d.word_count)
            assert d.url.startswith("https://www.sec.gov/Archives/edgar/data/")


def test_parse_and_render_round_trip() -> None:
    text = (
        "---\nid: demo-doc\ntitle: Demo\nsource: me\nurl: https://example.org\nkind: concepts\n"
        "as_of: 2026-11-03\n---\n\n# Demo\n\nBody.\n"
    )
    doc = parse_document(text, path="x.md")
    assert doc.id == "demo-doc" and doc.as_of == date(2026, 11, 3)
    assert parse_document(render_document(doc)).body == doc.body
    with pytest.raises(ValueError, match="front-matter missing"):
        parse_document("---\nid: a\n---\nbody", path="y.md")


def test_committed_rules_docs_are_not_stale(config: AppConfig) -> None:
    stale = stale_rules_docs(config)
    assert stale == [], f"run `make index` to regenerate knowledge/rules: {stale}"


def test_rules_docs_carry_prd_text_and_config_values(config: AppConfig) -> None:
    rendered = render_rules_docs(config, today=date(2026, 1, 1))
    assert set(rendered) == {
        "allocation.md",
        "constraints.md",
        "csp_screener.md",
        "leaps_screener.md",
        "pmcc_rules.md",
        "formulas.md",
        "quality_gate.md",
        "goal_feasibility.md",
        "news_flags.md",
        "holdings_concentration.md",
    }
    csp = rendered["csp_screener.md"]
    assert "## Specification (PRD.md section 3.3)" in csp
    assert f"| Open interest | ≥ {config.rules.csp.min_open_interest:,} |" in csp
    gate = rendered["quality_gate.md"]
    assert "| Price | ≥ $20 |" in gate and "| COST |" in gate
    sections = prd_sections((REPO_ROOT / "PRD.md").read_text(encoding="utf-8"))
    assert {f"3.{n}" for n in range(1, 11)} <= set(sections)
    assert "d1 = (ln(S/K)" in sections["3.6"][1]
    # 3.7 ends where 3.8 starts: the quality gate document does not swallow the Phase 12 rules
    assert "Goal feasibility" not in gate and "### 3.8" not in sections["3.7"][1]


def test_phase_12_rules_docs_carry_the_values_in_force(config: AppConfig) -> None:
    rendered = render_rules_docs(config, today=date(2026, 1, 1))
    goal = rendered["goal_feasibility.md"]
    assert "id: rules-3-8-goal-feasibility" in goal
    assert "## Specification (PRD.md section 3.8)" in goal and "`does_not_fit`" in goal
    caps = config.goals.max_assumed_return
    row = " | ".join(f"{caps[p] * 100:g}%" for p in ("conservative", "balanced", "aggressive"))
    assert f"is `does_not_fit`) | {row} |" in goal
    assert f"Withdrawal rate: {config.goals.withdrawal_rate * 100:g}%" in goal

    news = rendered["news_flags.md"]
    assert "id: rules-3-9-news-flags" in news
    for flag in ("earnings_within_dte", "ex_dividend_before_expiry", "ex_dividend_capture_window"):
        assert f"`{flag}`" in news
    assert f"| Stale marker | older than {config.news.stale_days} days |" in news
    assert f"within {config.news.capture_window_days} days before a short call's expiry" in news

    held = rendered["holdings_concentration.md"]
    assert "id: rules-3-10-holdings-concentration" in held
    assert "url: PRD.md#310-holdings-and-concentration-after-assignment" in held
    cons = config.risk.constraints
    row = " | ".join(
        f"{c.max_ticker_concentration_after_assignment * 100:g}%" for c in cons.values()
    )
    assert f"| Max ticker concentration after assignment | {row} |" in held
    assert f"| SPY | {config.holdings.expense_ratios_pct['SPY']:g}% |" in held


# ---------------------------------------------------------------------------------- chunking


def _doc(body: str, doc_id: str = "demo-doc") -> Document:
    return Document(
        id=doc_id,
        title="Demo",
        source="test",
        url="https://example.org",
        kind="concepts",
        as_of=date(2026, 11, 3),
        body=body,
    )


def test_chunk_ids_are_stable_and_sequential(corpus: list[Document]) -> None:
    params = ChunkParams(chunk_tokens=400, overlap=0.15)
    first = chunk_documents(corpus, params)
    second = chunk_documents(load_corpus(KNOWLEDGE), params)
    assert [c.id for c in first] == [c.id for c in second]
    assert [c.text for c in first] == [c.text for c in second]
    assert len(first) == len({c.id for c in first})
    for c in first:
        assert re.fullmatch(rf"{re.escape(c.doc_id)}#\d+", c.id)
    for doc in corpus:
        ns = [c.n for c in first if c.doc_id == doc.id]
        assert ns == list(range(len(ns)))


def test_chunks_respect_the_word_budget_and_overlap() -> None:
    words = " ".join(f"w{i}" for i in range(1000))
    chunks = chunk_document(
        _doc(f"# Long\n\n{words}\n"), ChunkParams(chunk_tokens=400, overlap=0.15)
    )
    max_words = int(400 * 0.75)
    assert len(chunks) > 1
    assert all(len(c.text.split()) <= max_words for c in chunks)
    overlap = int(max_words * 0.15)  # 45 words carried over into the next window
    assert chunks[0].text.split()[-overlap:] == chunks[1].text.split()[:overlap]
    assert chunks[0].heading == "Long" and chunks[0].context == "Demo › Long"


def test_sections_follow_headings_and_sources_are_skipped() -> None:
    body = "Intro.\n\n## A\n\nalpha text\n\n### A1\n\nnested\n\n## Sources\n\n- https://x\n"
    secs = split_sections(body)
    assert [s.heading for s in secs] == ["", "A", "A › A1", "Sources"]
    chunks = chunk_document(_doc(body))
    assert [c.heading for c in chunks] == ["", "A", "A › A1"]
    assert chunks[0].quote == "Intro."


def test_quote_cuts_at_a_sentence() -> None:
    long = "First sentence here. " * 30
    q = quote_of(long, limit=100)
    assert q.endswith(".") and len(q) <= 100
    assert quote_of("short") == "short"


# -------------------------------------------------------------------------------- embeddings


def test_hash_embedder_is_deterministic_and_normalised() -> None:
    e1, e2 = HashEmbedder(512), HashEmbedder(512)
    a = e1.embed(["Cash-secured put collateral", "LEAPS extrinsic value"])
    b = e2.embed(["Cash-secured put collateral", "LEAPS extrinsic value"])
    assert a.dtype == np.float32 and a.shape == (2, 512)
    assert np.array_equal(a, b)
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0)
    assert float(a[0] @ a[1]) < 0.5
    same = e1.embed(["cash secured put collateral"])[0]
    assert float(same @ a[0]) > 0.5  # tokenizer lower-cases and splits on hyphens
    assert np.all(e1.embed(["the and of"])[0] == 0)  # only stopwords → zero vector


def test_tokenizer_drops_stopwords_and_keeps_numbers() -> None:
    assert tokenize("What is the 30-day HV30 limit? 35%") == ["30-day", "hv30", "limit", "35"]


def test_make_embedder_honours_config(config: AppConfig) -> None:
    emb = make_embedder(config.rag.model_copy(update={"embedder": "hash", "hash_dimensions": 256}))
    assert emb.name == "hash-256" and emb.dimensions == 256


# ------------------------------------------------------------------------------------- store


def test_store_rebuild_is_idempotent(tmp_path: Path, corpus: list[Document]) -> None:
    chunks = chunk_documents(corpus[:5])
    emb = HashEmbedder(256)
    store = KnowledgeStore(tmp_path / "k.sqlite")
    n1 = store.rebuild(chunks, emb)
    m1 = store.meta()
    v1 = store.dense_scores(emb.embed(["assignment"])[0]).copy()
    n2 = store.rebuild(chunks, emb)
    assert n1 == n2 == len(store) == len(chunks)
    assert store.meta() == m1 and store.is_current(chunks, emb)
    assert np.array_equal(v1, store.dense_scores(emb.embed(["assignment"])[0]))
    assert [c.id for c in store.chunks()] == [c.id for c in chunks]
    assert store.get(chunks[0].id) == chunks[0]
    assert not store.is_current(chunks[:-1], emb)  # different corpus → stale
    store.close()
    reopened = KnowledgeStore(tmp_path / "k.sqlite")
    assert len(reopened) == len(chunks) and reopened.is_current(chunks, emb)


def test_build_index_summary(tmp_path: Path, config: AppConfig) -> None:
    rag = config.rag.model_copy(update={"embedder": "hash", "index_db": tmp_path / "k.sqlite"})
    cfg = config.model_copy(update={"rag": rag})
    summary = build_index(cfg)
    assert summary["documents"] >= 30 and summary["chunks"] > summary["documents"]  # type: ignore[operator]
    assert summary["embedder"] == f"hash-{config.rag.hash_dimensions}"
    assert float(summary["seconds"]) < 10.0  # type: ignore[arg-type]
    assert (tmp_path / "k.sqlite").exists()


# --------------------------------------------------------------------------------- retriever


@pytest.mark.parametrize(("question", "doc_id"), SAMPLE_QUESTIONS)
def test_retriever_returns_the_labelled_document(
    retriever: KnowledgeRetriever, question: str, doc_id: str
) -> None:
    result = retriever.retrieve(question)
    assert not result.empty
    assert len(result.hits) == retriever.cfg.top_k
    assert doc_id in {h.chunk.doc_id for h in result.hits}, format_result(result)
    assert [h.rank for h in result.hits] == list(range(1, len(result.hits) + 1))
    assert result.hits[0].fused >= result.hits[-1].fused


def test_floor_returns_empty_for_unrelated_queries(retriever: KnowledgeRetriever) -> None:
    for q in ("xqzv blorptastic", "the and of", ""):
        result = retriever.retrieve(q)
        assert result.empty and result.citations() == []
        assert "no chunks above the similarity floor" in format_result(result) or q == ""


def test_lexical_embedder_needs_a_shared_content_word(retriever: KnowledgeRetriever) -> None:
    """Step 10.8: no word of the question occurs anywhere in the corpus, so with the hash embedder
    any cosine above the floor is collision noise and the retriever must return nothing (the
    Education agent then answers with the fixed no-source sentence)."""
    assert retriever.cfg.embedder == "hash" and retriever.cfg.shared_term_required
    for q in ("what is the weather in Boston", "how does an iron condor work"):
        result = retriever.retrieve(q)
        assert result.empty, format_result(result)
    # a question that does share content words is unaffected
    assert not retriever.retrieve("what is assignment").empty


def test_kind_filter_is_respected(retriever: KnowledgeRetriever) -> None:
    queries = {
        "concepts": "volatility risk",
        "basics": "what is a stock",
        "tax": "wash sale after assignment",
        "rules": "volatility risk",
        "filings": "volatility risk",
    }
    for kind, query in queries.items():
        result = retriever.retrieve(query, kind=kind)  # type: ignore[arg-type]
        assert not result.empty and all(h.chunk.kind == kind for h in result.hits), kind
        assert result.kind == kind
    assert retriever.retrieve("volatility", kind="evidence").empty  # nothing indexed yet


def test_title_head_match_scores_the_subject_not_the_body() -> None:
    from options_scout.rag.retriever import title_head, title_head_match

    assert title_head("Cash-secured put (CSP): selling a put while holding the cash") == (
        "Cash-secured put"
    )
    assert (
        title_head("The wheel: cash-secured put, assignment, covered call, repeat") == "The wheel"
    )
    q = frozenset(tokenize("what is a cash-secured put"))
    assert title_head_match("Cash-secured put (CSP): selling a put", q) == 1.0
    assert title_head_match("The wheel: cash-secured put, assignment", q) == 0.0
    assert title_head_match(
        "Early assignment and dividends: when …", frozenset({"assignment"})
    ) == (pytest.approx(1 / 3))
    assert title_head_match("", q) == 0.0


def test_definitional_questions_cite_the_named_document_first(
    retriever: KnowledgeRetriever,
) -> None:
    """The Education agent quotes [S1]; a question that names a concept must get that concept's
    own document first, not another document that discusses it (the title-head boost)."""
    ambiguous = {  # these name two concepts; either document may lead
        "what is extrinsic value of a LEAPS",
        "how is the Reg T margin requirement for a naked put computed",
    }
    for question, doc_id in SAMPLE_QUESTIONS:
        if doc_id.startswith(("rules-", "filing-")) or question in ambiguous:
            continue
        hits = retriever.retrieve(question).hits
        assert hits and hits[0].chunk.doc_id == doc_id, (question, [h.chunk.id for h in hits])


def test_max_level_filter_caps_the_reading_level(retriever: KnowledgeRetriever) -> None:
    """A beginner cap never returns an advanced chunk; the result records the cap."""
    for cap, allowed in (
        ("beginner", {"beginner"}),
        ("intermediate", {"beginner", "intermediate"}),
    ):
        result = retriever.retrieve("what is a cash-secured put", max_level=cap)  # type: ignore[arg-type]
        assert result.max_level == cap
        assert all(h.chunk.level in allowed for h in result.hits), [h.chunk.id for h in result.hits]
    uncapped = retriever.retrieve("Reg T margin requirement for a naked put")
    assert any(h.chunk.level == "advanced" for h in uncapped.hits)
    capped = retriever.retrieve("Reg T margin requirement for a naked put", max_level="beginner")
    assert all(h.chunk.level == "beginner" for h in capped.hits)


def test_basics_and_tax_docs_meet_the_phase_12_contract(corpus: list[Document]) -> None:
    """Phase 12 step 12.1: beginner basics and tax/account documents, each cited and levelled."""
    basics = [d for d in corpus if d.kind == "basics"]
    tax = [d for d in corpus if d.kind == "tax"]
    assert len(basics) >= 25 and len(tax) >= 12, (len(basics), len(tax))
    disclaimer = "This is education, not tax advice"
    for d in basics + tax:
        assert 300 <= d.word_count <= 800, (d.id, d.word_count)
        assert d.url.startswith("http"), d.id
        assert d.level in ("beginner", "intermediate", "advanced"), d.id
        assert "Where this shows up in OptionsScout" in d.body, d.id
        if d.kind == "tax":
            assert disclaimer in d.body, d.id
    assert (
        sum(d.level == "beginner" for d in basics) >= len(basics) // 2
    )  # basics are for beginners
    required = {
        "compound-growth",
        "diversification",
        "concentration-risk",
        "risk-profiles",
        "fire-and-safe-withdrawal",
        "savings-rate",
        "account-types-for-options",
        "wash-sales-and-options",
        "section-1256-contracts",
    }
    assert required <= {d.id for d in basics + tax}


def test_top_k_and_citations(retriever: KnowledgeRetriever) -> None:
    result = retriever.retrieve("what is a cash-secured put", top_k=3)
    assert len(result.hits) == 3
    cites = result.citations()
    assert all(isinstance(c, Citation) for c in cites)
    assert cites[0].chunk_id == result.hits[0].chunk.id and cites[0].url
    assert cites[0].quote and not cites[0].quote.startswith(result.hits[0].chunk.title)
    block = result.sources_block()
    assert block.startswith("[S1] ") and "[S3] " in block


def test_in_memory_collection_for_run_evidence(config: AppConfig) -> None:
    docs = [
        _doc("# Costco\n\nReddit users rave about the Kirkland rotisserie chicken deal.", "ev-1"),
        _doc("# Nike\n\nNews: Nike cuts guidance on weak sneaker demand.", "ev-2"),
    ]
    chunks = chunk_documents(docs)
    r = KnowledgeRetriever.in_memory(chunks, HashEmbedder(512), config.rag)
    hit = r.retrieve("why is Costco rotisserie chicken trending")
    assert hit.hits and hit.hits[0].chunk.doc_id == "ev-1"


# ----------------------------------------------------------------------------------- filings


def test_item_1a_extraction_prefers_the_long_section() -> None:
    toc = "Item 1A. Risk Factors 12\nItem 1B. Unresolved Staff Comments 30\n"
    body_words = " ".join(["risk"] * 250)
    html = (
        "<html><body><p>" + toc.replace("\n", "</p><p>") + "</p>"
        f"<p>Item 1A. Risk Factors</p><p>{body_words}</p><p>More risks.</p>"
        "<p>Item 1B. Unresolved Staff Comments</p><p>None.</p></body></html>"
    )
    text = filings.html_to_text(html)
    section = filings.extract_item_1a(text)
    assert section is not None
    assert section.startswith("Item 1A. Risk Factors") and section.endswith("More risks.")
    assert (
        filings.extract_item_1a("Item 1A. Risk Factors\nshort\nItem 1B. Unresolved Staff Comments")
        is None
    )


def test_item_1a_extraction_falls_back_to_a_bare_risk_factors_heading() -> None:
    """McDonald's and Honeywell keep "Item 1A" only in a cross-reference index."""
    body = " ".join(["Demand for our products may fall if consumer spending weakens."] * 40)
    text = (
        "Part I\n\nItem 1 Business\n\nPage 3\n\nItem 1A Risk Factors\n\nPage 27\n\n"
        "Item 1B Unresolved Staff Comments Not applicable\n\nItem 1C Cybersecurity\n\nPage 40\n\n"
        "Risk Factors\n\nCybersecurity\n\nLegal Proceedings\n\n"  # a second index, as MCD prints
        "RISK FACTORS\n\nCautionary Statement\n\n"
        f"Risk Factors\n\nOur business results are subject to a variety of risks. {body}\n\n"
        "Unresolved Staff Comments\n\nNone.\n\nProperties\n\nWe own restaurants."
    )
    section = filings.extract_item_1a(text)
    assert section is not None
    # the last heading wins: not the index line, not the page banner above the cautionary note
    assert section.startswith("Risk Factors\n\nOur business results")
    assert "Unresolved Staff Comments" not in section and "Cautionary" not in section
    # the same text with only the index line (no real section) still returns nothing
    assert filings.extract_item_1a("Item 1A Risk Factors\n\nPage 27\n\nItem 1B") is None


def test_truncate_words_keeps_the_budget_and_notes_it() -> None:
    text = " ".join(f"word{i}." for i in range(5000))
    out = filings.truncate_words(text, 3000)
    assert len(out.split()) <= 3000
    assert out.endswith(filings.TRUNCATION_NOTE.format(n=3000))
    assert filings.truncate_words("tiny text", 3000) == "tiny text"


def test_filing_document_stays_within_the_cap() -> None:
    ref = filings.FilingRef(
        cik=320193,
        company="Apple Inc.",
        form="10-K",
        filed=date(2026, 11, 3),
        accession="0000320193-26-000026",
        primary_document="aapl-20260926.htm",
    )
    doc = filings.filing_document("aapl", ref, " ".join(["risk"] * 4000), section="Item 1A")
    assert doc.id == "filing-aapl" and doc.kind == "filings" and doc.as_of == ref.filed
    assert doc.word_count <= filings.MAX_WORDS
    assert ref.url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm"
    )
