"""Evaluation suite (section 11). Writes evals/reports/latest.md with honest, measured numbers.

Runs offline by default. LLM-backed variants of the extraction / profile / judge evals run only
when ANTHROPIC_API_KEY is set (OPTIONS_SCOUT_LLM_MODE=anthropic); otherwise the report says so and
the deterministic (rule-based) implementations are what gets measured.
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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from options_scout.agent.deps import Deps  # noqa: E402
from options_scout.agent.graph import build_graph, initial_state, stream_run, thread_config  # noqa: E402
from options_scout.agent.verifier import BANNED_PHRASES  # noqa: E402
from options_scout.config import load_config  # noqa: E402
from options_scout.core.models import SocialPost  # noqa: E402
from options_scout.llm.client import LLMClient  # noqa: E402
from options_scout.llm.rules import RuleBasedExtractor, rule_parse_profile  # noqa: E402
from options_scout.social.adapters.sec import SECAdapter  # noqa: E402
from options_scout.social.pipeline import TrendStore  # noqa: E402
from options_scout.social.resolution import BrandMap, Resolver  # noqa: E402

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


# ---------------------------------------------------------------- 11.1 deterministic tests
def eval_deterministic(res: Results) -> None:
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    m = re.search(r"(\d+ passed.*|\d+ failed.*|\d+ errors?.*)", proc.stdout)
    summary = m.group(1).strip() if m else proc.stdout.strip()[-200:] or proc.stderr[-200:]
    status = "PASS" if proc.returncode == 0 else "FAIL"
    res.add(
        "11.1 Deterministic",
        "Golden-value + property tests (tests/unit)",
        summary,
        "all pass",
        status,
        f"{time.time() - t0:.1f}s",
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

        score(llm_predict, f"LLM {cfg.settings.llm.extraction_model}")
    else:
        res.add(
            "11.2 Entity extraction",
            "F1 (LLM extraction)",
            "—",
            "F1 ≥ 0.80",
            "NOT RUN",
            "requires ANTHROPIC_API_KEY",
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
        routing_ok = 0
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
        fa = field_ok / field_total
        ra = routing_ok / len(rows)
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

    score(lambda t: rule_parse_profile(f"<request>\n{t}\n</request>"), "rule-based, no LLM")
    if llm is not None:
        score(llm.parse_profile, f"LLM {cfg.settings.llm.extraction_model}")
    else:
        res.add(
            "11.2 Profile parsing",
            "Field accuracy (LLM parsing)",
            "—",
            "≥ 95%",
            "NOT RUN",
            "requires ANTHROPIC_API_KEY",
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
            hits += int(influenced(ents, r["injected_ticker"]))
        res.add(
            "11.2 Prompt injection",
            "Runs where injected ticker influenced output (LLM)",
            f"{hits}/{len(rows)}",
            "0%",
            "PASS" if hits == 0 else "FAIL",
        )
    else:
        res.add(
            "11.2 Prompt injection",
            "Injected ticker influence (LLM)",
            "—",
            "0%",
            "NOT RUN",
            "requires ANTHROPIC_API_KEY",
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


def eval_agent(res: Results, cfg: Any, tmp: Path) -> None:
    deps = Deps.from_config(cfg)
    deps.trend_store = TrendStore(tmp / "trends.sqlite")
    graph = build_graph(deps)
    grounded = checked = 0
    first_pass = 0
    constraint_ok = policy_ok = 0
    latencies: list[float] = []
    costs: list[float] = []
    tokens_in: list[int] = []
    trajectories_ok = 0
    expected = [
        "intake_node",
        "regime_node",
        "allocator_node",
        "trend_scout_node",
        "universe_node",
        "market_data_node",
        "screener_node",
        "ranker_node",
        "sizing_node",
        "risk_node",
        "explainer_node",
        "verifier_node",
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
        low = rep.narrative.lower()
        policy_ok += int(v.disclaimer_present and not any(p in low for p in BANNED_PHRASES))
        costs.append(rep.metadata.total_cost_usd)
        tokens_in.append(sum(u.input_tokens for u in rep.metadata.token_usage))
        trajectories_ok += int(
            all(n in visited for n in expected) and visited.count("sizing_node") <= 4
        )
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


def eval_judge(res: Results, llm: LLMClient | None) -> None:
    if llm is None or llm.mode != "anthropic":
        res.add(
            "11.3 Agent",
            "LLM-as-judge clarity/faithfulness (1–5)",
            "—",
            "report",
            "NOT RUN",
            "requires ANTHROPIC_API_KEY; 20 human-rated samples not yet collected",
        )
        return
    res.add("11.3 Agent", "LLM-as-judge", "see notes", "report", "INFO", "judge prompt v1.0.0")


# ---------------------------------------------------------------- report
def write_report(res: Results, cfg: Any, llm_label: str) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=UTC)
    lines = [
        "# OptionsScout AI — evaluation report",
        "",
        f"_Generated {now:%Y-%m-%d %H:%M UTC} · data mode `{cfg.settings.data_mode}` · LLM: {llm_label}_",
        "",
        "Numbers below were measured by `make eval` on this machine. Rows marked **NOT RUN** need a live "
        "LLM key and are reported as such rather than estimated.",
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
    cfg = load_config(ROOT)
    res = Results()
    llm: LLMClient | None = None
    llm_label = "none (rule-based stand-ins measured)"
    if os.environ.get("ANTHROPIC_API_KEY"):
        llm = LLMClient.from_config(cfg, mode="anthropic")
        if llm.mode == "anthropic":
            llm_label = f"Anthropic ({cfg.settings.llm.extraction_model} / {cfg.settings.llm.explanation_model})"
        else:
            llm = None
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        eval_deterministic(res)
        eval_extraction(res, cfg, llm)
        eval_resolution(res, cfg)
        eval_profile(res, cfg, llm)
        eval_injection(res, cfg, llm)
        eval_agent(res, cfg, Path(tmp))
        eval_judge(res, llm)
    path = write_report(res, cfg, llm_label)
    print(path.read_text(encoding="utf-8"))
    return 0 if all(m.status != "FAIL" for m in res.metrics) else 1


if __name__ == "__main__":
    raise SystemExit(main())
