"""W35: the numbers in the docs are rendered from the eval reports and the tree, never typed.

Renders every marked region in memory with ``scripts/render_doc_numbers.py`` and compares with
the committed files, the way ``tests/unit/test_compliance_docs.py`` holds docs/compliance.md to
the code. A failure means a report or the tree changed without the docs being re-rendered:
run ``.venv/bin/python scripts/render_doc_numbers.py`` (``make eval`` does it too).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "render_doc_numbers", ROOT / "scripts" / "render_doc_numbers.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rendered_numbers_match_the_committed_docs() -> None:
    stale = [
        p.relative_to(ROOT).as_posix()
        for p, (old, new) in _script().rendered_files(ROOT).items()
        if old != new
    ]
    assert not stale, f"re-run scripts/render_doc_numbers.py; out of date: {stale}"


def test_every_doc_carries_markers_and_the_readme_table_is_rendered() -> None:
    mod = _script()
    for rel in mod.FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert mod.INLINE.search(text) or mod.BLOCK.search(text), f"{rel} has no number markers"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "<!-- numbers:start eval-table -->" in readme


def test_inline_markers_are_balanced() -> None:
    for rel in _script().FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        opens = len(re.findall(r"<!-- n:[\w.\-]+ -->", text))
        assert opens == text.count("<!-- /n -->"), rel
