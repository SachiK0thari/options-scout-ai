"""Load versioned prompts from prompts/*.md (front-matter header + body with {{placeholders}})."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    task: str
    body: str

    def render(self, **kwargs: str) -> str:
        text = self.body
        for key, value in kwargs.items():
            text = text.replace("{{" + key + "}}", value)
        leftover = re.findall(r"{{(\w+)}}", text)
        if leftover:
            raise KeyError(f"prompt {self.name} missing values for {leftover}")
        return text


def parse_prompt(text: str, fallback_name: str) -> Prompt:
    m = _FRONT.match(text)
    meta: dict[str, str] = {}
    body = text
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = text[m.end() :]
    return Prompt(
        name=meta.get("name", fallback_name),
        version=meta.get("version", "0.0.0"),
        task=meta.get("task", ""),
        body=body.strip() + "\n",
    )


@lru_cache(maxsize=32)
def load_prompt(prompts_dir: Path, name: str) -> Prompt:
    path = prompts_dir / f"{name}.md"
    return parse_prompt(path.read_text(encoding="utf-8"), name)


def prompt_versions(prompts_dir: Path) -> dict[str, str]:
    return {
        p.stem: load_prompt(prompts_dir, p.stem).version for p in sorted(prompts_dir.glob("*.md"))
    }
