"""W34 step 3: no prompt example may be (nearly) an eval row.

A routing or parsing prompt that carries an eval message as its example scores the model on the
answer it was shown. Every quoted example in ``prompts/*.md`` is compared with every text field of
every row in ``evals/datasets/dev/`` and ``evals/datasets/test/``. A failure names the prompt, the
example and the row *id*; the row text is not printed, so a test-split row stays unread by whoever
is editing the prompt.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "prompts"
SPLITS = (ROOT / "evals" / "datasets" / "dev", ROOT / "evals" / "datasets" / "test")
# `entity` (brand-to-ticker rows) is left out: the resolver is rule-based and reads no prompt, and a
# brand name given as a normalisation example ("Trader Joe's") is not an eval answer.
TEXT_FIELDS = ("message", "request_text", "title", "body", "question", "text")

RATIO = 0.8  # whole-string similarity at which an example counts as the row
CONTAINED_WORDS = 5  # an example this long found verbatim inside a row counts as the row

_QUOTED = re.compile(r"\"([^\"\n]{6,200})\"")


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9$%.]+", " ", s.lower()).split()).strip(" .")


def prompt_examples() -> list[tuple[str, str]]:
    """(prompt file, example) for every double-quoted phrase of two words or more."""
    out: list[tuple[str, str]] = []
    for path in sorted(PROMPTS.glob("*.md")):
        body = path.read_text(encoding="utf-8").split("---", 2)[-1]
        for m in _QUOTED.finditer(body):
            ex = m.group(1)
            if "{{" in ex or len(_norm(ex).split()) < 2:
                continue
            out.append((path.name, ex))
    return out


def dataset_texts() -> list[tuple[str, str, str]]:
    """(split/file, row id, text) for every text field of every labelled row."""
    out: list[tuple[str, str, str]] = []
    for split in SPLITS:
        for path in sorted(split.glob("*.jsonl")):
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
                if not line.strip():
                    continue
                row = json.loads(line)
                rid = str(row.get("id", i))
                texts = [row[f] for f in TEXT_FIELDS if isinstance(row.get(f), str)]
                texts += [p["text"] for p in row.get("paragraphs", []) if isinstance(p, dict)]
                for t in texts:
                    out.append((f"{split.name}/{path.name}", rid, t))
    return out


def overlaps() -> list[str]:
    rows = [(where, rid, _norm(t)) for where, rid, t in dataset_texts()]
    found: list[str] = []
    for prompt, ex in prompt_examples():
        e = _norm(ex)
        long_enough = len(e.split()) >= CONTAINED_WORDS
        for where, rid, t in rows:
            sm = SequenceMatcher(None, e, t, autojunk=False)
            near = (
                sm.real_quick_ratio() >= RATIO and sm.quick_ratio() >= RATIO and sm.ratio() >= RATIO
            )
            if near or (long_enough and f" {e} " in f" {t} "):
                found.append(f"{prompt}: example {ex!r} matches {where} row {rid}")
    return found


def test_prompts_carry_examples_to_check() -> None:
    # guards the extractor: if quoting style changes and nothing is found, the test below is vacuous
    assert len(prompt_examples()) >= 30
    assert len(dataset_texts()) >= 500


def test_no_prompt_example_is_an_eval_row() -> None:
    found = overlaps()
    assert not found, "prompt examples that appear in an eval split:\n" + "\n".join(found)
