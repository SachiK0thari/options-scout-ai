"""Record live model outputs into ``tests/fixtures/llm`` so fixture mode replays them (W34 step 7).

Usage: .venv/bin/python scripts/record_llm_fixtures.py [--runs N] [--dry-run]

Runs the end-to-end eval requests (``evals/run_evals.py`` ``REQUESTS``) on fixture market data,
in LLM *fixture* mode, with a recorder in front of the live provider: a call with no recording
goes to the model and its structured output is stored under
``tests/fixtures/llm/<task>/<hash>.json``; a call that has one is replayed. The code path is the
one replay takes, so a later offline run (CI, ``make eval``) finds the same keys and the
verifier, retry loop and paragraph fallback run on model-written text without a key.

A recording is keyed on the task, model, prompt version and the full rendered prompt, so it goes
stale when any of those change (a prompt edit, a payload change, new fixture data). Re-record
then; stale files are simply never read (delete ``tests/fixtures/llm`` first for a clean set).

Cost: one live end-to-end pass of the chosen runs, the same calls as the eval's live agent pass
(profile parsing, entity extraction on the fixture posts, constraint and news classification,
the explanation with its retries). Needs ``OPENROUTER_API_KEY`` or ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=6, help="how many of the eval requests to record")
    ap.add_argument("--dry-run", action="store_true", help="say what would run; call nothing")
    args = ap.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="record-llm-"))
    # never touch the app's own stores while recording
    os.environ.setdefault("OPTIONS_SCOUT_CHECKPOINT_DB", str(tmp / "checkpoints.sqlite"))

    from run_evals import REQUESTS

    from options_scout.agent.deps import Deps
    from options_scout.agent.graph import build_graph, initial_state, stream_run, thread_config
    from options_scout.config import load_config, load_env
    from options_scout.llm.client import _LIVE_PROVIDERS, FixtureProvider, LLMClient
    from options_scout.social.pipeline import TrendStore

    load_env()
    cfg = load_config(ROOT)
    llm_cfg = cfg.settings.llm
    models = llm_cfg.providers.get(llm_cfg.provider, llm_cfg.active)
    requests = REQUESTS[: max(args.runs, 0)]
    cache = cfg.paths.llm_cache_dir
    print(
        f"provider {llm_cfg.provider} · models {models.extraction_model} / {models.explanation_model}"
    )
    print(f"{len(requests)} end-to-end run(s) on fixture market data → {cache}")
    if args.dry_run:
        return 0
    try:
        live = _LIVE_PROVIDERS[llm_cfg.provider](models)
    except Exception as exc:
        print(f"no live provider: {exc}", file=sys.stderr)
        return 2
    before = {p: p.stat().st_mtime for p in cache.rglob("*.json")} if cache.exists() else {}
    llm = LLMClient(cfg, FixtureProvider(cache, live, record=True), "fixture", models)
    deps = replace(Deps.from_config(cfg), llm=llm)
    deps.trend_store = TrendStore(tmp / "trends.sqlite")
    graph = build_graph(deps)
    for i, text in enumerate(requests):
        for _ in stream_run(graph, initial_state(text), f"record-{i}"):
            pass
        rep = graph.get_state(thread_config(f"record-{i}")).values["report"]
        print(
            f"run {i}: narrative {rep.metadata.narrative_source}, passed {rep.verification.passed}"
        )
    used = set(cache.rglob("*.json"))
    print(f"{len(used - before.keys())} new recording(s); {len(used)} in total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
