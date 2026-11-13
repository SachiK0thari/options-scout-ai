"""W26 step 2: the knowledge articles cannot drift from the code and config they describe."""

from __future__ import annotations

import importlib
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from options_scout.config import AppConfig, ComplianceConfig
from options_scout.core.compliance import check_sources_fresh
from options_scout.core.models import Citation
from options_scout.rag.corpus import load_corpus
from options_scout.rag.tokens import knowledge_tokens, render

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "knowledge"
AUTHORED = ("basics", "concepts", "tax")  # rules are generated, filings are excerpts

TABS = r"(?:Setup|Candidates|Portfolio & Risk|Goals|Learn|Trends & News|Under the hood)"
CLAIM_START = re.compile(
    rf"(?:This app|The app|The report|The (?:CSP|LEAPS|PMCC) screener|The {TABS} tab)\b"
)
NAMES_A_FEATURE = re.compile(r"\bflag(?:s|ged)?\b|`[a-z_]+`")
NEGATIVE = re.compile(r"\b(?:not|no|never)\b")

# wording that dates an article or hard-codes a figure that lives in config
DRIFT = {
    "a planned feature": re.compile(r"\b(?:the|its) planned\b", re.I),
    "a phase number": re.compile(r"\bPhase \d+\b"),
    "a pending constraint": re.compile(r"until that constraint lands", re.I),
    "a constraint count": re.compile(
        r"\b(?:five|six|seven|eight|nine|ten)\s+(?:portfolio\s+|sizing\s+)?constraints\b", re.I
    ),
    "a ranking weight": re.compile(r"\d+(?:\.\d+)?%\s+of the (?:final )?ranking\b", re.I),
}


def _raw_articles() -> list[tuple[str, str]]:
    return [
        (str(p.relative_to(ROOT)), p.read_text(encoding="utf-8"))
        for kind in AUTHORED
        for p in sorted((KNOWLEDGE / kind).glob("*.md"))
    ]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


@pytest.mark.parametrize("label", sorted(DRIFT))
def test_no_article_carries_drift_wording(label: str) -> None:
    hits = [
        f"{path}: {m.group(0)!r}"
        for path, text in _raw_articles()
        for m in DRIFT[label].finditer(text)
    ]
    assert not hits, f"{label} written into an article (use a {{{{token}}}} or reword): {hits}"


def test_every_config_or_src_path_named_in_an_article_exists() -> None:
    missing = [
        f"{path}: {m.group(1)}"
        for path, text in _raw_articles()
        for m in re.finditer(r"`((?:config|src)/[^`\s]+)`", text)
        if not (ROOT / m.group(1).rstrip(".,")).exists()
    ]
    assert not missing


def test_tokens_render_from_config_and_none_is_left(config: AppConfig) -> None:
    tokens = knowledge_tokens(config)
    w = config.settings.ranking.weights
    assert tokens["ranking.social_pct"] == f"{w.social * 100:g}%"
    assert tokens["risk.constraints_margin"] == "eight"
    assert tokens["risk.constraints_cash"] == "seven"
    docs = load_corpus(KNOWLEDGE, AUTHORED, tokens=tokens)
    assert docs and not [d.path for d in docs if "{{" in d.body or "{{" in d.title]
    used = {
        m.group(1)
        for _p, text in _raw_articles()
        for m in re.finditer(r"\{\{\s*([a-z0-9_.]+)", text)
    }
    assert used and used <= set(tokens)


def test_an_unknown_token_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown knowledge token"):
        render("weight {{ranking.nope}}", {"ranking.social_pct": "10%"}, where="x.md")


def _resolve(target: str) -> Any:
    module, _, attr = target.partition(":")
    obj: Any = importlib.import_module(module)
    for part in attr.split("."):
        fields = getattr(obj, "model_fields", None)
        if fields is not None and part in fields:
            return fields[part]
        obj = getattr(obj, part)
    return obj


def test_every_app_claim_is_registered_with_the_code_behind_it() -> None:
    registry = yaml.safe_load((KNOWLEDGE / "app_claims.yaml").read_text(encoding="utf-8"))
    claims = registry["claims"]
    for c in claims:
        assert _resolve(c["implemented_by"]) is not None, c
    docs = {d.id: d for d in load_corpus(KNOWLEDGE, AUTHORED)}
    unlisted: list[str] = []
    for doc in docs.values():
        listed = [c["contains"] for c in claims if c["doc"] == doc.id]
        for s in _sentences(doc.body):
            if not (CLAIM_START.match(s) and NAMES_A_FEATURE.search(s)) or NEGATIVE.search(s):
                continue
            if not any(snippet in s for snippet in listed):
                unlisted.append(f"{doc.id}: {s[:120]}")
    assert not unlisted, f"add these claims to knowledge/app_claims.yaml: {unlisted}"
    stale = [c for c in claims if c["doc"] not in docs or c["contains"] not in docs[c["doc"]].body]
    assert not stale, f"registered claims no longer in their article: {stale}"


def test_a_dated_rule_past_its_review_date_warns(config: AppConfig) -> None:
    docs = {d.id: d for d in load_corpus(KNOWLEDGE, AUTHORED)}
    pdt = docs["pattern-day-trading-rule"]
    assert pdt.review_by == date(2027, 10, 20)
    cite = Citation(
        chunk_id="pattern-day-trading-rule#0",
        doc_id=pdt.id,
        title=pdt.title,
        url=pdt.url,
        quote="",
        kind="tax",
        tag="S1",
        as_of=pdt.as_of,
        review_by=pdt.review_by,
    )
    cfg: ComplianceConfig = config.compliance
    assert check_sources_fresh([cite], cfg, today=date(2027, 10, 20)).passed
    late = check_sources_fresh([cite], cfg, today=date(2027, 10, 21))
    assert not late.passed and "past its review date" in late.detail and late.severity == "warn"
