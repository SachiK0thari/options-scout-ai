"""Run the social arbitrage pipeline and persist a scored snapshot.

Run: ``python -m options_scout.jobs.refresh_trends [--mode live|fixture]``
"""

from __future__ import annotations

import argparse
import sys

from options_scout.config import get_config
from options_scout.llm.client import LLMClient
from options_scout.social.pipeline import TrendScout, TrendStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the trend board snapshot.")
    parser.add_argument("--mode", choices=["live", "fixture"], default=None)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args(argv)
    cfg = get_config()
    llm = LLMClient.from_config(cfg)
    scout = TrendScout(cfg, llm, mode=args.mode)
    run = scout.run()
    TrendStore(cfg.paths.cache_db.parent / "trends.sqlite").save(run)
    print(
        f"posts={run.posts_in} kept={run.filter_report.kept} entities={run.entities_found} "
        f"signals={len(run.signals)} "
        f"rejected_unvalidated_tickers={run.unvalidated_tickers_rejected}"
    )
    for s in run.signals[: args.top]:
        flags = f" [{', '.join(s.flags)}]" if s.flags else ""
        print(f"{s.score:6.1f}  {s.entity:<20} {s.ticker or '—':<6}{flags}")
    for e in run.errors:
        print("error:", e, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
