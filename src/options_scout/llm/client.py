"""Provider abstraction: one function per LLM task, structured outputs everywhere.

Providers
---------
* ``AnthropicProvider`` – official ``anthropic`` SDK, ``messages.parse`` with a Pydantic schema.
* ``FixtureProvider`` – replays cached responses from ``tests/fixtures/llm/<task>/<hash>.json``;
  when no cached response exists it falls back to the deterministic rule-based implementation and
  records that it did so (``cached=False``). Lets CI and the demo run with no API key.
* ``RuleBasedProvider`` – no LLM at all (``--no-llm`` mode): regex/alias based parsing and
  extraction, template narrative.

Every call returns ``(result, TokenUsage)`` so runs can report tokens and cost.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from options_scout.config import AppConfig, LLMMode
from options_scout.core.models import ExtractionBatch, ProfileParse, SocialPost, TokenUsage
from options_scout.llm.prompts import Prompt, load_prompt

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class JudgeScore(BaseModel):
    faithfulness: int
    clarity: int
    policy: int
    notes: str = ""


class Narrative(BaseModel):
    text: str


class LLMProvider(Protocol):
    name: str

    def complete(
        self, *, task: str, model: str, system: str, user: str, schema: type[T], max_tokens: int
    ) -> tuple[T, TokenUsage]: ...


# -------------------------------------------------------------------------------- Anthropic
class AnthropicProvider:
    name = "anthropic"

    def __init__(self, pricing: dict[str, Any]) -> None:
        import anthropic  # lazy: fixture/none modes must not require credentials

        self._client = anthropic.Anthropic()
        self._pricing = pricing

    def complete(
        self, *, task: str, model: str, system: str, user: str, schema: type[T], max_tokens: int
    ) -> tuple[T, TokenUsage]:
        response = self._client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        if response.stop_reason == "refusal":
            raise RuntimeError(f"model refused task={task}: {response.stop_details}")
        parsed = response.parsed_output
        if parsed is None:
            raise RuntimeError(
                f"no parsed output for task={task} (stop_reason={response.stop_reason})"
            )
        usage = response.usage
        price = self._pricing.get(model)
        cost = 0.0
        if price is not None:
            cost = (
                usage.input_tokens * price.input + usage.output_tokens * price.output
            ) / 1_000_000
        return parsed, TokenUsage(
            model=model,
            task=task,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost,
        )


# ---------------------------------------------------------------------------------- fixture
def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:24]


class FixtureProvider:
    """Replay cached structured outputs; fall back to the rule-based provider when none exists."""

    name = "fixture"

    def __init__(self, cache_dir: Path, fallback: LLMProvider, *, record: bool = False) -> None:
        self.cache_dir = cache_dir
        self.fallback = fallback
        self.record = record

    def _path(self, task: str, key: str) -> Path:
        return self.cache_dir / task / f"{key}.json"

    def complete(
        self, *, task: str, model: str, system: str, user: str, schema: type[T], max_tokens: int
    ) -> tuple[T, TokenUsage]:
        key = _hash(task, model, system, user)
        path = self._path(task, key)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return schema.model_validate(data["output"]), TokenUsage(
                model=model, task=task, cached=True
            )
        result, usage = self.fallback.complete(
            task=task, model=model, system=system, user=user, schema=schema, max_tokens=max_tokens
        )
        if self.record:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {"task": task, "model": model, "output": result.model_dump(mode="json")},
                    indent=1,
                ),
                encoding="utf-8",
            )
        return result, usage

    def store(self, *, task: str, model: str, system: str, user: str, output: BaseModel) -> Path:
        path = self._path(task, _hash(task, model, system, user))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"task": task, "model": model, "output": output.model_dump(mode="json")}, indent=1
            ),
            encoding="utf-8",
        )
        return path


# ------------------------------------------------------------------------------- rule-based
class RuleBasedProvider:
    """Deterministic stand-ins. The actual logic lives in ``options_scout.llm.rules``."""

    name = "rule_based"

    def __init__(self, handlers: dict[str, Callable[[str], BaseModel]]) -> None:
        self._handlers = handlers

    def complete(
        self, *, task: str, model: str, system: str, user: str, schema: type[T], max_tokens: int
    ) -> tuple[T, TokenUsage]:
        handler = self._handlers.get(task)
        if handler is None:
            raise RuntimeError(f"rule-based provider has no handler for task={task}")
        out = handler(user)
        if not isinstance(out, schema):
            out = schema.model_validate(out.model_dump())
        return out, TokenUsage(model="rule_based", task=task, cached=False)


# ------------------------------------------------------------------------------------ facade
class LLMClient:
    """One method per task. Prompts are files; schemas are Pydantic; no numbers originate here."""

    def __init__(self, cfg: AppConfig, provider: LLMProvider, mode: LLMMode) -> None:
        self.cfg = cfg
        self.provider = provider
        self.mode = mode
        self.usage: list[TokenUsage] = []

    @classmethod
    def from_config(cls, cfg: AppConfig, mode: LLMMode | None = None) -> LLMClient:
        from options_scout.llm import rules

        mode = mode or cfg.settings.llm_mode
        rule_provider = RuleBasedProvider(rules.handlers(cfg))
        if mode == "anthropic":
            try:
                provider: LLMProvider = AnthropicProvider(cfg.settings.llm.pricing)
            except Exception as exc:  # no credentials → degrade to fixture mode, loudly
                log.warning("Anthropic provider unavailable (%s); using fixture mode", exc)
                mode = "fixture"
                provider = FixtureProvider(cfg.paths.llm_cache_dir, rule_provider)
        elif mode == "fixture":
            provider = FixtureProvider(cfg.paths.llm_cache_dir, rule_provider)
        else:
            provider = rule_provider
        return cls(cfg, provider, mode)

    def _prompt(self, name: str) -> Prompt:
        return load_prompt(self.cfg.paths.prompts_dir, name)

    def _run(self, task: str, model: str, prompt: Prompt, schema: type[T], **vars: str) -> T:
        user = prompt.render(**vars)
        system = f"[{prompt.name} v{prompt.version}] {prompt.task}"
        out, usage = self.provider.complete(
            task=task,
            model=model,
            system=system,
            user=user,
            schema=schema,
            max_tokens=self.cfg.settings.llm.max_output_tokens,
        )
        self.usage.append(usage)
        return out

    # -- tasks -----------------------------------------------------------------------
    def parse_profile(self, request_text: str) -> ProfileParse:
        return self._run(
            "parse_profile",
            self.cfg.settings.llm.extraction_model,
            self._prompt("parse_profile"),
            ProfileParse,
            request_text=request_text,
        )

    def extract_entities(self, posts: Sequence[SocialPost]) -> ExtractionBatch:
        rendered = "\n".join(
            f'<post id="{p.id}" subreddit="{p.subreddit or ""}" '
            f'stock_sub="{str(p.is_stock_sub).lower()}">\n'
            f"{p.title}\n{p.body}\n</post>"
            for p in posts
        )
        return self._run(
            "extract_entities",
            self.cfg.settings.llm.extraction_model,
            self._prompt("extract_entities"),
            ExtractionBatch,
            posts=rendered,
        )

    def explain(self, payload: dict[str, Any]) -> str:
        out = self._run(
            "explain_report",
            self.cfg.settings.llm.explanation_model,
            self._prompt("explain_report"),
            Narrative,
            payload=json.dumps(payload, indent=1, sort_keys=True, default=str),
        )
        return out.text

    def judge(self, payload: dict[str, Any], narrative: str) -> JudgeScore:
        return self._run(
            "judge_explanation",
            self.cfg.settings.llm.judge_model,
            self._prompt("judge_explanation"),
            JudgeScore,
            payload=json.dumps(payload, indent=1, sort_keys=True, default=str),
            narrative=narrative,
        )

    def total_cost(self) -> float:
        return sum(u.cost_usd for u in self.usage)
