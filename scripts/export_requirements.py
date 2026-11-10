"""Export ``requirements.txt`` from ``pyproject.toml`` for graders and plain-pip users (step 12.9).

``pyproject.toml`` stays the source of truth: this runs ``uv pip compile`` over the ``dev`` and
``mcp`` extras for Python 3.12 with universal markers, then prepends a header saying so. Run it
through ``make requirements`` after editing the dependency pins.

An existing ``requirements.txt`` is kept as uv's preference, so a re-export only moves the pins
that ``pyproject.toml`` forces to move; CI re-exports and fails on any difference (W42).
``--match-env PYTHON`` constrains every pin to the versions installed in that environment, which
re-aligns the lock with the environment the tests ran in.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = (
    "# requirements.txt is EXPORTED for graders and plain-pip users; pyproject.toml is the source of\n"
    "# truth. Regenerate with `make requirements` after editing pyproject.toml. Equivalent to\n"
    '# `pip install -e ".[dev,mcp]"` on Python 3.12 (the optional [rag] and [trends] extras are not\n'
    '# included; see README "Troubleshooting"). `pip install -r requirements.txt && pip install -e .`\n'
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", default="uv", help="uv executable")
    parser.add_argument("--out", default=ROOT / "requirements.txt", type=Path)
    parser.add_argument(
        "--match-env",
        default=None,
        metavar="PYTHON",
        help="pin to the versions installed in this interpreter's environment",
    )
    args = parser.parse_args(argv)
    cmd = [
        args.uv,
        "pip",
        "compile",
        str(ROOT / "pyproject.toml"),
        "--extra",
        "dev",
        "--extra",
        "mcp",
        "--python-version",
        "3.12",
        "--universal",
        "--custom-compile-command",
        "make requirements",
        "-q",
        "-o",
        str(args.out),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        if args.match_env:
            frozen = subprocess.run(
                [args.uv, "pip", "freeze", "--exclude-editable", "--python", args.match_env],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            constraints = Path(tmp) / "env-constraints.txt"
            constraints.write_text(frozen, encoding="utf-8")
            # first pass moves the pins; the plain pass below keeps them as preferences and
            # writes annotations that do not name this temporary file
            first = subprocess.run([*cmd, "-c", str(constraints)], cwd=ROOT, check=False)
            if first.returncode != 0:
                return first.returncode
        proc = subprocess.run(cmd, cwd=ROOT, check=False)
    if proc.returncode != 0:
        return proc.returncode
    body = args.out.read_text(encoding="utf-8")
    args.out.write_text(HEADER + body, encoding="utf-8")
    pins = sum(1 for line in body.splitlines() if "==" in line and not line.startswith("#"))
    print(f"wrote {args.out.relative_to(ROOT)}: {pins} pinned packages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
