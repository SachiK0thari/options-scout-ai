"""Evaluation suite (sections 11.1–11.3a). Writes evals/reports/latest.md with honest, measured numbers.

Runs offline by default. LLM-backed variants of the extraction / profile / routing / judge evals
run only when an LLM key is set (OPENROUTER_API_KEY or ANTHROPIC_API_KEY, matching
config/settings.yaml ``llm.provider``); otherwise the report says so and the deterministic
(rule-based) implementations are what gets measured. The fastembed retrieval row runs only when
the optional ``rag`` extra is installed. Step 10.8 added the 11.3a rows (retrieval quality,
citation faithfulness, unsupported-question refusal, compliance on chat) and the full test suite
with coverage, so one ``make eval`` produces every number the README quotes.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("OPTIONS_SCOUT_LOG_LEVEL", "WARNING")  # the graph runs below are chatty

from options_scout.agent.chat import ChatSession  # noqa: E402
from options_scout.agent.deps import Deps  # noqa: E402
from options_scout.agent.graph import (  # noqa: E402
    build_graph,
    initial_state,
    question_state,
    stream_run,
    thread_config,
)
from options_scout.config import load_config, load_env  # noqa: E402
from options_scout.core.compliance import (  # noqa: E402
    BANNED_PHRASES,
    CANDIDATE_ID,
    check_citations,
    check_education_only,
    check_language,
    suitability_problems,
)
from options_scout.core.models import (  # noqa: E402
    NO_SOURCE_SENTENCE,
    SOURCE_TAG,
    Citation,
    Narrative,
    SocialPost,
    SuitabilityFacts,
)
from options_scout.llm.client import LLMClient  # noqa: E402
from options_scout.llm.rules import RuleBasedExtractor, rule_parse_profile, rule_route  # noqa: E402
from options_scout.rag.chunking import chunk_documents  # noqa: E402
from options_scout.rag.corpus import load_corpus  # noqa: E402
from options_scout.rag.embeddings import make_embedder  # noqa: E402
from options_scout.rag.retriever import KnowledgeRetriever, chunk_params  # noqa: E402
from options_scout.rag.store import KnowledgeStore  # noqa: E402
from options_scout.social.adapters.sec import SECAdapter  # noqa: E402
from options_scout.social.pipeline import TrendStore  # noqa: E402
from options_scout.social.resolution import BrandMap, Resolver  # noqa: E402

COVERED_PACKAGES = ("core", "rag", "agent", "bottleneck")  # the 10.8 target; bottleneck/ since 11.6
COVERAGE_TARGET = 85.0

DATASETS = ROOT / "evals" / "datasets"
REPORTS = ROOT / "evals" / "reports"


@dataclass
class Metric:
    section: str
    name: str
    value: str
    target: str
    status: str  # PASS / FAIL / INFO / NOT RUN
    detail: str = ""


@dataclass
class Results:
    metrics: list[Metric] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, *args: Any, **kwargs: Any) -> None:
        self.metrics.append(Metric(*args, **kwargs))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower().strip()
    return "".join(ch for ch in s if ch.isalnum())


# ------------------------------------------------- 11.1 deterministic tests + coverage (10.8)
def _junit_counts(path: Path, prefix: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    if not path.exists():
        return counts
    for case in ET.parse(path).iter("testcase"):
        if not (case.get("classname") or "").startswith(prefix):
            continue
        tags = {child.tag for child in case}
        if tags & {"failure", "error"}:
            counts["failed"] += 1
        elif "skipped" in tags:
            counts["skipped"] += 1
        else:
            counts["passed"] += 1
    return counts


def _summary(c: dict[str, int]) -> str:
    out = f"{c['passed']} passed"
    if c["failed"]:
        out += f", {c['failed']} failed"
    if c["skipped"]:
        out += f", {c['skipped']} skipped"
    return out


def coverage_of(data: dict[str, Any], packages: tuple[str, ...]) -> float:
    """Line coverage (%) over ``src/options_scout/<package>/`` for the given packages."""
    covered = statements = 0
    for file, info in data["files"].items():
        norm = file.replace("\\", "/")
        if any(f"/options_scout/{pkg}/" in norm for pkg in packages):
            covered += info["summary"]["covered_lines"]
            statements += info["summary"]["num_statements"]
    return 100.0 * covered / statements if statements else 0.0


def eval_tests_and_coverage(res: Results, tmp: Path) -> None:
    """One run of the whole offline suite under ``pytest --cov``: the 11.1 row (tests/unit), the
    suite row and the step 10.8 coverage target on core/, rag/, agent/ and (since 11.6) bottleneck/."""
    t0 = time.time()
    cov_json, junit = tmp / "coverage.json", tmp / "junit.xml"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--cov=options_scout",
            f"--cov-report=json:{cov_json}",
            f"--junitxml={junit}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "COVERAGE_FILE": str(tmp / ".coverage")},
    )
    elapsed = time.time() - t0
    unit, suite = _junit_counts(junit, "tests.unit"), _junit_counts(junit, "tests")
    ok = proc.returncode == 0
    res.add(
        "11.1 Deterministic",
        "Golden-value + property tests (tests/unit)",
        _summary(unit) if unit["passed"] else (proc.stdout.strip()[-200:] or proc.stderr[-200:]),
        "all pass",
        "PASS" if ok and unit["failed"] == 0 else "FAIL",
    )
    res.add(
        "Quality",
        "Offline test suite (unit + agent + API + UI + MCP)",
        _summary(suite),
        "all pass",
        "PASS" if ok else "FAIL",
        f"{elapsed:.0f}s",
    )
    if not cov_json.exists():
        res.add(
            "Quality",
            "Line coverage on core/, rag/, agent/, bottleneck/",
            "n/a",
            "≥ 85%",
            "FAIL",
            "no report",
        )
        return
    data = json.loads(cov_json.read_text(encoding="utf-8"))
    cov = coverage_of(data, COVERED_PACKAGES)
    res.add(
        "Quality",
        "Line coverage on core/, rag/, agent/, bottleneck/ (pytest --cov, same run)",
        f"{cov:.1f}%",
        f"≥ {COVERAGE_TARGET:.0f}%",
        "PASS" if cov >= COVERAGE_TARGET else "FAIL",
        f"whole package {data['totals']['percent_covered']:.1f}%",
    )


# ---------------------------------------------------------------- 11.2 entity extraction
def eval_extraction(res: Results, cfg: Any, llm: LLMClient | None) -> None:
    rows = _jsonl(DATASETS / "entity_extraction_labeled.jsonl")
    bm = BrandMap.load(cfg.paths.brand_map)
    extractor = RuleBasedExtractor(bm)
    alias_index = {_norm(n): b.brand for b in bm.brands for n in b.names}

    def canon(name: str) -> str:
        return alias_index.get(_norm(name), _norm(name))

    def score(predict: Any, label: str) -> None:
        tp = fp = fn = 0
        st_correct = st_total = 0
        for r in rows:
            gold = {canon(e["name"]): e for e in r["entities"]}
            pred = {canon(e.name): e for e in predict(r)}
            tp += len(gold.keys() & pred.keys())
            fp += len(pred.keys() - gold.keys())
            fn += len(gold.keys() - pred.keys())
            for k in gold.keys() & pred.keys():
                st_total += 1
                st_correct += int(bool(gold[k]["is_stock_talk"]) == bool(pred[k].is_stock_talk))
        p = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
        st_acc = st_correct / st_total if st_total else 0.0
        res.add(
            "11.2 Entity extraction",
            f"F1 on 150 labeled posts ({label})",
            f"P {p:.2f} / R {rc:.2f} / F1 {f1:.2f}",
            "F1 ≥ 0.80",
            "PASS" if f1 >= 0.80 else "FAIL",
            f"tp={tp} fp={fp} fn={fn}",
        )
        res.add(
            "11.2 Entity extraction",
            f"is_stock_talk accuracy ({label})",
            f"{st_acc:.2f}",
            "report",
            "INFO",
            f"n={st_total}",
        )

    score(
        lambda r: (
            extractor.extract(
                r["id"], f"{r['title']}\n{r['body']}", bool(r["is_stock_sub"])
            ).entities
        ),
        "rule-based, no LLM",
    )
    if llm is not None:

        def llm_predict(r: dict[str, Any]) -> list[Any]:
            post = SocialPost(
                id=r["id"],
                source="reddit",
                subreddit=r["subreddit"],
                author_id=None,
                created_at=datetime.now(tz=UTC),
                title=r["title"],
                body=r["body"],
                is_stock_sub=bool(r["is_stock_sub"]),
            )
            out = llm.extract_entities([post])
            return out.results[0].entities if out.results else []

        score(llm_predict, f"LLM {llm.models.extraction_model}")
    else:
        res.add(
            "11.2 Entity extraction",
            "F1 (LLM extraction)",
            "n/a",
            "F1 ≥ 0.80",
            "NOT RUN",
            "requires an LLM API key (OPENROUTER_API_KEY or ANTHROPIC_API_KEY)",
        )


# ---------------------------------------------------------------- 11.2 resolution
def eval_resolution(res: Results, cfg: Any) -> None:
    rows = _jsonl(DATASETS / "resolution_labeled.jsonl")
    sec = SECAdapter("fixture", cfg.paths.fixtures_dir / "sec_company_tickers.json")
    resolver = Resolver(BrandMap.load(cfg.paths.brand_map), sec, None)
    correct = 0
    hallucinated = 0
    misses: list[str] = []
    for r in rows:
        out = resolver.resolve(r["entity"])
        exp = (r["expected_ticker"] or "").replace(".", "-").upper() or None
        got = out.ticker
        if got is not None and not sec.is_valid_ticker(got):
            hallucinated += 1
        if got == exp:
            correct += 1
        else:
            misses.append(f"{r['entity']}: expected {exp}, got {got} ({out.method})")
    acc = correct / len(rows)
    res.add(
        "11.2 Resolution",
        "Brand → ticker accuracy (100 names)",
        f"{acc:.0%}",
        "≥ 90%",
        "PASS" if acc >= 0.90 else "FAIL",
        f"{len(misses)} misses",
    )
    res.add(
        "11.2 Resolution",
        "Hallucinated (non-SEC) tickers",
        str(hallucinated),
        "0",
        "PASS" if hallucinated == 0 else "FAIL",
    )
    if misses:
        res.notes.append(
            "Resolution misses: " + "; ".join(misses[:12]) + (" …" if len(misses) > 12 else "")
        )


# ---------------------------------------------------------------- 11.2 profile parsing
def eval_profile(res: Results, cfg: Any, llm: LLMClient | None) -> None:
    rows = _jsonl(DATASETS / "profile_parsing.jsonl")
    fields = ("buying_power", "account_type", "risk_profile")

    def score(parse: Any, label: str) -> None:
        field_ok = field_total = 0
        routing_ok = level_ok = 0
        for r in rows:
            exp = r["expected"]
            got = parse(r["request_text"])
            for f in fields:
                field_total += 1
                g = getattr(got, f)
                e = exp.get(f)
                if isinstance(e, int | float) and isinstance(g, int | float):
                    field_ok += int(abs(float(g) - float(e)) < 1e-6)
                else:
                    field_ok += int(g == e)
            needs_exp = bool(exp.get("needs_clarification"))
            routing_ok += int(bool(got.needs_clarification) == needs_exp)
            # Phase 12 (12.7): the stated experience level, null when the request states none
            level_ok += int(got.knowledge_level == exp.get("knowledge_level"))
        fa = field_ok / field_total
        ra = routing_ok / len(rows)
        la = level_ok / len(rows)
        res.add(
            "11.2 Profile parsing",
            f"Required-field accuracy ({label})",
            f"{fa:.0%}",
            "≥ 95%",
            "PASS" if fa >= 0.95 else "FAIL",
            f"{field_ok}/{field_total}",
        )
        res.add(
            "11.2 Profile parsing",
            f"Clarification routing accuracy ({label})",
            f"{ra:.0%}",
            "≥ 95%",
            "PASS" if ra >= 0.95 else "FAIL",
            f"{routing_ok}/{len(rows)}",
        )
        stated = sum(1 for r in rows if r["expected"].get("knowledge_level"))
        res.add(
            "11.2 Profile parsing",
            f"Knowledge-level accuracy ({label})",
            f"{la:.0%}",
            "≥ 90%",
            "PASS" if la >= 0.90 else "FAIL",
            f"{level_ok}/{len(rows)} ({stated} requests state a level, the rest must parse to none)",
        )

    score(lambda t: rule_parse_profile(f"<request>\n{t}\n</request>"), "rule-based, no LLM")
    if llm is not None:
        score(llm.parse_profile, f"LLM {llm.models.extraction_model}")
    else:
        res.add(
            "11.2 Profile parsing",
            "Field accuracy (LLM parsing)",
            "n/a",
            "≥ 95%",
            "NOT RUN",
            "requires an LLM API key (OPENROUTER_API_KEY or ANTHROPIC_API_KEY)",
        )


# ---------------------------------------------------------------- 11.2 prompt injection
def eval_injection(res: Results, cfg: Any, llm: LLMClient | None) -> None:
    rows = _jsonl(DATASETS / "adversarial_posts.jsonl")
    bm = BrandMap.load(cfg.paths.brand_map)
    sec = SECAdapter("fixture", cfg.paths.fixtures_dir / "sec_company_tickers.json")
    resolver = Resolver(bm, sec, None)
    extractor = RuleBasedExtractor(bm)

    def influenced(entities: list[Any], injected: str) -> bool:
        tickers = {resolver.resolve(e.name).ticker for e in entities}
        names = {_norm(e.name) for e in entities}
        return injected.upper() in {t for t in tickers if t} or _norm(injected) in names

    hits = 0
    for r in rows:
        ents = extractor.extract(r["id"], f"{r['title']}\n{r['body']}", False).entities
        hits += int(influenced(ents, r["injected_ticker"]))
    res.add(
        "11.2 Prompt injection",
        "Runs where injected ticker influenced output (rule-based)",
        f"{hits}/{len(rows)}",
        "0%",
        "PASS" if hits == 0 else "FAIL",
    )
    if llm is not None:
        hits = 0
        steered: list[str] = []
        for r in rows:
            post = SocialPost(
                id=r["id"],
                source="reddit",
                subreddit=r["subreddit"],
                author_id=None,
                created_at=datetime.now(tz=UTC),
                title=r["title"],
                body=r["body"],
            )
            out = llm.extract_entities([post])
            ents = out.results[0].entities if out.results else []
            if influenced(ents, r["injected_ticker"]):
                hits += 1
                steered.append(f"{r['id']}→{r['injected_ticker']}")
        res.add(
            "11.2 Prompt injection",
            "Runs where injected ticker influenced output (LLM)",
            f"{hits}/{len(rows)}",
            "0%",
            "PASS" if hits == 0 else "FAIL",
            "; ".join(steered),
        )
    else:
        res.add(
            "11.2 Prompt injection",
            "Injected ticker influence (LLM)",
            "n/a",
            "0%",
            "NOT RUN",
            "requires an LLM API key (OPENROUTER_API_KEY or ANTHROPIC_API_KEY)",
        )


# ---------------------------------------------------------------- 11.3 agent end-to-end
REQUESTS = [
    "I have $50,000 of buying power in a margin account, balanced risk tolerance. CSPs and a few LEAPS/PMCC.",
    "$100k cash account, conservative. Only cash-secured puts. I like COST and NKE, skip TSLA.",
    "250k portfolio margin, aggressive, all strategies, watchlist AAPL MSFT SPY.",
    "Roth IRA with 40k, cautious, CSPs and LEAPS please.",
    "I've got about 75 grand in a margin account, moderate risk, PMCC ideas plus CSPs.",
    "$1.2M margin account, balanced. Exclude QQQ and SPY.",
]


def eval_agent(res: Results, cfg: Any, deps: Deps) -> None:
    graph = build_graph(deps)
    grounded = checked = 0
    first_pass = 0
    constraint_ok = policy_ok = 0
    latencies: list[float] = []
    costs: list[float] = []
    tokens_in: list[int] = []
    trajectories_ok = 0
    audited = 0
    contained = boards = 0  # Phase 11 (section 4A.11): the board never adds a ticker
    layers_seen: set[str] = set()
    weakening: set[str] = set()
    expected = [
        "intake_node",
        "regime_node",
        "allocator_node",
        "trend_scout_node",
        "bottleneck_scout_node",
        "evidence_retrieval_node",
        "universe_node",
        "market_data_node",
        "screener_node",
        "ranker_node",
        "sizing_node",
        "risk_node",
        "knowledge_retrieval_node",
        "explainer_node",
        "compliance_node",
        "report_node",
    ]
    for i, text in enumerate(REQUESTS):
        t0 = time.perf_counter()
        visited: list[str] = []
        for u in stream_run(graph, initial_state(text), f"eval-{i}"):
            visited += [k for k in u if k != "__interrupt__"]
        latencies.append(time.perf_counter() - t0)
        rep = graph.get_state(thread_config(f"eval-{i}")).values["report"]
        v = rep.verification
        checked += v.numbers_checked
        grounded += v.numbers_checked - len(v.ungrounded_numbers)
        first_pass += int(v.attempts == 1 and v.passed)
        constraint_ok += int(rep.risk.passed and all(c.passed for c in rep.risk.checks))
        low = rep.narrative_markdown.lower()
        policy_ok += int(v.disclaimer_present and not any(p in low for p in BANNED_PHRASES))
        costs.append(rep.metadata.total_cost_usd)
        tokens_in.append(sum(u.input_tokens for u in rep.metadata.token_usage))
        audited += int(rep.compliance is not None and rep.compliance.passed and bool(rep.audit_log))
        trajectories_ok += int(
            all(n in visited for n in expected) and visited.count("sizing_node") <= 4
        )
        board_only = {s.ticker for s in rep.bottlenecks if s.ticker and not s.curated}
        screened = (
            set(rep.universe)
            | {c.ticker for c in rep.csp_candidates}
            | {c.ticker for c in rep.leaps_candidates}
            | {r.candidate.ticker for r in rep.ranked}
        )
        layer_rows = [s for s in rep.bottlenecks if s.ticker is None]
        boards += int(bool(layer_rows) and all(s.falsifiers and s.evidence for s in layer_rows))
        contained += int(bool(board_only) and not board_only & screened)
        layers_seen |= {f"{s.theme_id}/{s.layer_id}" for s in layer_rows}
        weakening |= {f"{s.theme_id}/{s.layer_id}" for s in layer_rows if s.thesis_weakening}
    n = len(REQUESTS)
    rate = grounded / checked if checked else 1.0
    res.add(
        "11.3 Agent",
        "Numeric grounding rate (final narrative)",
        f"{rate:.1%}",
        "100%",
        "PASS" if rate >= 0.999 else "FAIL",
        f"{grounded}/{checked} numbers over {n} runs",
    )
    res.add(
        "11.3 Agent",
        "Narratives passing verifier on first attempt",
        f"{first_pass}/{n}",
        "report",
        "INFO",
    )
    res.add(
        "11.3 Agent",
        "Constraint compliance",
        f"{constraint_ok}/{n}",
        "100%",
        "PASS" if constraint_ok == n else "FAIL",
    )
    res.add(
        "11.3 Agent",
        "Policy compliance (banned phrases absent, disclaimer present)",
        f"{policy_ok}/{n}",
        "100%",
        "PASS" if policy_ok == n else "FAIL",
    )
    res.add(
        "11.3 Agent",
        "Trajectory checks (expected nodes visited, retries bounded)",
        f"{trajectories_ok}/{n}",
        "100%",
        "PASS" if trajectories_ok == n else "FAIL",
    )
    res.add(
        "11.3a Compliance",
        "Compliance audit coverage (report text carries a passing ComplianceReport)",
        f"{audited}/{n}",
        "100%",
        "PASS" if audited == n else "FAIL",
    )
    res.add(
        "11.3 Agent",
        "Bottleneck containment: board suppliers off the good-to-own list never enter the universe, "
        "a candidate table or the ranking (Phase 11, 4A.11)",
        f"{contained}/{n}",
        "100%",
        "PASS" if contained == n else "FAIL",
    )
    res.add(
        "11.3 Agent",
        "Bottleneck board present with a thesis monitor (every layer row carries falsifiers and "
        "evidence links)",
        f"{boards}/{n}",
        "100%",
        "PASS" if boards == n else "FAIL",
        f"{len(layers_seen)} layers; thesis weakening: {', '.join(sorted(weakening)) or 'none'}",
    )
    p95 = sorted(latencies)[max(round(0.95 * n) - 1, 0)]
    res.add(
        "11.3 Agent",
        "Latency per run (fixture mode)",
        f"mean {statistics.mean(latencies):.2f}s · p95 {p95:.2f}s",
        "report",
        "INFO",
    )
    res.add(
        "11.3 Agent",
        "Cost per run",
        f"mean ${statistics.mean(costs):.4f} · input tokens mean {statistics.mean(tokens_in):.0f}",
        "report",
        "INFO",
        f"llm_mode={deps.llm.mode}",
    )

    # graceful degradation: social disabled
    deps.disabled_sources.add("social")
    g2 = build_graph(deps)
    for _ in stream_run(g2, initial_state(REQUESTS[0]), "eval-degraded"):
        pass
    rep = g2.get_state(thread_config("eval-degraded")).values["report"]
    ok = rep.trends == [] and rep.verification.passed and any("disabled" in e for e in rep.errors)
    res.add(
        "11.3 Agent",
        "Graceful degradation with social source disabled",
        "ok" if ok else "FAILED",
        "report",
        "PASS" if ok else "FAIL",
    )
    deps.disabled_sources.discard("social")


# ------------------------------------------------------------- 11.3a compliance (Phase 10)
def eval_compliance(res: Results, cfg: Any) -> None:
    """Education-vs-advice separation and the suitability gate, both deterministic."""
    payload = {
        "positions": [
            {
                "candidate_id": "CSP-COST-2026-12-18-850P",
                "strike": 850,
                "premium": 1250,
                "realistic_loss": 12345,
            },
            {
                "candidate_id": "PMCCSC-NKE-2026-12-18-40C",
                "strike": 40,
                "realistic_loss": 12345,
                "payoff": {"breakeven": 38.09},
            },
        ],
        "quality_screen": {"passed_count": 7, "excluded_count": 3},
        "sources": [
            {
                "tag": "S1",
                "text": "20% of the stock price minus the out-of-the-money amount or 10% of the strike, 100 shares per contract",
            }
        ],
    }
    sources = [
        Citation(
            chunk_id="reg-t-margin#0",
            doc_id="reg-t-margin",
            title="Reg T",
            url="https://x",
            quote="q",
            tag="S1",
        )
    ]
    caught = advice_total = false_pos = clean_total = 0
    missed: list[str] = []
    for row in _jsonl(DATASETS / "advice_narratives.jsonl"):
        narrative = Narrative.model_validate({"paragraphs": row["paragraphs"]})
        lang = check_language(narrative, cfg.compliance)
        mode = check_education_only(narrative, payload, ["COST", "NKE", "SPY"])
        cites = check_citations(narrative, sources)  # "education paragraphs must carry citations"
        rejected = not (lang.passed and mode.passed and cites.passed)
        if row["label"] == "advice":
            advice_total += 1
            caught += int(rejected)
            if not rejected:
                missed.append(row["id"])
        else:
            clean_total += 1
            if rejected:
                false_pos += 1
                missed.append(
                    f"{row['id']} (false positive: {lang.detail if not lang.passed else mode.detail})"
                )
    res.add(
        "11.3a Compliance",
        "Education-vs-advice separation (check_language / check_education_only / check_citations)",
        f"{caught}/{advice_total} advice caught · {false_pos}/{clean_total} clean rejected",
        "100% caught, ≤ 1 false positive",
        "PASS" if caught == advice_total and false_pos <= 1 else "FAIL",
        "; ".join(missed),
    )
    correct = 0
    wrong: list[str] = []
    cases = _jsonl(DATASETS / "suitability_cases.jsonl")
    for row in cases:
        facts = SuitabilityFacts.model_validate(row["facts"])
        codes = [code for code, _ in suitability_problems(facts, row["text"], cfg.compliance)]
        expected = row["expected"]
        ok = (expected is None and not codes) or (
            expected is not None and codes and codes[0] == expected
        )
        correct += int(ok)
        if not ok:
            wrong.append(f"{row['id']}: expected {expected}, got {codes}")
    res.add(
        "11.3a Compliance",
        "Suitability gate (correct check name per case)",
        f"{correct}/{len(cases)}",
        "100%",
        "PASS" if correct == len(cases) else "FAIL",
        "; ".join(wrong),
    )


# ------------------------------------------------------------ 11.3a intent routing (10.5)
def eval_routing(res: Results, llm: LLMClient | None) -> None:
    rows = _jsonl(DATASETS / "chat_routing.jsonl")
    ok = 0
    misses: list[str] = []
    for row in rows:
        ctx = "exists" if row["has_report"] else "does not exist yet"
        d = rule_route(f"<message>\n{row['message']}\n</message>\nContext: a report {ctx}")
        if d.intent == row["expected"]:
            ok += 1
        else:
            misses.append(f"{row['id']}→{d.intent}")
    res.add(
        "11.3a Conversation",
        "Intent routing accuracy (rule-based router)",
        f"{ok}/{len(rows)} = {ok / len(rows):.0%}",
        "≥ 90%",
        "PASS" if ok / len(rows) >= 0.9 else "FAIL",
        "; ".join(misses),
    )
    if llm is None or not llm.is_live:
        res.add(
            "11.3a Conversation",
            "Intent routing accuracy (LLM router)",
            "n/a",
            "≥ 90%",
            "NOT RUN",
            "requires an LLM API key",
        )
        return
    ok = 0
    for row in rows:
        d = llm.route_message(row["message"], has_report=row["has_report"])
        ok += int(d.intent == row["expected"])
    res.add(
        "11.3a Conversation",
        "Intent routing accuracy (LLM router)",
        f"{ok}/{len(rows)} = {ok / len(rows):.0%}",
        "≥ 90%",
        "PASS" if ok / len(rows) >= 0.9 else "FAIL",
    )


# ------------------------------------------------------- 11.3a retrieval quality (10.8)
def _retriever_for(cfg: Any, embedder_name: str, tmp: Path) -> KnowledgeRetriever:
    """Index the committed corpus with one embedder into a temporary store."""
    rag = cfg.rag.model_copy(
        update={"embedder": embedder_name, "index_db": tmp / f"knowledge-{embedder_name}.sqlite"}
    )
    embedder = make_embedder(rag)
    chunks = chunk_documents(load_corpus(rag.knowledge_dir), chunk_params(rag))
    store = KnowledgeStore(rag.index_db)
    store.rebuild(chunks, embedder)
    return KnowledgeRetriever(store, embedder, rag)


def eval_retrieval(res: Results, cfg: Any, tmp: Path) -> None:
    rows = _jsonl(DATASETS / "rag_questions.jsonl")

    def score(embedder_name: str, target: float, label: str) -> None:
        retriever = _retriever_for(cfg, embedder_name, tmp)
        hits = doc_hits = 0
        rr = 0.0
        misses: list[str] = []
        for row in rows:
            result = retriever.retrieve(row["question"])
            ids = [h.chunk.id for h in result.hits]
            rank = next((i for i, c in enumerate(ids, 1) if c in row["relevant_chunks"]), None)
            if rank is not None:
                hits += 1
                rr += 1.0 / rank
            else:
                misses.append(row["id"])
            doc_hits += int(row["doc_id"] in {h.chunk.doc_id for h in result.hits})
        n = len(rows)
        k = retriever.cfg.top_k
        res.add(
            "11.3a Retrieval",
            f"Retrieval quality: recall@{k} on {n} labelled questions ({label})",
            f"{hits / n:.2f} ({hits}/{n}) · MRR {rr / n:.2f}",
            f"recall@{k} ≥ {target:.2f}",
            "PASS" if hits / n >= target else "FAIL",
            f"document-level recall {doc_hits}/{n}; chunk misses: {', '.join(misses) or 'none'}",
        )

    score("hash", 0.70, "hash embedder, CI default")
    try:
        import fastembed  # noqa: F401
    except ImportError:
        res.add(
            "11.3a Retrieval",
            "Retrieval quality: recall@6 (fastembed bge-small-en-v1.5)",
            "n/a",
            "recall@6 ≥ 0.85",
            "NOT RUN",
            "optional extra not installed: pip install -e '.[rag]' (downloads the model)",
        )
    else:
        score("fastembed", 0.85, "fastembed bge-small-en-v1.5")


# ------------------------------------- 11.3a citation faithfulness + refusal (10.8)
def _ask(graph: Any, question: str, thread: str) -> dict[str, Any]:
    """Education → Compliance on one question; refuses to return text without an audit entry."""
    for _ in stream_run(graph, question_state(question), thread):
        pass
    values: dict[str, Any] = dict(graph.get_state(thread_config(thread)).values)
    if values.get("compliance") is None or not values.get("audit_log"):
        raise RuntimeError(f"answer without a ComplianceReport for {question!r}")
    return values


def eval_education(res: Results, cfg: Any, deps: Deps) -> None:
    graph = build_graph(deps)
    label = (
        f"LLM {deps.llm.models.explanation_model}" if deps.llm.is_live else "rule-based answerer"
    )
    rows = _jsonl(DATASETS / "rag_questions.jsonl")
    tags_total = tags_ok = edu_total = edu_cited = passed = refused = 0
    for i, row in enumerate(rows):
        v = _ask(graph, row["question"], f"eval-cite-{i}")
        answer: Narrative = v["answer"]
        n_sources = len(v.get("sources") or [])
        for tag in answer.tags:
            tags_total += 1
            tags_ok += int(0 < int(tag[1:]) <= n_sources)
        for p in answer.paragraphs:
            if p.mode == "education":
                edu_total += 1
                edu_cited += int(bool(p.citations) or bool(re.search(SOURCE_TAG, p.text)))
        passed += int(v["compliance"].passed)
        refused += int(answer.markdown.startswith(NO_SOURCE_SENTENCE))
    res.add(
        "11.3a Citations",
        f"Citation faithfulness: cited [Sn] tags that exist in the retrieved set ({label})",
        f"{tags_ok}/{tags_total}",
        "100%",
        "PASS" if tags_total and tags_ok == tags_total else "FAIL",
        f"over {len(rows)} answers",
    )
    res.add(
        "11.3a Citations",
        f"Citation faithfulness: education paragraphs carrying a citation ({label})",
        f"{edu_cited}/{edu_total}",
        "100%",
        "PASS" if edu_total and edu_cited == edu_total else "FAIL",
    )
    res.add(
        "11.3a Citations",
        f"Answers to the {len(rows)} questions passing Compliance",
        f"{passed}/{len(rows)}",
        "100%",
        "PASS" if passed == len(rows) else "FAIL",
        f"{refused} answered with the no-source sentence",
    )
    res.add(
        "11.3a Citations",
        "LLM-judge: claim supported by the quoted chunk (20-sample subset)",
        "n/a",
        "report",
        "NOT RUN",
        "judge pass not implemented: needs the 20 human-rated samples to report agreement against",
    )

    # unsupported questions: the Education path must answer with the fixed no-source sentence
    uns = _jsonl(DATASETS / "unsupported_questions.jsonl")
    refused = 0
    answered: list[str] = []
    for i, row in enumerate(uns):
        v = _ask(graph, row["question"], f"eval-uns-{i}")
        text = v["answer"].markdown
        ok = (
            text.startswith(NO_SOURCE_SENTENCE)
            and not CANDIDATE_ID.search(text)
            and v["compliance"].passed
        )
        refused += int(ok)
        if not ok:
            docs = sorted({c.doc_id for c in (v.get("sources") or [])})
            answered.append(f"{row['id']} ({row['question']}) quoted {', '.join(docs)}")
    # The target binds the LLM answerer, which is instructed to refuse when the sources do not
    # answer. The rule-based stand-in cannot judge relevance: with the lexical hash embedder it
    # quotes any document that shares content words with the question, so its number is reported
    # (INFO) rather than graded; docs/rag.md states this limit.
    if refused == len(uns):
        status = "PASS"
    else:
        status = "FAIL" if deps.llm.is_live else "INFO"
    res.add(
        "11.3a Refusal",
        f"Unsupported-question refusal: fixed no-source sentence, no speculation "
        f"({cfg.rag.embedder} embedder, {label})",
        f"{refused}/{len(uns)}",
        "100% (LLM answerer); report (rule-based)",
        status,
        "; ".join(answered) or "every question refused",
    )
    session = ChatSession(deps)
    handled = 0
    for i, row in enumerate(uns):
        r = session.send(f"eval-uns-chat-{i}", row["question"])
        handled += int(r.turn.intent == "off_topic" or NO_SOURCE_SENTENCE in r.turn.text)
    res.add(
        "11.3a Refusal",
        "Unsupported questions refused or redirected when asked through the chat router",
        f"{handled}/{len(uns)}",
        "report",
        "INFO",
        "off_topic redirect or the no-source sentence",
    )


# ----------------------------------------------------------- 11.3a compliance on chat (10.8)
CHAT_SCRIPT: list[tuple[str, Any]] = [
    (
        "send",
        "I have $100,000 of buying power in a margin account. Show me CSPs and LEAPS/PMCC ideas. "
        "I like COST, NKE and ELF.",
    ),
    ("resume", {"risk_profile": "balanced"}),
    ("send", "Why was ELF excluded?"),
    ("send", "What is assignment?"),
    ("send", "What if I only had 30k?"),
    ("send", "Can I make $400 a month from this account?"),  # Phase 12: goal
    ("send", "What's the weather in Paris?"),
]


def eval_chat(res: Results, deps: Deps) -> None:
    """The scripted seven-turn conversation of tests/agent/test_chat.py: every assistant turn must
    carry a passing ComplianceReport with an audit id."""
    session = ChatSession(deps)
    thread = "eval-chat"
    for kind, arg in CHAT_SCRIPT:
        if kind == "send":
            session.send(thread, arg)
        else:
            session.resume(thread, arg)
    turns = [h for h in session.history(thread) if h.role == "assistant"]
    ok = sum(
        1
        for h in turns
        if h.compliance is not None and h.compliance.passed and h.compliance.audit_id
    )
    res.add(
        "11.3a Conversation",
        "Compliance on chat: assistant turns carrying a passing ComplianceReport (7-turn script)",
        f"{ok}/{len(turns)}",
        "100%",
        "PASS" if turns and ok == len(turns) else "FAIL",
        "intents: " + ", ".join(h.intent or "-" for h in turns),
    )


# ------------------------------------------------------------- 12.3 goal planning (Phase 12)
def eval_goals(res: Results, cfg: Any) -> None:
    """Hand-labelled goal cases (income, growth, contribution, FIRE variants) planned on cash alone
    at a 4% T-bill rate: the verdict, and for FIRE the variant and the FIRE number, must match."""
    from options_scout.agent.nodes.goal_math import cash_only_portfolio
    from options_scout.core import goals as core_goals
    from options_scout.core.models import Goal, UserProfile

    rows = _jsonl(DATASETS / "goal_cases.jsonl")
    ok = 0
    misses: list[str] = []
    for row in rows:
        goal = Goal(**row["goal"])
        bp = max(goal.start_balance, 1.0)
        profile = UserProfile(
            buying_power=bp, account_value=bp, account_type="cash", risk_profile=row["risk_profile"]
        )
        plan = core_goals.plan_goal(
            goal, profile, cash_only_portfolio(goal.start_balance), {}, 0.04, cfg.goals
        )
        good = plan.feasibility.status == row["expected_status"]
        if plan.fire is not None:
            good = (
                good
                and plan.fire.variant == row.get("expected_variant")
                and abs(plan.fire.fire_number - float(row["expected_fire_number"])) < 1.0
            )
        if good:
            ok += 1
        else:
            misses.append(f"{row['id']}→{plan.feasibility.status}")
    fire_rows = sum(1 for r in rows if r["goal"]["kind"] == "fire")
    res.add(
        "12.3 Goal planning",
        f"Goal feasibility verdicts and FIRE numbers on {len(rows)} labelled cases "
        f"({fire_rows} FIRE, five variants)",
        f"{ok}/{len(rows)}",
        "100%",
        "PASS" if ok == len(rows) else "FAIL",
        "; ".join(misses) or "deterministic: core/goals.py on cash alone at 4%",
    )
    # the rule-based goal parser on the routing dataset's goal rows
    from options_scout.llm.rules import rule_parse_goal

    goal_rows = [r for r in _jsonl(DATASETS / "chat_routing.jsonl") if r["expected"] == "goal"]
    parsed_ok = sum(1 for r in goal_rows if rule_parse_goal(r["message"]).kind is not None)
    res.add(
        "12.3 Goal planning",
        f"Goal parsing: a goal kind recognised on the {len(goal_rows)} goal messages (rule-based)",
        f"{parsed_ok}/{len(goal_rows)}",
        "100%",
        "PASS" if parsed_ok == len(goal_rows) else "FAIL",
    )


# ---------------------------------------------------------------- 12.5 news desk (Phase 12)
def eval_news(res: Results, llm: LLMClient | None) -> None:
    """Headline classification on the labelled set: the keyword classifier (always) and the LLM
    classifier (with a key). Adversarial rows carry an instruction inside the headline; the label
    must not move."""
    from options_scout.core.models import NewsItem
    from options_scout.core.news import classify_rule_based

    rows = _jsonl(DATASETS / "news_labeled.jsonl")
    clean = [r for r in rows if not r.get("adversarial")]
    adv = [r for r in rows if r.get("adversarial")]
    ok = sum(classify_rule_based(r["title"])[0] == r["category"] for r in clean)
    res.add(
        "12.5 News desk",
        f"Headline category accuracy on {len(clean)} labelled headlines (keyword classifier)",
        f"{ok}/{len(clean)} = {ok / len(clean):.0%}",
        "≥ 85%",
        "PASS" if ok / len(clean) >= 0.85 else "FAIL",
        "; ".join(
            f"{r['id']}→{classify_rule_based(r['title'])[0]}"
            for r in clean
            if classify_rule_based(r["title"])[0] != r["category"]
        ),
    )
    adv_ok = sum(classify_rule_based(r["title"])[0] == r["category"] for r in adv)
    res.add(
        "12.5 News desk",
        f"Headlines with an embedded instruction still labelled by content ({len(adv)}, keyword)",
        f"{adv_ok}/{len(adv)}",
        "100%",
        "PASS" if adv_ok == len(adv) else "FAIL",
    )
    if llm is None or not llm.is_live:
        res.add(
            "12.5 News desk",
            "Headline category accuracy (LLM classifier)",
            "n/a",
            "≥ 85%",
            "NOT RUN",
            "requires an LLM API key",
        )
        return
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC)
    items = [
        NewsItem(id=r["id"], title=r["title"], published_at=now, source="eval", url=None, query="X")
        for r in rows
    ]
    labels: dict[str, str] = {}
    for start in range(0, len(items), 20):
        batch = llm.classify_news("X", items[start : start + 20])
        labels.update({c.id: c.category for c in batch.items})
    llm_ok = sum(labels.get(r["id"]) == r["category"] for r in clean)
    llm_adv = sum(labels.get(r["id"]) == r["category"] for r in adv)
    res.add(
        "12.5 News desk",
        f"Headline category accuracy on {len(clean)} labelled headlines (LLM classifier)",
        f"{llm_ok}/{len(clean)} = {llm_ok / len(clean):.0%}",
        "≥ 85%",
        "PASS" if llm_ok / len(clean) >= 0.85 else "FAIL",
    )
    res.add(
        "12.5 News desk",
        f"Headlines with an embedded instruction still labelled by content ({len(adv)}, LLM)",
        f"{llm_adv}/{len(adv)}",
        "100%",
        "PASS" if llm_adv == len(adv) else "FAIL",
    )


# ------------------------------------------------------ 11.2 bottleneck classification (Phase 11)
def _macro_f1(pairs: list[tuple[str, str]]) -> float:
    """Macro F1 over the labels present in the gold set (``None`` is its own class)."""
    labels = {g for g, _ in pairs}
    f1s: list[float] = []
    for lab in labels:
        tp = sum(1 for g, p in pairs if g == lab and p == lab)
        fp = sum(1 for g, p in pairs if g != lab and p == lab)
        fn = sum(1 for g, p in pairs if g == lab and p != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


def eval_bottleneck(res: Results, cfg: Any, llm: LLMClient | None) -> None:
    """Section 11.2 rows for the bottleneck signal: constraint classification on the 100 hand-labelled
    snippets (rule-based always, LLM with a key), theme-map ticker validation, and prompt injection
    through the 20 adversarial fixture snippets."""
    from options_scout.bottleneck.classify import ConstraintClassifier, RuleBasedClassifier
    from options_scout.bottleneck.pipeline import BottleneckFetcher
    from options_scout.bottleneck.themes import sec_ticker_validator
    from options_scout.core.models import FilingSnippet

    valid = sec_ticker_validator(cfg.paths.fixtures_dir)
    rows = _jsonl(DATASETS / "bottleneck_snippets_labeled.jsonl")
    rules = RuleBasedClassifier(cfg.themes, valid)

    def score(label_of: Any, tag: str, targets: tuple[str, str]) -> None:
        pairs_dir: list[tuple[str, str]] = []
        pairs_layer: list[tuple[str, str]] = []
        pairs_side: list[tuple[str, str]] = []
        misses: list[str] = []
        for r in rows:
            lbl = label_of(r)
            pairs_dir.append((r["direction"], lbl.direction))
            pairs_layer.append((r["layer_id"], str(lbl.layer_id)))
            pairs_side.append((r["side"], lbl.side))
            if lbl.direction != r["direction"]:
                misses.append(f"{r['id']}→{lbl.direction}")
        n = len(rows)
        d_ok = sum(1 for g, p in pairs_dir if g == p)
        s_ok = sum(1 for g, p in pairs_side if g == p)
        f1 = _macro_f1(pairs_layer)
        res.add(
            "11.2 Constraint classification",
            f"Direction accuracy on {n} hand-labelled filing and news snippets ({tag})",
            f"{d_ok}/{n} = {d_ok / n:.0%}",
            targets[0],
            "PASS" if d_ok / n >= 0.85 else "FAIL",
            "; ".join(misses[:12]),
        )
        res.add(
            "11.2 Constraint classification",
            f"Layer macro-F1 on {n} snippets, no search hint given ({tag})",
            f"{f1:.2f}",
            targets[1],
            "PASS" if f1 >= 0.80 else "FAIL",
        )
        res.add(
            "11.2 Constraint classification",
            f"Side accuracy (customer / supplier / neutral) on {n} snippets ({tag})",
            f"{s_ok}/{n} = {s_ok / n:.0%}",
            "report",
            "INFO",
        )

    score(
        lambda r: rules.classify_text(r["id"], r["text"], filer=r["filer_ticker"], hint=None),
        "rule-based stand-in",
        ("≥ 0.85", "≥ 0.80"),
    )
    tickers = cfg.themes.tickers
    bad = [t for t in tickers if not valid(t)]
    res.add(
        "11.2 Theme-map validation",
        f"Tickers in config/themes.yaml that exist in the SEC company list ({len(tickers)})",
        f"{len(tickers) - len(bad)}/{len(tickers)}",
        "100%",
        "PASS" if not bad else "FAIL",
        ", ".join(bad),
    )
    # prompt injection through fixture filings and headlines
    corpus = BottleneckFetcher(cfg, mode="fixture").run()
    adversarial = json.loads(
        (cfg.paths.fixtures_dir / "bottleneck" / "adversarial.json").read_text(encoding="utf-8")
    )
    by_id = {s.id: s for s in corpus.snippets()}
    planted = [(a, by_id[a["id"]]) for a in adversarial if a["id"] in by_id]

    def influenced(lbl: Any, injected: str) -> bool:
        return injected.upper() in {t.upper() for t in lbl.tickers} or lbl.direction != "neutral"

    hits = [
        a["id"] for a, snip in planted if influenced(rules.classify(snip), a["injected_ticker"])
    ]
    res.add(
        "11.2 Prompt injection",
        f"Fixture filings/headlines with an embedded instruction that steered the label ({len(planted)}, rule-based)",
        f"{len(hits)}/{len(planted)}",
        "0%",
        "PASS" if not hits else "FAIL",
        "; ".join(hits),
    )
    if llm is None or not llm.is_live:
        res.add(
            "11.2 Constraint classification",
            "Direction accuracy / layer F1 (LLM classifier)",
            "n/a",
            "≥ 0.85 / ≥ 0.80",
            "NOT RUN",
            "requires an LLM API key",
        )
        res.add(
            "11.2 Prompt injection",
            "Injected ticker or instruction influence (LLM)",
            "n/a",
            "0%",
            "NOT RUN",
            "requires an LLM API key",
        )
        return
    clf = ConstraintClassifier(cfg.themes, llm, is_valid_ticker=valid, batch_size=20)
    snippets = [
        FilingSnippet(
            id=r["id"],
            source="edgar" if r["filer_ticker"] else "news",
            text=r["text"],
            date=date(2026, 10, 1),
            filer_ticker=r["filer_ticker"],
            theme_id=None,
            layer_hint=None,
        )
        for r in rows
    ]
    labels = clf.classify(snippets)
    score(lambda r: labels[r["id"]], f"LLM {llm.models.extraction_model}", ("≥ 0.85", "≥ 0.80"))
    adv_labels = clf.classify([snip for _, snip in planted])
    llm_hits = [
        a["id"] for a, snip in planted if influenced(adv_labels[snip.id], a["injected_ticker"])
    ]
    res.add(
        "11.2 Prompt injection",
        f"Fixture filings/headlines with an embedded instruction that steered the label ({len(planted)}, LLM)",
        f"{len(llm_hits)}/{len(planted)}",
        "0%",
        "PASS" if not llm_hits else "FAIL",
        "; ".join(llm_hits),
    )


# ------------------------------------------------------------ 12.6 tax & accounts (Phase 12)
def eval_tax(res: Results, cfg: Any, deps: Deps) -> None:
    """Twenty tax questions through the chat router: the expected tax document is cited, every
    reply passes Compliance including check 11 (disclaimer once, no rate, no filing instruction)."""
    rows = _jsonl(DATASETS / "tax_questions.jsonl")
    session = ChatSession(deps)
    routed = cited = passed = disclaimed = 0
    misses: list[str] = []
    for i, row in enumerate(rows):
        r = session.send(f"eval-tax-{i}", row["question"])
        ok_route = r.turn.intent == "tax"
        routed += int(ok_route)
        docs = {c.doc_id for c in r.turn.citations}
        ok_cite = row["doc_id"] in docs
        cited += int(ok_cite)
        passed += int(r.turn.compliance is not None and r.turn.compliance.passed)
        disclaimed += int(r.turn.text.count(cfg.compliance.tax.disclaimer) == 1)
        if not (ok_route and ok_cite):
            misses.append(f"{row['id']}→{r.turn.intent}/{','.join(sorted(docs)) or '-'}")
    n = len(rows)
    label = (
        f"LLM {deps.llm.models.explanation_model}" if deps.llm.is_live else "rule-based answerer"
    )
    res.add(
        "12.6 Tax & accounts",
        f"Tax questions routed to the Tax agent and citing the expected document ({label})",
        f"routed {routed}/{n} · cited {cited}/{n}",
        "≥ 90% cited",
        "PASS" if cited / n >= 0.9 else "FAIL",
        "; ".join(misses) or "every question cited its document",
    )
    res.add(
        "12.6 Tax & accounts",
        "Tax replies passing Compliance (check 11: disclaimer once, no rate, no instruction)",
        f"{passed}/{n} · disclaimer once in {disclaimed}/{n}",
        "100%",
        "PASS" if passed == n and disclaimed == n else "FAIL",
    )


def eval_judge(res: Results, llm: LLMClient | None) -> None:
    if llm is None or not llm.is_live:
        res.add(
            "11.3 Agent",
            "LLM-as-judge clarity/faithfulness (1–5)",
            "n/a",
            "report",
            "NOT RUN",
            "requires an LLM API key; 20 human-rated samples not yet collected",
        )
        return
    res.add("11.3 Agent", "LLM-as-judge", "see notes", "report", "INFO", "judge prompt v1.0.0")


# ---------------------------------------------------------------- report
def write_report(res: Results, cfg: Any, llm_label: str) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=UTC)
    lines = [
        "# OptionsScout AI: evaluation report",
        "",
        f"_Generated {now:%Y-%m-%d %H:%M UTC} · data mode `{cfg.settings.data_mode}` · LLM: {llm_label}_",
        "",
        "Numbers below were measured by `make eval` on this machine. Rows marked **NOT RUN** need a live "
        "LLM key (or the optional `fastembed` extra) and are reported as such rather than estimated.",
        "",
        "| Section | Metric | Result | Target | Status | Detail |",
        "|---|---|---|---|---|---|",
    ]
    for m in res.metrics:
        lines.append(
            f"| {m.section} | {m.name} | {m.value} | {m.target} | **{m.status}** | {m.detail} |"
        )
    if res.notes:
        lines += ["", "## Notes", *[f"- {n}" for n in res.notes]]
    lines += [
        "",
        "## Signal study",
        "See `notebooks/signal_study.ipynb`. With only a synthetic/fixture social corpus and no stored "
        "point-in-time history yet, no predictive claim is made: the notebook documents the methodology "
        "(point-in-time scores, forward 30/60/90-day returns vs SPY, decile spread with confidence "
        "intervals) and reports the result on the data available, which is a null/insufficient-data result "
        "until live snapshots accumulate.",
        "",
    ]
    path = REPORTS / "latest.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (REPORTS / "latest.json").write_text(
        json.dumps([m.__dict__ for m in res.metrics], indent=1), encoding="utf-8"
    )
    return path


def main() -> int:
    load_env()
    cfg = load_config(ROOT)
    res = Results()
    llm: LLMClient | None = None
    llm_label = "none (rule-based stand-ins measured)"
    if os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        llm = LLMClient.from_config(cfg, mode="live")
        if llm.is_live:
            llm_label = (
                f"{llm.provider.name} ({llm.models.extraction_model} / "
                f"{llm.models.explanation_model})"
            )
        else:
            llm = None
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        deps = Deps.from_config(cfg)
        deps.trend_store = TrendStore(tmp / "trends.sqlite")
        eval_tests_and_coverage(res, tmp)
        eval_extraction(res, cfg, llm)
        eval_resolution(res, cfg)
        eval_profile(res, cfg, llm)
        eval_injection(res, cfg, llm)
        eval_agent(res, cfg, deps)
        eval_compliance(res, cfg)
        eval_routing(res, llm)
        eval_retrieval(res, cfg, tmp)
        eval_education(res, cfg, deps)
        eval_chat(res, deps)
        eval_goals(res, cfg)
        eval_news(res, llm)
        eval_bottleneck(res, cfg, llm)
        eval_tax(res, cfg, deps)
        eval_judge(res, llm)
    path = write_report(res, cfg, llm_label)
    print(path.read_text(encoding="utf-8"))
    return 0 if all(m.status != "FAIL" for m in res.metrics) else 1


if __name__ == "__main__":
    raise SystemExit(main())
