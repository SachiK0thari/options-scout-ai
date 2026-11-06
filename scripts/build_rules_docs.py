"""Regenerate knowledge/rules/*.md from PRD.md sections 3.1–3.10 and config/*.yaml.

Usage: .venv/bin/python scripts/build_rules_docs.py [--check]

``make index`` runs this before indexing. ``--check`` exits 1 and lists stale files instead of
writing (the unit test does the same, so CI catches a config change without a regenerated doc).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from options_scout.config import load_config
from options_scout.rag.rules_docs import stale_rules_docs, write_rules_docs


def main(argv: list[str]) -> int:
    cfg = load_config()
    if "--check" in argv:
        stale = stale_rules_docs(cfg)
        if stale:
            print("stale rules docs (run `make index`):", ", ".join(stale))
            return 1
        print("knowledge/rules is up to date")
        return 0
    for path in write_rules_docs(cfg):
        print(path.relative_to(cfg.root))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
