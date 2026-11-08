"""Run the bottleneck engine, persist a dated snapshot and print the thesis monitor (PRD 4A.9).

Run: ``python -m options_scout.jobs.refresh_bottlenecks [--fixture | --mode live|fixture]
[--no-llm] [--sources edgar,fred,news]``. Snapshots go to ``data/bottleneck_snapshots.sqlite`` and
are kept for ``bottleneck.retention_days``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from options_scout.bottleneck.engine import BottleneckEngine, BottleneckRun, BottleneckStore
from options_scout.config import BOTTLENECK_SOURCE_NAMES, AppConfig, get_config, load_env
from options_scout.llm.client import LLMClient


def store_path(cfg: AppConfig) -> Path:
    return cfg.paths.cache_db.parent / "bottleneck_snapshots.sqlite"


def format_run(run: BottleneckRun, *, top: int = 10) -> str:
    cr = run.classification
    lines = [
        f"Bottleneck board as of {run.as_of:%Y-%m-%d %H:%M} UTC · snippets {run.snippets_in} · "
        f"labels: gt {cr.from_ground_truth}, cache {cr.from_cache}, provider {cr.from_provider}, "
        f"rules {cr.from_rules_fallback} · unvalidated tickers rejected "
        f"{cr.unvalidated_tickers_rejected}",
        "Sources: "
        + " · ".join(
            f"{n} {st.state}" + (f" {st.items}" if st.enabled and st.ok else "")
            for n, st in run.source_status.items()
        ),
        "",
        f"{'layer':<28} {'score':>6} {'tight_z':>8} {'trend':>6} {'decel':>6} {'supply_z':>9} "
        f"{'cross':>6}  thesis",
    ]
    for row in run.layer_rows:
        c = row.components
        trend = f"{c['price_trend']:+.2f}" if "price_trend" in c else "  n/a"
        decel = f"{c['price_deceleration']:.2f}" if "price_deceleration" in c else " n/a"
        state = "WEAKENING" if row.thesis_weakening else "holding"
        key = f"{row.theme_id}/{row.layer_id}"
        lines.append(
            f"{key:<28} {row.score:6.1f} {c.get('tightness_z', 0):8.2f} "
            f"{trend:>6} {decel:>6} {c.get('supply_response_z', 0):9.2f} "
            f"{c.get('cross_source_norm', 0):6.2f}  {state}"
        )
    lines += ["", "Thesis monitor:"]
    for row in run.layer_rows:
        lines.append(f"  {row.theme_id}/{row.layer_id}: {row.thesis}")
        for f in row.falsifiers:
            obs = f"{f.observed:.2f}" if f.observed is not None else "n/a"
            lines.append(
                f"    - {f.signal} {f.op} {f.value:g} for {f.snapshots} snapshot(s): "
                f"{f.state} (observed {obs})"
            )
    companies = sorted(run.company_rows, key=lambda s: s.score, reverse=True)
    lines += ["", f"Top companies (score = layer × exposure; {len(companies)} rows):"]
    for s in companies[:top]:
        flags = f" [{', '.join(s.flags)}]" if s.flags else ""
        tag = "curated" if s.curated else "not on the good-to-own list"
        lines.append(
            f"{s.score:6.1f}  {s.ticker:<6} {s.theme_id}/{s.layer_id:<12} "
            f"exposure {s.components.get('exposure', 0):.2f}  {tag}{flags}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Refresh the bottleneck board snapshot.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mode", choices=["live", "fixture"], default=None)
    mode.add_argument("--fixture", action="store_true", help="shorthand for --mode fixture")
    parser.add_argument("--no-llm", action="store_true", help="rule-based classification only")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument(
        "--sources",
        default=None,
        help=f"comma-separated subset of {','.join(BOTTLENECK_SOURCE_NAMES)} to run",
    )
    args = parser.parse_args(argv)
    if args.sources:
        os.environ["OPTIONS_SCOUT_BOTTLENECK_SOURCES"] = args.sources
        get_config.cache_clear()
    cfg = get_config()
    llm = LLMClient.from_config(cfg, mode="none" if args.no_llm else None)
    store = BottleneckStore(store_path(cfg))
    engine = BottleneckEngine(cfg, llm, mode="fixture" if args.fixture else args.mode, store=store)
    run = engine.run()
    print(format_run(run, top=args.top))
    print(f"\nsnapshots stored: {store.count()} in {store.path}")
    for e in run.errors:
        print("error:", e, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
