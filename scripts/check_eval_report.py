"""Fail when the committed eval report is older than the code it describes (W34 step 7).

Usage: .venv/bin/python scripts/check_eval_report.py

``make eval`` writes ``evals/reports/latest.meta.json`` with a fingerprint of the package, the
prompts, the config, the eval runner and the datasets. This compares it with the tree as it is
now: a mismatch means a number in ``latest.md`` may no longer be what the code would measure.
Fix by re-running ``make eval`` (with the LLM key, if the report should keep its live rows).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))


def main() -> int:
    from run_evals import REPORTS, code_fingerprint

    meta_path = REPORTS / "latest.meta.json"
    if not meta_path.exists():
        print(f"{meta_path.relative_to(ROOT)} is missing: run `make eval`", file=sys.stderr)
        return 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    now = code_fingerprint()
    if meta.get("fingerprint") != now:
        print(
            f"evals/reports/latest.md was generated {meta.get('generated')} for code "
            f"{meta.get('fingerprint')}; the tree is now {now}. Re-run `make eval`.",
            file=sys.stderr,
        )
        return 1
    print(f"eval report matches the code ({now}, generated {meta.get('generated')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
