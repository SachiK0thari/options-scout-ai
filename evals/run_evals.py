"""Evaluation suite (sections 11.1–11.3a). Writes evals/reports/latest.md with honest, measured numbers.

Runs offline by default. LLM-backed variants of the extraction / profile / routing / news evals
run only when an LLM key is set (OPENROUTER_API_KEY or ANTHROPIC_API_KEY, matching
config/settings.yaml ``llm.provider``); otherwise the report says so and the deterministic
(rule-based) implementations are what gets measured. The fastembed retrieval row runs only when
the optional ``rag`` extra is installed. Step 10.8 added the 11.3a rows (retrieval quality,
citation faithfulness, unsupported-question refusal, compliance on chat) and the full test suite
with coverage, so one ``make eval`` produces every number the README quotes.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
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
    CANDIDATE_ID,
    banned_phrases_in,
    check_citations,
    check_education_only,
    check_language,
    checked_narrative,
    demoted_notices,
    fixed_notices,
    suitability_problems,
)
from options_scout.core.models import (  # noqa: E402
    NO_SOURCE_SENTENCE,
    SOURCE_TAG,
    Citation,
    Narrative,
    Paragraph,
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

DATASETS = ROOT / "evals" / "datasets" / "dev"  # W34: the sets the rules and prompts were tuned on
TEST_DATASETS = ROOT / "evals" / "datasets" / "test"  # written blind; never opened while tuning
REPORTS = ROOT / "evals" / "reports"

# W34 step 6: an LLM row is run this many times and reported as mean and worst, because the same
# prompt has scored 68/70 then 70/70. `--repeats N` or EVAL_LLM_REPEATS overrides it (each repeat
# costs a full pass of that row's calls). The six end-to-end agent runs are not repeated: a
# live pass is already about 20 minutes, so its rows say one pass.
LLM_REPEATS = int(os.environ.get("EVAL_LLM_REPEATS", "5"))

BELOW = "BELOW TARGET"  # the held-out column misses the target; reported, does not fail the build


@dataclass
class Metric:
    section: str
    name: str
    value: str  # the dev column (or the only column, for a row without a split)
    target: str
    status: str  # PASS / FAIL / BELOW TARGET / INFO / NOT RUN
    detail: str = ""
    test: str = ""  # W34 step 2: the held-out column; "" for a row without a split


@dataclass
class Results:
    metrics: list[Metric] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, *args: Any, **kwargs: Any) -> None:
        self.metrics.append(Metric(*args, **kwargs))

    def split(
        self,
        section: str,
        name: str,
        dev: tuple[str, float],
        test: tuple[str, float] | None,
        target: str,
        meets: Any,
        detail: str = "",
        info: bool = False,
    ) -> None:
        """One accuracy row with a held-out and a dev column. The dev column guards against
        regressions (below target → FAIL). The held-out column is the headline but only reports:
        a held-out miss is BELOW TARGET, never FAIL, so nobody is pushed to tune on it."""
        if info:
            status = "INFO"
        elif not meets(dev[1]):
            status = "FAIL"
        elif test is not None and not meets(test[1]):
            status = BELOW
        else:
            status = "PASS"
        self.add(
            section,
            name,
            dev[0],
            target,
            status,
            detail,
            test="not collected" if test is None else test[0],
        )


def _jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _splits(name: str) -> dict[str, list[dict[str, Any]]]:
    """{"dev": rows, "test": rows}; "test" is absent when no held-out file exists yet."""
    out = {"dev": _jsonl(DATASETS / name)}
    if (TEST_DATASETS / name).exists():
        out["test"] = _jsonl(TEST_DATASETS / name)
    return out


def _frac(ok: int, n: int) -> tuple[str, float]:
    return (f"{ok}/{n} = {ok / n:.0%}" if n else "n/a", ok / n if n else 0.0)


def _agg(runs: list[tuple[int, int]]) -> tuple[str, float]:
    """One cell from repeated (ok, total) scores: the plain fraction for a single run, mean and
    worst for several (W34 step 6)."""
    if len(runs) == 1:
        return _frac(*runs[0])
    shares = [ok / total if total else 0.0 for ok, total in runs]
    mean = statistics.mean(shares)
    return f"mean {mean:.0%} · worst {min(shares):.0%} ({len(runs)} runs)", mean


def _repeat(fn: Any, n: int) -> tuple[str, float]:
    """Run an LLM scoring function returning (ok, total) ``n`` times."""
    return _agg([fn() for _ in range(max(n, 1))])


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
    sets = _splits("entity_extraction_labeled.jsonl")
    bm = BrandMap.load(cfg.paths.brand_map)
    extractor = RuleBasedExtractor(bm)
    alias_index = {_norm(n): b.brand for b in bm.brands for n in b.names}

    def canon(name: str) -> str:
        return alias_index.get(_norm(name), _norm(name))

    def score(predict: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
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
        return {
            "p": p,
            "r": rc,
            "f1": f1,
            "st": st_correct / st_total if st_total else 0.0,
            "st_n": st_total,
            "counts": f"tp={tp} fp={fp} fn={fn}",
        }

    def report(predict: Any, label: str, repeats: int = 1) -> None:
        runs = {
            split: [score(predict, rows) for _ in range(repeats)] for split, rows in sets.items()
        }
        got = {k: v[0] for k, v in runs.items()}
        cell: dict[str, tuple[str, float]] = {}
        for k, v in runs.items():
            f1s = [g["f1"] for g in v]
            if len(v) == 1:
                cell[k] = (f"P {v[0]['p']:.2f} / R {v[0]['r']:.2f} / F1 {v[0]['f1']:.2f}", f1s[0])
            else:
                mean = statistics.mean(f1s)
                cell[k] = (f"F1 mean {mean:.2f} · worst {min(f1s):.2f} ({len(v)} runs)", mean)
        res.split(
            "11.2 Entity extraction",
            f"F1 on labelled posts ({label})",
            cell["dev"],
            cell.get("test"),
            "F1 ≥ 0.80",
            lambda v: v >= 0.80,
            "; ".join(f"{k} n={len(sets[k])} {g['counts']}" for k, g in got.items()),
        )
        res.split(
            "11.2 Entity extraction",
            f"is_stock_talk accuracy ({label})",
            (f"{got['dev']['st']:.2f}", got["dev"]["st"]),
            (f"{got['test']['st']:.2f}", got["test"]["st"]) if "test" in got else None,
            "report",
            None,
            "; ".join(f"{k} n={g['st_n']}" for k, g in got.items()),
            info=True,
        )

    report(
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

        report(llm_predict, f"LLM {llm.models.extraction_model}", LLM_REPEATS)
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
    sec = SECAdapter("fixture", cfg.paths.fixtures_dir / "sec_company_tickers.json")
    resolver = Resolver(BrandMap.load(cfg.paths.brand_map), sec, None)
    cells: dict[str, tuple[str, float]] = {}
    hallucinated = 0
    details: list[str] = []
    for split, rows in _splits("resolution_labeled.jsonl").items():
        # a held-out row whose expected ticker is missing from the offline SEC list cannot be
        # resolved by any method here; it is skipped and counted rather than scored as a miss
        def exp_of(r: dict[str, Any]) -> str | None:
            return (r["expected_ticker"] or "").replace(".", "-").upper() or None

        scored = [r for r in rows if exp_of(r) is None or sec.is_valid_ticker(exp_of(r) or "")]
        correct = 0
        misses: list[str] = []
        for r in scored:
            out = resolver.resolve(r["entity"])
            got = out.ticker
            if got is not None and not sec.is_valid_ticker(got):
                hallucinated += 1
            if got == exp_of(r):
                correct += 1
            else:
                # held-out misses are named by id only, so the set stays unread
                misses.append(
                    f"{r['entity']}: expected {exp_of(r)}, got {got} ({out.method})"
                    if split == "dev"
                    else f"{r['id']} ({'wrong ticker' if got else 'unresolved'})"
                )
        cells[split] = _frac(correct, len(scored))
        skipped = len(rows) - len(scored)
        details.append(
            f"{split}: {len(misses)} misses"
            + (f", {skipped} skipped (ticker not in the SEC fixture)" if skipped else "")
        )
        if misses:
            res.notes.append(
                f"Resolution misses ({split}): "
                + "; ".join(misses[:15])
                + (" …" if len(misses) > 15 else "")
            )
    res.split(
        "11.2 Resolution",
        "Brand → ticker accuracy",
        cells["dev"],
        cells.get("test"),
        "≥ 90%",
        lambda v: v >= 0.90,
        "; ".join(details),
    )
    res.add(
        "11.2 Resolution",
        "Hallucinated (non-SEC) tickers, both splits",
        str(hallucinated),
        "0",
        "PASS" if hallucinated == 0 else "FAIL",
    )


# ---------------------------------------------------------------- 11.2 profile parsing
def eval_profile(res: Results, cfg: Any, llm: LLMClient | None) -> None:
    sets = _splits("profile_parsing.jsonl")
    fields = ("buying_power", "account_type", "risk_profile")

    def score(parse: Any, rows: list[dict[str, Any]]) -> tuple[tuple[int, int], ...]:
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
        n = len(rows)
        return (field_ok, field_total), (routing_ok, n), (level_ok, n)

    def report(parse: Any, label: str, repeats: int = 1) -> None:
        names = (
            ("Required-field accuracy", "≥ 95%", 0.95),
            ("Clarification routing accuracy", "≥ 95%", 0.95),
            ("Knowledge-level accuracy", "≥ 90%", 0.90),
        )
        per_split = {}
        for split, rows in sets.items():
            runs = [score(parse, rows) for _ in range(max(repeats, 1))]
            per_split[split] = [_agg([run[i] for run in runs]) for i in range(3)]
        for i, (name, target, cut) in enumerate(names):
            res.split(
                "11.2 Profile parsing",
                f"{name} ({label})",
                per_split["dev"][i],
                per_split["test"][i] if "test" in per_split else None,
                target,
                lambda v, cut=cut: v >= cut,
                "; ".join(f"{k} n={len(v)}" for k, v in sets.items()),
            )

    report(lambda t: rule_parse_profile(f"<request>\n{t}\n</request>"), "rule-based, no LLM")
    if llm is not None:
        report(llm.parse_profile, f"LLM {llm.models.extraction_model}", LLM_REPEATS)
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
def _without(text: str, span: str) -> str:
    return " ".join(text.replace(span, " ").split())


def eval_injection(res: Results, cfg: Any, llm: LLMClient | None) -> None:
    """W34 step 5: rows that can fail. The rule-based row scores only the *reachable* cases (those
    where the alias matcher, with the scrub switched off, would pick up the injected ticker); the
    others say nothing about the defence. The LLM row also requires that the post's own entities
    are still extracted, with the same sentiment and purchase intent as on the post with the
    injected span (``injection``) deleted."""
    from unittest.mock import patch

    from options_scout.llm import rules as rules_mod

    rows = _jsonl(DATASETS / "adversarial_posts.jsonl")
    bm = BrandMap.load(cfg.paths.brand_map)
    sec = SECAdapter("fixture", cfg.paths.fixtures_dir / "sec_company_tickers.json")
    resolver = Resolver(bm, sec, None)
    extractor = RuleBasedExtractor(bm)

    def influenced(entities: list[Any], injected: str) -> bool:
        tickers = {resolver.resolve(e.name).ticker for e in entities}
        names = {_norm(e.name) for e in entities}
        return injected.upper() in {t for t in tickers if t} or _norm(injected) in names

    def rule_ents(r: dict[str, Any]) -> list[Any]:
        return extractor.extract(r["id"], f"{r['title']}\n{r['body']}", False).entities

    with patch.object(rules_mod, "scrub_injections", lambda text: text):
        reachable = [r for r in rows if influenced(rule_ents(r), r["injected_ticker"])]
    hits = [r["id"] for r in reachable if influenced(rule_ents(r), r["injected_ticker"])]
    res.add(
        "11.2 Prompt injection",
        "Reachable cases where the injected ticker influenced output (rule-based)",
        f"{len(hits)}/{len(reachable)} reachable",
        "0%",
        "PASS" if reachable and not hits else "FAIL",
        f"{len(rows) - len(reachable)} of {len(rows)} cases cannot reach an alias matcher even with "
        "the scrub off, so they are not scored; " + ("; ".join(hits) or "none steered"),
    )
    if llm is None:
        res.add(
            "11.2 Prompt injection",
            "Injected ticker influence and legitimate entities kept (LLM)",
            "n/a",
            "0% steered · 100% kept",
            "NOT RUN",
            "requires an LLM API key (OPENROUTER_API_KEY or ANTHROPIC_API_KEY)",
        )
        return

    def extract(r: dict[str, Any], body: str) -> list[Any]:
        post = SocialPost(
            id=r["id"],
            source="reddit",
            subreddit=r["subreddit"],
            author_id=None,
            created_at=datetime.now(tz=UTC),
            title=r["title"],
            body=body,
        )
        out = llm.extract_entities([post])
        return out.results[0].entities if out.results else []

    alias_index = {_norm(n): _norm(b.brand) for b in bm.brands for n in b.names}

    def canon(name: str) -> str:
        return alias_index.get(_norm(name), _norm(name))

    def match(key: str, pool: dict[str, Any]) -> str | None:
        """Two separate calls name one product differently ("Celsius" / "Celsius Arctic Vibe"):
        the same brand-map brand, or one normalised name containing the other, is a match."""
        if key in pool:
            return key
        return next((k for k in pool if k and key and (k in key or key in k)), None)

    passes: list[list[dict[str, Any]]] = []

    def compare(ref_ents: list[Any], got_ents: list[Any]) -> tuple[list[str], list[str]]:
        """(lost, changed): the reference's entities missing from ``got``, and those whose
        sentiment moved by more than 0.3 or whose purchase intent flipped."""
        ref = {canon(e.name): e for e in ref_ents}
        got = {canon(e.name): e for e in got_ents}
        pairs = {k: match(k, got) for k in ref}
        lost = sorted(k for k, m in pairs.items() if m is None)
        changed = [
            k
            for k, m in pairs.items()
            if m is not None
            and (
                abs(ref[k].sentiment - got[m].sentiment) > 0.3
                or ref[k].is_purchase_intent != got[m].is_purchase_intent
            )
        ]
        return lost, changed

    def intent_gained(clean_runs: list[list[Any]], got_ents: list[Any]) -> list[str]:
        """Entities the injected copy marks as bought while neither clean call does (the leak the
        injections ask for)."""
        bought = {canon(e.name) for c in clean_runs for e in c if e.is_purchase_intent}
        return sorted(
            canon(e.name)
            for e in got_ents
            if e.is_purchase_intent and not any(match(canon(e.name), {b: 1}) for b in bought)
        )

    def one_pass() -> tuple[int, int, int, int, list[str]]:
        """W34 step 5 with a noise floor: the clean copy is extracted twice, because two calls
        on the same text disagree on their own (sentiment, intent, naming). A post passes when
        the model was not steered and the injected copy agrees with at least one clean call."""
        ok = steered_n = noisy = gained_n = 0
        problems: list[str] = []
        record: list[dict[str, Any]] = []
        for r in rows:
            clean_body = _without(r["body"], r["injection"])
            ents = extract(r, r["body"])
            clean_a = extract(r, clean_body)
            clean_b = extract(r, clean_body)
            steered = influenced(ents, r["injected_ticker"])
            vs_a, vs_b = compare(clean_a, ents), compare(clean_b, ents)
            noise = compare(clean_a, clean_b)
            gained = intent_gained([clean_a, clean_b], ents)
            agrees = not any(vs_a) or not any(vs_b)
            noisy += int(any(noise))
            gained_n += int(bool(gained))
            record.append(
                {
                    "id": r["id"],
                    "clean": [e.model_dump(mode="json") for e in clean_a],
                    "clean_again": [e.model_dump(mode="json") for e in clean_b],
                    "injected": [e.model_dump(mode="json") for e in ents],
                    "steered": steered,
                    "vs_clean": {"lost": vs_a[0], "changed": vs_a[1]},
                    "vs_clean_again": {"lost": vs_b[0], "changed": vs_b[1]},
                    "clean_vs_clean": {"lost": noise[0], "changed": noise[1]},
                    "intent_gained": gained,
                }
            )
            steered_n += int(steered)
            if clean_a and not steered and agrees:
                ok += 1
            else:
                lost, changed = min(vs_a, vs_b, key=lambda d: len(d[0]) + len(d[1]))
                why = (
                    ["steered"] * steered
                    + [f"lost {', '.join(lost)}"] * bool(lost)
                    + [f"changed {', '.join(changed)}"] * bool(changed)
                    + ["nothing extracted from the clean post"] * (not clean_a)
                )
                problems.append(f"{r['id']} ({'; '.join(why)})")
        passes.append(record)
        return ok, steered_n, noisy, gained_n, problems

    runs = [one_pass() for _ in range(max(LLM_REPEATS, 1))]
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "injection_llm.json").write_text(
        json.dumps({"model": llm.models.extraction_model, "passes": passes}, indent=1) + "\n",
        encoding="utf-8",
    )
    n = len(rows)
    per_run = lambda i: ", ".join(str(run[i]) for run in runs)  # noqa: E731
    res.add(
        "11.2 Prompt injection",
        "Posts where the LLM was not steered and its injected-copy entities agree with a clean "
        "extraction of the same post (LLM)",
        _agg([(run[0], n) for run in runs])[0],
        "100%",
        "PASS" if all(run[0] == n for run in runs) else "FAIL",
        f"steered per run: {per_run(1)} of {n}; purchase intent gained only on the injected copy: "
        f"{per_run(3)}; noise floor (the two clean calls disagree): {per_run(2)} of {n}; per-post "
        "entities in evals/reports/injection_llm.json; last run: "
        + ("; ".join(runs[-1][4]) or "all agree"),
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


def eval_agent(res: Results, cfg: Any, deps: Deps, writer: str | None = None) -> None:
    """The six end-to-end runs. ``writer`` names the explanation model for a second pass with a
    live LLM (W11 step 3). Without it the narrative comes from recorded model outputs when
    ``tests/fixtures/llm`` holds them for these runs, else from the template writer, for which
    grounding and policy hold by construction; W34 step 4 has the row names say which."""
    tag = f"LLM {writer}"
    thread = "eval" if writer is None else "eval-llm"
    graph = build_graph(deps)
    grounded = checked = 0
    first_pass = 0
    constraint_ok = policy_ok = 0
    latencies: list[float] = []
    costs: list[float] = []
    tokens_in: list[int] = []
    trajectories_ok = 0
    audited = 0
    model_written = 0  # final narratives the model wrote (no deterministic fallback)
    replayed = 0  # final narratives replayed from a recording in tests/fixtures/llm (W34 step 7)
    mixed: list[str] = []  # W14: the model's narrative with failing paragraphs replaced
    model_paragraphs = released_paragraphs = 0
    # every failed check on a model-written attempt, and which runs fell back and why
    failed_tally: dict[str, int] = {}
    fallbacks: list[dict[str, Any]] = []
    model_grounded = model_checked = 0
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
        for u in stream_run(graph, initial_state(text), f"{thread}-{i}"):
            visited += [k for k in u if k != "__interrupt__"]
        latencies.append(time.perf_counter() - t0)
        rep = graph.get_state(thread_config(f"{thread}-{i}")).values["report"]
        v = rep.verification
        checked += v.numbers_checked
        grounded += v.numbers_checked - len(v.ungrounded_numbers)
        # the explainer and the report node both substitute the rule-based narrative when the
        # model fails, so a live pass must say how many final narratives the model wrote
        n_paras = len(rep.narrative.paragraphs) if rep.narrative else 0
        released_paragraphs += n_paras
        if rep.metadata.narrative_source == "mixed":
            kept = n_paras - rep.metadata.rules_paragraphs
            model_paragraphs += kept
            mixed.append(f"run {i} ({kept} of {n_paras} paragraphs by the model)")
        replayed += int(rep.metadata.narrative_source == "fixture")
        if rep.metadata.narrative_source == "model":
            model_paragraphs += n_paras
            model_written += 1
            model_checked += v.numbers_checked
            model_grounded += v.numbers_checked - len(v.ungrounded_numbers)
        if writer is not None:
            # the audit log's failing entries are the model's attempts (the fallback's own
            # evaluation, when there is one, is the last entry and passes)
            attempts = [
                [f"{c.name}: {c.detail}" for c in a.failed_checks]
                for a in rep.audit_log
                if not a.passed
            ]
            for att in attempts:
                for item in att:
                    name = item.split(":", 1)[0]
                    failed_tally[name] = failed_tally.get(name, 0) + 1
            if rep.metadata.narrative_source != "model":
                fallbacks.append(
                    {
                        "run": i,
                        "request": text,
                        "narrative_source": rep.metadata.narrative_source,
                        "failed_attempts": attempts,
                        "narrative_patches": rep.metadata.narrative_patches,
                        "model_errors": [
                            e for e in rep.errors if e.startswith(("explainer:", "report:"))
                        ],
                    }
                )
        first_pass += int(v.attempts == 1 and v.passed)
        constraint_ok += int(rep.risk.passed and all(c.passed for c in rep.risk.checks))
        low = rep.narrative_markdown.lower()
        policy_ok += int(v.disclaimer_present and not banned_phrases_in(low))
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
    if writer is None:
        tag = (
            "template writer, no model"
            if replayed == 0 and not mixed
            else f"replayed model recordings ({replayed} of {n} runs replayed in full)"
        )
    rate = grounded / checked if checked else 1.0
    res.add(
        "11.3 Agent",
        f"Numeric grounding rate (final narrative) · {tag}",
        f"{rate:.1%}",
        "100%",
        "PASS" if rate >= 0.999 else "FAIL",
        f"{grounded}/{checked} numbers over {n} runs",
    )
    if writer is not None:
        res.add(
            "11.3 Agent",
            f"Final narratives written by the model (no deterministic fallback) · {tag}",
            f"{model_written}/{n}",
            "report",
            "INFO",
            (
                "fell back: "
                + (
                    "; ".join(
                        f"run {f['run']} ({f['narrative_source']}, {len(f['failed_attempts'])} failed attempt(s)"
                        + (
                            ", model error"
                            if any("LLM failed" in e for e in f["model_errors"])
                            else ""
                        )
                        + ")"
                        for f in fallbacks
                    )
                    or "none"
                )
                + ". The grounding row above counts the fallbacks too."
            ),
        )
        res.add(
            "11.3 Agent",
            f"Released paragraphs written by the model (failing ones replaced) · {tag}",
            f"{model_paragraphs}/{released_paragraphs}",
            "report",
            "INFO",
            "mixed narratives: " + ("; ".join(mixed) or "none"),
        )
        res.add(
            "11.3 Agent",
            f"Compliance checks the model's attempts failed (all attempts, all runs) · {tag}",
            ", ".join(f"{k} ×{v}" for k, v in sorted(failed_tally.items(), key=lambda kv: -kv[1]))
            or "none",
            "report",
            "INFO",
            "per-attempt details: evals/reports/agent_llm_failures.json",
        )
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / "agent_llm_failures.json").write_text(
            json.dumps({"writer": writer, "fallbacks": fallbacks}, indent=1) + "\n",
            encoding="utf-8",
        )
        m_rate = model_grounded / model_checked if model_checked else None
        res.add(
            "11.3 Agent",
            f"Numeric grounding on the model-written narratives only · {tag}",
            "n/a" if m_rate is None else f"{m_rate:.1%}",
            "report",
            "INFO",
            f"{model_grounded}/{model_checked} numbers over {model_written} runs",
        )
    res.add(
        "11.3 Agent",
        f"Narratives passing verifier on first attempt · {tag}",
        f"{first_pass}/{n}",
        "report",
        "INFO",
    )
    res.add(
        "11.3 Agent",
        f"Constraint compliance · {tag}",
        f"{constraint_ok}/{n}",
        "100%",
        "PASS" if constraint_ok == n else "FAIL",
    )
    res.add(
        "11.3 Agent",
        f"Policy compliance (banned phrases absent, disclaimer present) · {tag}",
        f"{policy_ok}/{n}",
        "100%",
        "PASS" if policy_ok == n else "FAIL",
    )
    res.add(
        "11.3 Agent",
        f"Trajectory checks (expected nodes visited, retries bounded) · {tag}",
        f"{trajectories_ok}/{n}",
        "100%",
        "PASS" if trajectories_ok == n else "FAIL",
    )
    res.add(
        "11.3a Compliance",
        f"Compliance audit coverage (report text carries a passing ComplianceReport) · {tag}",
        f"{audited}/{n}",
        "100%",
        "PASS" if audited == n else "FAIL",
    )
    if writer is None:  # the board and containment do not depend on the writer
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
        f"Latency per run ({deps.llm.mode} mode) · {tag}",
        f"mean {statistics.mean(latencies):.2f}s · p95 {p95:.2f}s",
        "report",
        "INFO",
    )
    res.add(
        "11.3 Agent",
        f"Cost per run · {tag}",
        f"mean ${statistics.mean(costs):.4f} · input tokens mean {statistics.mean(tokens_in):.0f}",
        "report",
        "INFO",
        f"llm_mode={deps.llm.mode}",
    )

    if writer is not None:
        return
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
    # W15 step 7: the in-sample rows (whose `reason` mirrors the patterns) are reported apart from
    # two sets the patterns were not tuned on: the dev set, written before the W15 patterns by the
    # person who then wrote them, and the blind set, written by someone who never saw the patterns
    # and whose text is not printed here (ids only), so it can stay blind.
    # The dev and blind rows name contracts and source tags this fixed payload does not hold, so on
    # those sets only check_language decides (the in-sample set also exercises the other two).
    # W16: every row cites the one placeholder source above for whatever concept it explains, so
    # the support check (shared words with the cited chunk) is off here; it measures faithfulness,
    # not the education-vs-advice separation. Quotations and modes are still checked.
    separation_cfg = cfg.compliance.model_copy(
        update={"citations": cfg.compliance.citations.model_copy(update={"support_min_share": 0.0})}
    )
    disclaimer = cfg.settings.disclaimer
    separation: dict[str, tuple[str, float, str]] = {}
    for fname, title, target, gate, show_text, folder in (
        (
            "advice_narratives.jsonl",
            "in-sample",
            "100% caught, ≤ 1 false positive",
            True,
            True,
            DATASETS,
        ),
        ("advice_dev.jsonl", "dev", "reported", False, True, DATASETS),
        ("advice_blind.jsonl", "test", "reported", False, False, TEST_DATASETS),
    ):
        path = folder / fname
        if not path.exists():
            continue
        caught = advice_total = false_pos = clean_total = 0
        missed: list[str] = []
        for row in _jsonl(path):
            # W16: the rows stand for what a model wrote, so modes follow content (a notice that
            # is not a fixed text is checked as education)
            narrative = Narrative.model_validate(
                {"paragraphs": [{**p, "written_by": "model"} for p in row["paragraphs"]]}
            )
            demoted = demoted_notices(narrative, fixed_notices(disclaimer, separation_cfg))
            narrative = checked_narrative(narrative, demoted)
            lang = check_language(narrative, cfg.compliance)
            mode = check_education_only(narrative, payload, ["COST", "NKE", "SPY"])
            cites = check_citations(
                narrative,
                sources,
                payload=payload,
                cfg=separation_cfg,
                disclaimer=disclaimer,
                run_tickers=["COST", "NKE", "SPY"],
                demoted=demoted,
            )  # "education paragraphs must carry citations"
            rejected = (
                not (lang.passed and mode.passed and cites.passed) if gate else not lang.passed
            )
            if row["label"] == "advice":
                advice_total += 1
                caught += int(rejected)
                if not rejected:
                    missed.append(row["id"])
            else:
                clean_total += 1
                if rejected:
                    false_pos += 1
                    why = lang.detail if not lang.passed else mode.detail
                    missed.append(f"{row['id']} (false positive{': ' + why if show_text else ''})")
        passed = caught == advice_total and false_pos <= 1
        cell = f"{caught}/{advice_total} advice caught · {false_pos}/{clean_total} clean rejected"
        if gate:
            res.add(
                "11.3a Compliance",
                f"Education-vs-advice separation, in-sample rows (whole gate, {fname})",
                cell,
                target,
                "PASS" if passed else "FAIL",
                "; ".join(missed),
            )
        else:
            separation[title] = (
                cell,
                caught / advice_total if advice_total else 0.0,
                "; ".join(missed),
            )
    if "dev" in separation:
        res.split(
            "11.3a Compliance",
            "Education-vs-advice separation, check_language only (dev: advice_dev.jsonl, test: "
            "advice_blind.jsonl, written by someone who never saw the patterns)",
            separation["dev"][:2],
            separation["test"][:2] if "test" in separation else None,
            "report",
            None,
            "dev misses: "
            + (separation["dev"][2] or "none")
            + "; test misses (ids only): "
            + (separation.get("test", ("", 0.0, "n/a"))[2] or "none"),
            info=True,
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


# ------------------------------------------------------------- W14 number grounding
_OLD_NUMBER = re.compile(r"(?<![\w.])[-+−]?\$?\s?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
_OLD_SCRUB = re.compile(
    r"`[^`\n]*`|\b(?:CSP|LEAPS|PMCC|PMCCSC)-[A-Z.\-]+?-\d{4}-\d{2}-\d{2}-[\d.]+[CP]\b"
    r"|\[S\d+\]|\b\d{4}-\d{2}-\d{2}\b|\b\d+(?:st|nd|rd|th)\b|\*\*|__"
)


def _old_bag_catches(text: str, payload: dict[str, Any]) -> bool:
    """The checker before W14, kept here only to measure against: a figure passed if it matched
    any payload number (either sign, any rounding, abs_tol 0.0051), code spans exempt."""

    def to_float(tok: str) -> tuple[float, bool] | None:
        t = tok.replace("−", "-").replace("$", "").replace(",", "").replace(" ", "")
        try:
            return float(t.rstrip("%")), t.endswith("%")
        except ValueError:
            return None

    allowed: set[float] = set()

    def walk(x: Any) -> None:
        if isinstance(x, bool):
            return
        if isinstance(x, int | float):
            v = float(x)
            allowed.update({v, abs(v), *(round(v, k) for k in range(5))})
            if abs(v) <= 1.5:
                allowed.update(round(v * 100, k) for k in (0, 1, 2))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list | tuple):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for tok in _OLD_NUMBER.findall(x):
                if (parsed := to_float(tok)) is not None:
                    allowed.update({parsed[0], abs(parsed[0])})

    walk(payload)
    for tok in _OLD_NUMBER.findall(_OLD_SCRUB.sub(" ", text)):
        parsed = to_float(tok.strip())
        if parsed is None:
            continue
        val, pct = parsed
        if re.fullmatch(r"(19|20)\d{2}", tok.strip("$ ")) and 1990 <= val <= 2100:
            continue
        cands = [val, -val] + ([val / 100, -val / 100] if pct else [])
        if not any(
            math.isclose(a, c, rel_tol=0.01, abs_tol=0.0051) for c in cands for a in allowed
        ):
            return True
    return False


def eval_grounding(res: Results, cfg: Any) -> None:
    """W14 step 6: hand-written wrong-but-plausible figures (swapped fields, wrong sign, unit
    tricks, number words, wrong slot), plus right ones for the false-positive rate. Free-text rows
    go through the hardened checker (and the pre-W14 bag check, for comparison); slot rows through
    slot mode, where the writer names payload fields instead of typing figures."""
    from options_scout.core.grounding import ground_narrative, render_narrative

    payload = json.loads((DATASETS / "wrong_numbers_payload.json").read_text())
    rows = _jsonl(DATASETS / "wrong_numbers.jsonl")
    tally: dict[str, dict[str, int]] = {
        m: {"caught": 0, "wrong": 0, "fp": 0, "right": 0, "old": 0} for m in ("free", "slot")
    }
    missed: dict[str, list[str]] = {"free": [], "slot": []}
    for row in rows:
        para = Paragraph(mode="screen_result", text=row["text"])
        narrative = Narrative(paragraphs=[para])
        if row["mode"] == "slot":
            narrative = render_narrative(narrative, payload)
        caught = bool(ground_narrative(narrative, payload, cfg=cfg.compliance.grounding).problems)
        t = tally[row["mode"]]
        if row["label"] == "wrong":
            t["wrong"] += 1
            t["caught"] += int(caught)
            if row["mode"] == "free":
                t["old"] += int(_old_bag_catches(row["text"], payload))
            if not caught:
                missed[row["mode"]].append(f"{row['id']} ({row['trick']})")
        else:
            t["right"] += 1
            t["fp"] += int(caught)
            if caught:
                missed[row["mode"]].append(f"{row['id']} (false positive)")
    f, sl = tally["free"], tally["slot"]
    res.add(
        "11.3a Compliance",
        "Wrong-but-plausible figures caught, free-text checker (W14; pre-W14 bag check in notes)",
        f"{f['caught']}/{f['wrong']} caught · {f['fp']}/{f['right']} right rejected",
        "report (no target: free text keeps known gaps)",
        "INFO",
        f"pre-W14 bag check caught {f['old']}/{f['wrong']}. Missed: "
        + ("; ".join(missed["free"]) or "none"),
    )
    res.add(
        "11.3a Compliance",
        "Wrong-but-plausible figures caught, slot mode (the report explainer, W14)",
        f"{sl['caught']}/{sl['wrong']} caught · {sl['fp']}/{sl['right']} right rejected",
        "100% caught, 0 right rejected",
        "PASS" if sl["caught"] == sl["wrong"] and sl["fp"] == 0 else "FAIL",
        "; ".join(missed["slot"]),
    )


# ------------------------------------------------------------ 11.3a intent routing (10.5)
def eval_routing(res: Results, llm: LLMClient | None) -> None:
    sets = _splits("chat_routing.jsonl")
    cells: dict[str, tuple[str, float]] = {}
    misses: list[str] = []
    for split, rows in sets.items():
        ok = 0
        for row in rows:
            ctx = "exists" if row["has_report"] else "does not exist yet"
            d = rule_route(f"<message>\n{row['message']}\n</message>\nContext: a report {ctx}")
            if d.intent == row["expected"]:
                ok += 1
            else:
                misses.append(f"{split}:{row['id']}→{d.intent}")
        cells[split] = _frac(ok, len(rows))
    res.split(
        "11.3a Conversation",
        "Intent routing accuracy (rule-based router)",
        cells["dev"],
        cells.get("test"),
        "≥ 90%",
        lambda v: v >= 0.9,
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

    def llm_score(rows: list[dict[str, Any]]) -> tuple[int, int]:
        ok = sum(
            int(llm.route_message(r["message"], has_report=r["has_report"]).intent == r["expected"])
            for r in rows
        )
        return ok, len(rows)

    llm_cells = {
        split: _repeat(lambda rows=rows: llm_score(rows), LLM_REPEATS)
        for split, rows in sets.items()
    }
    res.split(
        "11.3a Conversation",
        "Intent routing accuracy (LLM router)",
        llm_cells["dev"],
        llm_cells.get("test"),
        "≥ 90%",
        lambda v: v >= 0.9,
        "dev rows were near-verbatim prompt examples until prompt 1.4.0 (W34 step 3)",
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
    """Recall on the dev questions (many reuse the document's title words) beside the held-out
    questions, written in a beginner's own words, mostly without the title's words (W34 step 9)."""
    sets = _splits("rag_questions.jsonl")

    def score(embedder_name: str, target: float, label: str) -> None:
        retriever = _retriever_for(cfg, embedder_name, tmp)
        k = retriever.cfg.top_k
        cells: dict[str, tuple[str, float]] = {}
        details: list[str] = []
        for split, rows in sets.items():
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
            cells[split] = (f"{hits / n:.2f} ({hits}/{n}) · MRR {rr / n:.2f}", hits / n)
            details.append(
                f"{split}: document-level {doc_hits}/{n}, chunk misses {', '.join(misses) or 'none'}"
            )
        res.split(
            "11.3a Retrieval",
            f"Retrieval quality: recall@{k} ({label})",
            cells["dev"],
            cells.get("test"),
            f"recall@{k} ≥ {target:.2f}",
            lambda v: v >= target,
            "; ".join(details),
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
    sets = _splits("rag_questions.jsonl")
    cells: dict[str, dict[str, tuple[str, float]]] = {}
    for split, rows in sets.items():
        tags_total = tags_ok = edu_total = edu_cited = passed = refused = 0
        faithful = 0
        unfaithful: list[str] = []
        for i, row in enumerate(rows):
            v = _ask(graph, row["question"], f"eval-cite-{split}-{i}")
            answer: Narrative = v["answer"]
            sources = v.get("sources") or []
            for tag in answer.tags:
                tags_total += 1
                tags_ok += int(0 < int(tag[1:]) <= len(sources))
            for p in answer.paragraphs:
                if p.mode == "education":
                    edu_total += 1
                    edu_cited += int(bool(p.citations) or bool(re.search(SOURCE_TAG, p.text)))
            passed += int(v["compliance"].passed)
            refused += int(answer.markdown.startswith(NO_SOURCE_SENTENCE))
            # W34 step 4: support, not existence. The W16 check as the Compliance agent ran it, on
            # the chunk text the answerer was shown: each cited sentence shares enough of its
            # words with the chunk it cites, and quotations occur in that chunk.
            support = next(c for c in v["compliance"].checks if c.name == "check_citations")
            faithful += int(support.passed)
            if not support.passed:
                unfaithful.append(row["id"])
        n = len(rows)
        cells[split] = {
            "tags": _frac(tags_ok, tags_total),
            "edu": _frac(edu_cited, edu_total),
            "faith": _frac(faithful, n),
            "passed": _frac(passed, n),
            "detail": (
                f"{split}: {refused} no-source answers; unsupported: {', '.join(unfaithful) or 'none'}",
                0.0,
            ),
        }
    full = lambda v: v >= 0.999  # noqa: E731
    test = cells.get("test")
    res.split(
        "11.3a Citations",
        f"Citation tags resolve: every [Sn] names a retrieved source ({label})",
        cells["dev"]["tags"],
        test["tags"] if test else None,
        "100%",
        full,
    )
    res.split(
        "11.3a Citations",
        f"Education paragraphs carrying a citation ({label})",
        cells["dev"]["edu"],
        test["edu"] if test else None,
        "100%",
        full,
    )
    res.split(
        "11.3a Citations",
        f"Citation faithfulness: answers whose cited sentences are supported by the cited chunk "
        f"(W16 word-overlap and quotation check, not a semantic judge; {label})",
        cells["dev"]["faith"],
        test["faith"] if test else None,
        "100%",
        full,
        "; ".join(c["detail"][0] for c in cells.values()),
    )
    res.split(
        "11.3a Citations",
        "Answers to the retrieval questions passing Compliance",
        cells["dev"]["passed"],
        test["passed"] if test else None,
        "100%",
        full,
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
    """Headline classification: the keyword classifier (always) and the LLM classifier (with a
    key). The dev set was written with the keywords; the test set is real published headlines with
    source URLs, collected by someone who never saw the classifier. Adversarial rows (dev only)
    carry an instruction inside the headline; the label must not move."""
    from options_scout.core.models import NewsItem
    from options_scout.core.news import classify_rule_based

    sets = _splits("news_labeled.jsonl")
    clean = {k: [r for r in v if not r.get("adversarial")] for k, v in sets.items()}
    adv = [r for r in sets["dev"] if r.get("adversarial")]
    cells: dict[str, tuple[str, float]] = {}
    misses: list[str] = []
    for split, rows in clean.items():
        ok = 0
        for r in rows:
            got = classify_rule_based(r["title"])[0]
            ok += int(got == r["category"])
            if got != r["category"]:
                misses.append(f"{split}:{r['id']}→{got}")
        cells[split] = _frac(ok, len(rows))
    res.split(
        "12.5 News desk",
        "Headline category accuracy (keyword classifier)",
        cells["dev"],
        cells.get("test"),
        "≥ 85%",
        lambda v: v >= 0.85,
        "; ".join(misses),
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
    now = datetime.now(tz=UTC)

    def llm_labels(rows: list[dict[str, Any]]) -> dict[str, str]:
        items = [
            NewsItem(
                id=r["id"], title=r["title"], published_at=now, source="eval", url=None, query="X"
            )
            for r in rows
        ]
        labels: dict[str, str] = {}
        for start in range(0, len(items), 20):
            batch = llm.classify_news("X", items[start : start + 20])
            labels.update({c.id: c.category for c in batch.items})
        return labels

    runs = {k: [llm_labels(v) for _ in range(max(LLM_REPEATS, 1))] for k, v in sets.items()}

    def tally(rows: list[dict[str, Any]], labels: dict[str, str]) -> tuple[int, int]:
        return sum(labels.get(r["id"]) == r["category"] for r in rows), len(rows)

    llm_cells = {k: _agg([tally(clean[k], lab) for lab in runs[k]]) for k in sets}
    res.split(
        "12.5 News desk",
        "Headline category accuracy (LLM classifier)",
        llm_cells["dev"],
        llm_cells.get("test"),
        "≥ 85%",
        lambda v: v >= 0.85,
    )
    adv_runs = [tally(adv, lab) for lab in runs["dev"]]
    res.add(
        "12.5 News desk",
        f"Headlines with an embedded instruction still labelled by content ({len(adv)}, LLM)",
        _agg(adv_runs)[0],
        "100%",
        "PASS" if all(ok == n for ok, n in adv_runs) else "FAIL",
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
    sets = _splits("bottleneck_snippets_labeled.jsonl")
    rules = RuleBasedClassifier(cfg.themes, valid)

    def score(label_of: Any, tag: str, runs: int = 1) -> None:
        """``label_of(split, run, row)`` gives the label; ``runs`` > 1 reports mean and worst."""
        cells: dict[str, list[tuple[str, float]]] = {}
        misses: list[str] = []
        for split, rows in sets.items():
            d_runs: list[tuple[int, int]] = []
            s_runs: list[tuple[int, int]] = []
            f1s: list[float] = []
            for k in range(runs):
                pairs_layer: list[tuple[str, str]] = []
                d_ok = s_ok = 0
                for r in rows:
                    lbl = label_of(split, k, r)
                    d_ok += int(lbl.direction == r["direction"])
                    s_ok += int(lbl.side == r["side"])
                    pairs_layer.append((r["layer_id"], str(lbl.layer_id)))
                    if k == 0 and lbl.direction != r["direction"]:
                        misses.append(f"{split}:{r['id']}→{lbl.direction}")
                d_runs.append((d_ok, len(rows)))
                s_runs.append((s_ok, len(rows)))
                f1s.append(_macro_f1(pairs_layer))
            f1_mean = statistics.mean(f1s)
            f1_cell = (
                f"{f1s[0]:.2f}"
                if runs == 1
                else f"mean {f1_mean:.2f} · worst {min(f1s):.2f} ({runs} runs)"
            )
            cells[split] = [_agg(d_runs), (f1_cell, f1_mean), _agg(s_runs)]
        sizes = "; ".join(f"{k} n={len(v)}" for k, v in sets.items())
        test = cells.get("test")
        res.split(
            "11.2 Constraint classification",
            f"Direction accuracy on hand-labelled filing and news snippets ({tag})",
            cells["dev"][0],
            test[0] if test else None,
            "≥ 0.85",
            lambda v: v >= 0.85,
            sizes + "; " + "; ".join(misses[:12]),
        )
        res.split(
            "11.2 Constraint classification",
            f"Layer macro-F1, no search hint given ({tag})",
            cells["dev"][1],
            test[1] if test else None,
            "≥ 0.80",
            lambda v: v >= 0.80,
            sizes,
        )
        res.split(
            "11.2 Constraint classification",
            f"Side accuracy (customer / supplier / neutral) ({tag})",
            cells["dev"][2],
            test[2] if test else None,
            "report",
            None,
            sizes,
            info=True,
        )

    score(
        lambda _s, _k, r: rules.classify_text(
            r["id"], r["text"], filer=r["filer_ticker"], hint=None
        ),
        "rule-based stand-in",
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

    def snippets_of(rows: list[dict[str, Any]]) -> list[FilingSnippet]:
        return [
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

    llm_runs = {
        split: [clf.classify(snippets_of(rows)) for _ in range(max(LLM_REPEATS, 1))]
        for split, rows in sets.items()
    }
    score(
        lambda split, k, r: llm_runs[split][k][r["id"]],
        f"LLM {llm.models.extraction_model}",
        max(LLM_REPEATS, 1),
    )
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
    """Tax questions through the chat router: the expected tax document is cited, every reply
    passes Compliance including check 11 (disclaimer once, no rate, no filing instruction)."""
    session = ChatSession(deps)
    label = (
        f"LLM {deps.llm.models.explanation_model}" if deps.llm.is_live else "rule-based answerer"
    )
    cells: dict[str, dict[str, tuple[str, float]]] = {}
    misses: list[str] = []
    for split, rows in _splits("tax_questions.jsonl").items():
        routed = cited = passed = disclaimed = 0
        for i, row in enumerate(rows):
            r = session.send(f"eval-tax-{split}-{i}", row["question"])
            ok_route = r.turn.intent == "tax"
            routed += int(ok_route)
            docs = {c.doc_id for c in r.turn.citations}
            ok_cite = row["doc_id"] in docs
            cited += int(ok_cite)
            good = r.turn.compliance is not None and r.turn.compliance.passed
            once = r.turn.text.count(cfg.compliance.tax.disclaimer) == 1
            passed += int(good and once)
            disclaimed += int(once)
            if not (ok_route and ok_cite):
                misses.append(
                    f"{split}:{row['id']}→{r.turn.intent}/{','.join(sorted(docs)) or '-'}"
                )
        n = len(rows)
        cells[split] = {
            "routed": _frac(routed, n),
            "cited": _frac(cited, n),
            "passed": _frac(passed, n),
        }
    test = cells.get("test")
    res.split(
        "12.6 Tax & accounts",
        f"Tax questions routed to the Tax agent ({label})",
        cells["dev"]["routed"],
        test["routed"] if test else None,
        "report",
        None,
        info=True,
    )
    res.split(
        "12.6 Tax & accounts",
        f"Tax questions citing the expected document ({label})",
        cells["dev"]["cited"],
        test["cited"] if test else None,
        "≥ 90%",
        lambda v: v >= 0.9,
        "; ".join(misses) or "every question cited its document",
    )
    res.split(
        "12.6 Tax & accounts",
        "Tax replies passing Compliance with the disclaimer once (check 11: no rate, no instruction)",
        cells["dev"]["passed"],
        test["passed"] if test else None,
        "100%",
        lambda v: v >= 0.999,
    )


# ---------------------------------------------------------------- report
FINGERPRINT_PATHS = ("src", "prompts", "config", "evals/run_evals.py", "evals/datasets")


def code_fingerprint(root: Path = ROOT) -> str:
    """A hash of everything the report measures: the package, prompts, config, this runner and
    the datasets. ``scripts/check_eval_report.py`` compares it with the committed report's."""
    import hashlib

    h = hashlib.sha256()
    for rel in FINGERPRINT_PATHS:
        base = root / rel
        files = [base] if base.is_file() else sorted(base.rglob("*"))
        for f in files:
            if not f.is_file() or "__pycache__" in f.parts or f.suffix in {".pyc", ".sqlite"}:
                continue
            h.update(f.relative_to(root).as_posix().encode())
            h.update(b"\x00")
            h.update(f.read_bytes())
            h.update(b"\x00")
    return h.hexdigest()[:16]


def write_report(res: Results, cfg: Any, llm_label: str) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=UTC)
    fingerprint = code_fingerprint()
    lines = [
        "# OptionsScout AI: evaluation report",
        "",
        f"_Generated {now:%Y-%m-%d %H:%M UTC} · data mode `{cfg.settings.data_mode}` · LLM: {llm_label}"
        f" · LLM rows repeated {LLM_REPEATS}× · code fingerprint `{fingerprint}`_",
        "",
        "Numbers below were measured by `make eval` on this machine. Rows marked **NOT RUN** need a live "
        "LLM key (or the optional `fastembed` extra) and are reported as such rather than estimated.",
        "",
        "**Held-out** is `evals/datasets/test/`: written by people who never saw the rules or prompts "
        "and never opened while a rule or prompt is edited. **Dev** is `evals/datasets/dev/`, the sets "
        "the rules and prompts were built against, so it overstates accuracy on new text. Status grades "
        "both: a dev figure below target is **FAIL** (a regression); a held-out figure below target is "
        "**BELOW TARGET** (reported, never tuned against, and it does not fail the build). A row without "
        "a split shows `-` in the held-out column.",
        "",
        "| Section | Metric | Held-out | Dev | Target | Status | Detail |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in res.metrics:
        lines.append(
            f"| {m.section} | {m.name} | {m.test or '-'} | {m.value} | {m.target} | **{m.status}** | {m.detail} |"
        )
    if res.notes:
        lines += ["", "## Notes", *[f"- {n}" for n in res.notes]]
    lines += [
        "",
        "## Signal study",
        "See `notebooks/signal_study.ipynb` (`evals/signal_study.py`). The corpus is synthetic fixture "
        "data with no stored point-in-time history, so no predictive claim is made. The notebook "
        "documents the method (point-in-time scores, forward 30/60/90-day returns against SPY, a "
        "tercile spread with a bootstrap interval) and reports it on the few observations available; "
        "on a sample that small the interval says nothing about the live signal.",
        "",
    ]
    path = REPORTS / "latest.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (REPORTS / "latest.json").write_text(
        json.dumps([m.__dict__ for m in res.metrics], indent=1), encoding="utf-8"
    )
    (REPORTS / "latest.meta.json").write_text(
        json.dumps(
            {
                "generated": now.isoformat(timespec="seconds"),
                "fingerprint": fingerprint,
                "llm": llm_label,
                "llm_repeats": LLM_REPEATS,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse

    global LLM_REPEATS
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--repeats",
        type=int,
        default=LLM_REPEATS,
        help="times each LLM row is run (mean and worst reported); each repeat is a full pass of calls",
    )
    LLM_REPEATS = max(ap.parse_args(argv).repeats, 1)
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
        if llm is not None:  # W11 step 3: the same runs with the model writing the narrative
            eval_agent(res, cfg, replace(deps, llm=llm), writer=llm.models.explanation_model)
        eval_compliance(res, cfg)
        eval_grounding(res, cfg)
        eval_routing(res, llm)
        eval_retrieval(res, cfg, tmp)
        eval_education(res, cfg, deps)
        eval_chat(res, deps)
        eval_goals(res, cfg)
        eval_news(res, llm)
        eval_bottleneck(res, cfg, llm)
        eval_tax(res, cfg, deps)
    path = write_report(res, cfg, llm_label)
    print(path.read_text(encoding="utf-8"))
    return 0 if all(m.status != "FAIL" for m in res.metrics) else 1


if __name__ == "__main__":
    raise SystemExit(main())
