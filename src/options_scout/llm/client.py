"""Provider abstraction: one function per LLM task, structured outputs everywhere.

Providers
---------
* ``AnthropicProvider`` – official ``anthropic`` SDK, ``messages.parse`` with a Pydantic schema.
* ``OpenRouterProvider`` – any OpenAI-compatible gateway (default OpenRouter, e.g. DeepSeek V4.1
  Flash) via the ``openai`` SDK with ``response_format=json_schema``; the reply is validated with
  the same Pydantic schema and retried once with the validation error if it does not conform.
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
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from options_scout.config import AppConfig, LLMMode, LLMProviderName, LLMProviderSettings
from options_scout.core.models import (
    ConstraintLabelBatch,
    ExtractionBatch,
    GoalParse,
    HoldingsParse,
    Narrative,
    NewsClassificationBatch,
    NewsItem,
    ProfileParse,
    RouteDecision,
    SocialPost,
    TokenUsage,
)
from options_scout.llm.prompts import Prompt, load_prompt

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class JudgeScore(BaseModel):
    faithfulness: int
    clarity: int
    policy: int
    notes: str = ""


class LLMProvider(Protocol):
    name: str

    def complete(
        self, *, task: str, model: str, system: str, user: str, schema: type[T], max_tokens: int
    ) -> tuple[T, TokenUsage]: ...


# -------------------------------------------------------------------------------- Anthropic
class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: LLMProviderSettings) -> None:
        import anthropic  # lazy: fixture/none modes must not require credentials

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic()
        self._pricing = settings.pricing

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
        return parsed, TokenUsage(
            model=model,
            task=task,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=_list_price(self._pricing, model, usage.input_tokens, usage.output_tokens),
        )


def _list_price(
    pricing: dict[str, Any], model: str, input_tokens: int, output_tokens: int
) -> float:
    price = pricing.get(model)
    if price is None:
        return 0.0
    return float(input_tokens * price.input + output_tokens * price.output) / 1_000_000


# ------------------------------------------------------------------------------- OpenRouter
_DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1"
_DETERMINISTIC_TASKS = frozenset(
    {"parse_profile", "extract_entities", "route_message"}
)  # temperature 0


class OpenRouterProvider:
    """OpenAI-compatible chat completions with JSON-schema structured output.

    Works with OpenRouter (default) or any gateway exposing ``/chat/completions``. The schema is
    sent as ``response_format={"type": "json_schema"}`` and ``provider.require_parameters`` asks
    OpenRouter to route only to backends that honour it; the body is still validated locally with
    the Pydantic schema, and one corrective retry is made if validation fails.
    """

    name = "openrouter"

    def __init__(self, settings: LLMProviderSettings, *, http_client: Any | None = None) -> None:
        import openai  # lazy: fixture/none modes must not require credentials

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=settings.base_url or _DEFAULT_OPENROUTER_URL,
            default_headers={
                "HTTP-Referer": "https://github.com/options-scout-ai",
                "X-Title": "OptionsScout AI (educational screener)",
            },
            max_retries=3,
            http_client=http_client,  # tests inject an httpx.MockTransport client
        )
        self._pricing = settings.pricing
        self._reasoning_effort = settings.reasoning_effort

    def complete(
        self, *, task: str, model: str, system: str, user: str, schema: type[T], max_tokens: int
    ) -> tuple[T, TokenUsage]:
        from openai.types.chat import ChatCompletionMessageParam
        from openai.types.shared_params import ResponseFormatJSONSchema

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        response_format: ResponseFormatJSONSchema = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "strict": True,
                "schema": strict_json_schema(schema.model_json_schema()),
            },
        }
        totals = TokenUsage(model=model, task=task)
        last_error: Exception | None = None
        for attempt in range(2):
            kwargs: dict[str, Any] = {}
            if task in _DETERMINISTIC_TASKS:
                kwargs["temperature"] = 0.0
            extra: dict[str, Any] = {
                "provider": {"require_parameters": True},
                "usage": {"include": True},
            }
            if self._reasoning_effort is not None:
                extra["reasoning"] = {"effort": self._reasoning_effort}
            response = self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                response_format=response_format,
                extra_body=extra,
                **kwargs,
            )
            totals = _add_usage(totals, response, self._pricing)
            if not response.choices:
                raise RuntimeError(f"empty response for task={task}")
            choice = response.choices[0]
            refusal = getattr(choice.message, "refusal", None)
            if refusal:
                raise RuntimeError(f"model refused task={task}: {refusal}")
            text = choice.message.content or ""
            if getattr(choice, "finish_reason", None) == "length":
                # out of tokens: a corrective retry with the same budget is cut off again
                raise RuntimeError(
                    f"output cut off for task={task} at max_tokens={max_tokens} after "
                    f"{len(text)} chars (reasoning tokens share the budget; see "
                    "llm.max_output_tokens and reasoning_effort)"
                )
            try:
                return schema.model_validate_json(_strip_fences(text)), totals
            except ValueError as exc:  # pydantic.ValidationError subclasses ValueError
                last_error = exc
                log.warning(
                    "openrouter task=%s attempt=%d: output failed schema validation (%s; %s; "
                    "finish_reason=%s, %d chars)",
                    task,
                    attempt + 1,
                    str(exc).splitlines()[0],
                    validation_summary(exc),
                    getattr(choice, "finish_reason", None),
                    len(text),
                )
                messages = [
                    *messages,
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply did not match the required JSON schema:\n"
                            f"{exc}\nReply again with only a JSON object that matches the schema."
                        ),
                    },
                ]
        raise RuntimeError(f"schema validation failed for task={task}: {last_error}")


def validation_summary(exc: Exception, limit: int = 3) -> str:
    """Where and why a reply failed validation, without the reply's text: ``loc: type`` for the
    first ``limit`` errors (a JSON syntax error reports its position instead)."""
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return type(exc).__name__
    try:
        items = errors(include_input=False, include_url=False)
    except TypeError:
        items = errors()
    parts = [
        f"{'.'.join(str(x) for x in e.get('loc', ())) or '<root>'}: {e.get('type', '?')}"
        for e in items[:limit]
    ]
    more = len(items) - limit
    return ", ".join(parts) + (f" (+{more} more)" if more > 0 else "")


def strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a Pydantic JSON schema acceptable to strict structured-output modes.

    Strict mode (OpenAI and the OpenRouter backends that honour it) requires every property of
    every object to be listed in ``required`` and ``additionalProperties: false``. Pydantic leaves
    defaulted fields out of ``required``, and a model given such a schema simply omits them: the
    profile-parsing eval measured 42% field accuracy because ``account_type`` and ``risk_profile``
    never came back at all. Listing them as required (``null`` stays allowed through ``anyOf``)
    makes "unknown" an explicit ``null`` instead of a missing key.
    """
    out = dict(schema)
    if out.get("type") == "object" and isinstance(out.get("properties"), dict):
        props = {k: strict_json_schema(v) for k, v in out["properties"].items()}
        out["properties"] = props
        out["required"] = list(props)
        out["additionalProperties"] = False
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(out.get(key), list):
            out[key] = [strict_json_schema(v) for v in out[key]]
    if isinstance(out.get("items"), dict):
        out["items"] = strict_json_schema(out["items"])
    if isinstance(out.get("$defs"), dict):
        out["$defs"] = {k: strict_json_schema(v) for k, v in out["$defs"].items()}
    return out


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def _add_usage(totals: TokenUsage, response: Any, pricing: dict[str, Any]) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return totals
    inp = int(getattr(usage, "prompt_tokens", 0) or 0)
    out = int(getattr(usage, "completion_tokens", 0) or 0)
    extra = getattr(usage, "model_extra", None) or {}
    reported = extra.get("cost")
    cost = float(reported) if reported is not None else _list_price(pricing, totals.model, inp, out)
    return totals.model_copy(
        update={
            "input_tokens": totals.input_tokens + inp,
            "output_tokens": totals.output_tokens + out,
            "cost_usd": totals.cost_usd + cost,
        }
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


_LIVE_PROVIDERS: dict[LLMProviderName, Callable[[LLMProviderSettings], LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openrouter": OpenRouterProvider,
}


# ------------------------------------------------------------------------------------ facade
class LLMClient:
    """One method per task. Prompts are files; schemas are Pydantic; no numbers originate here."""

    def __init__(
        self, cfg: AppConfig, provider: LLMProvider, mode: LLMMode, models: LLMProviderSettings
    ) -> None:
        self.cfg = cfg
        self.provider = provider
        self.mode: LLMMode = mode
        self.models = models  # model names used for calls and labels
        self.usage: list[TokenUsage] = []

    @property
    def is_live(self) -> bool:
        """True when calls go to a real LLM API (as opposed to fixture replay / rules)."""
        return self.mode == "live"

    @classmethod
    def from_config(cls, cfg: AppConfig, mode: LLMMode | None = None) -> LLMClient:
        from options_scout.llm import rules

        mode = mode or cfg.settings.llm_mode
        llm_cfg = cfg.settings.llm
        provider_name: LLMProviderName = llm_cfg.provider
        if mode in ("anthropic", "openrouter"):
            provider_name = mode
            mode = "live"
        models = llm_cfg.providers.get(provider_name, llm_cfg.active)
        rule_provider = RuleBasedProvider(rules.handlers(cfg))
        provider: LLMProvider
        if mode == "live":
            try:
                provider = _LIVE_PROVIDERS[provider_name](models)
            except Exception as exc:  # no credentials → degrade to fixture mode, loudly
                log.warning("%s provider unavailable (%s); using fixture mode", provider_name, exc)
                mode = "fixture"
                provider = FixtureProvider(cfg.paths.llm_cache_dir, rule_provider)
        elif mode == "fixture":
            provider = FixtureProvider(cfg.paths.llm_cache_dir, rule_provider)
        else:
            provider = rule_provider
        return cls(cfg, provider, mode, models)

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
            self.models.extraction_model,
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
            self.models.extraction_model,
            self._prompt("extract_entities"),
            ExtractionBatch,
            posts=rendered,
        )

    def explain(
        self,
        payload: dict[str, Any],
        sources: str = "",
        audience: str = "intermediate: define unusual terms on first use",
    ) -> Narrative:
        """Tagged paragraphs explaining a report; ``sources`` is the rendered ``[Sn]`` block and
        ``audience`` the reader's level (Phase 12)."""
        return self._run(
            "explain_report",
            self.models.explanation_model,
            self._prompt("explain_report"),
            Narrative,
            payload=json.dumps(payload, indent=1, sort_keys=True, default=str),
            sources=sources or "(no sources retrieved)",
            audience=audience,
        )

    def answer_concept(
        self,
        question: str,
        sources: str,
        disclaimer: str,
        intent: str = "concept",
        audience: str = "intermediate: define unusual terms on first use",
    ) -> Narrative:
        """Cited answer to an education (``concept``) or run (``why``) question from sources."""
        return self._run(
            "answer_concept",
            self.models.explanation_model,
            self._prompt("answer_concept"),
            Narrative,
            question=question,
            sources=sources or "(no sources retrieved)",
            disclaimer=disclaimer,
            intent=intent,
            audience=audience,
        )

    def route_message(
        self, message: str, *, has_report: bool, profile: str = "none"
    ) -> RouteDecision:
        """Orchestrator intent routing (step 10.5); the rule-based fallback has the same schema."""
        return self._run(
            "route_message",
            self.models.extraction_model,
            self._prompt("route_message"),
            RouteDecision,
            message=message,
            has_report="exists" if has_report else "does not exist yet",
            profile=profile,
        )

    def parse_goal(self, message: str, profile: str = "none") -> GoalParse:
        """Goal Planning intake (Phase 12 step 12.3); the rule-based parser has the same schema."""
        return self._run(
            "parse_goal",
            self.models.extraction_model,
            self._prompt("parse_goal"),
            GoalParse,
            message=message,
            profile=profile,
        )

    def explain_goal(self, payload: dict[str, Any], sources: str, disclaimer: str) -> Narrative:
        """Tagged paragraphs explaining a computed ``GoalPlan`` (Phase 12 step 12.3)."""
        return self._run(
            "explain_goal",
            self.models.explanation_model,
            self._prompt("explain_goal"),
            Narrative,
            payload=json.dumps(payload, indent=1, sort_keys=True, default=str),
            sources=sources or "(no sources retrieved)",
            disclaimer=disclaimer,
        )

    def parse_holdings(self, message: str) -> HoldingsParse:
        """Holdings intake (Phase 12 step 12.4); the rule-based parser has the same schema."""
        return self._run(
            "parse_holdings",
            self.models.extraction_model,
            self._prompt("parse_holdings"),
            HoldingsParse,
            message=message,
        )

    def classify_news(self, ticker: str, items: Sequence[NewsItem]) -> NewsClassificationBatch:
        """News Desk labels (Phase 12 step 12.5); headlines are rendered as data."""
        rendered = "\n".join(
            f'<headline id="{n.id}" source="{n.source}" published="{n.published_at:%Y-%m-%d}">'
            f"\n{n.title}\n</headline>"
            for n in items
        )
        return self._run(
            "classify_news",
            self.models.extraction_model,
            self._prompt("classify_news"),
            NewsClassificationBatch,
            ticker=ticker,
            headlines=rendered,
        )

    def classify_bottleneck(self, snippets: Sequence[Any], theme_map: Any) -> ConstraintLabelBatch:
        """Bottleneck snippet labels (Phase 11, section 4A.6); snippets are rendered as data."""
        from options_scout.bottleneck.classify import render_layers, render_snippets

        return self._run(
            "classify_bottleneck",
            self.models.extraction_model,
            self._prompt("classify_bottleneck"),
            ConstraintLabelBatch,
            layers=render_layers(theme_map),
            snippets=render_snippets(snippets),
        )

    def answer_tax(
        self,
        question: str,
        sources: str,
        facts: dict[str, Any],
        disclaimer: str,
        tax_disclaimer: str,
    ) -> Narrative:
        """Cited tax / account-type answer (Phase 12 step 12.6); illustrative facts are data."""
        return self._run(
            "answer_tax",
            self.models.explanation_model,
            self._prompt("answer_tax"),
            Narrative,
            question=question,
            sources=sources or "(no sources retrieved)",
            facts=json.dumps(facts, indent=1, sort_keys=True, default=str),
            disclaimer=disclaimer,
            tax_disclaimer=tax_disclaimer,
        )

    def judge(self, payload: dict[str, Any], narrative: str) -> JudgeScore:
        return self._run(
            "judge_explanation",
            self.models.judge_model,
            self._prompt("judge_explanation"),
            JudgeScore,
            payload=json.dumps(payload, indent=1, sort_keys=True, default=str),
            narrative=narrative,
        )

    def total_cost(self) -> float:
        return sum(u.cost_usd for u in self.usage)
