"""Prompt loading, fixture provider replay, and the rule-based stand-ins."""

from __future__ import annotations

from pathlib import Path

import pytest

from options_scout.config import AppConfig
from options_scout.core.models import ProfileParse
from options_scout.llm import rules
from options_scout.llm.client import FixtureProvider, LLMClient, RuleBasedProvider
from options_scout.llm.prompts import load_prompt, prompt_versions


def test_prompts_have_versions_and_render(config: AppConfig) -> None:
    versions = prompt_versions(config.paths.prompts_dir)
    assert set(versions) >= {
        "parse_profile",
        "extract_entities",
        "explain_report",
        "judge_explanation",
    }
    assert all(v.count(".") == 2 for v in versions.values())
    p = load_prompt(config.paths.prompts_dir, "parse_profile")
    text = p.render(request_text="hello")
    assert "<request>\nhello\n</request>" in text
    with pytest.raises(KeyError):
        p.render()


@pytest.mark.parametrize(
    ("text", "bp", "acct", "risk", "needs"),
    [
        (
            "I have $50,000 of buying power in a margin account, balanced risk tolerance.",
            50000,
            "margin",
            "balanced",
            [],
        ),
        (
            "Roth IRA with 25k, I'm pretty conservative. Only CSPs please, no TSLA.",
            25000,
            "cash",
            "conservative",
            [],
        ),
        (
            "Got about 1.2M in a portfolio margin account, aggressive, I like COST and NKE",
            1200000,
            "portfolio_margin",
            "aggressive",
            [],
        ),
        (
            "Show me some income ideas",
            None,
            None,
            None,
            ["buying_power", "account_type", "risk_profile"],
        ),
        (
            "$100k margin, I'm conservative but also want to be aggressive",
            100000,
            "margin",
            None,
            ["risk_profile"],
        ),
    ],
)
def test_rule_parse_profile(
    text: str, bp: float | None, acct: str | None, risk: str | None, needs: list[str]
) -> None:
    out = rules.rule_parse_profile(f"<request>\n{text}\n</request>")
    assert isinstance(out, ProfileParse)
    assert out.buying_power == bp
    assert out.account_type == acct
    assert out.risk_profile == risk
    assert out.needs_clarification == needs


def test_rule_parse_profile_tickers_and_strategies() -> None:
    out = rules.rule_parse_profile(
        "<request>\n$60k margin balanced. CSPs and PMCCs. I like COST, NKE and Starbucks. Skip TSLA and GME.\n</request>"
    )
    assert out.strategies == ["csp", "pmcc"]
    assert set(out.watchlist) == {"COST", "NKE", "SBUX"}
    assert set(out.exclude) == {"TSLA", "GME"}


def test_fixture_provider_replays_then_falls_back(tmp_path: Path, config: AppConfig) -> None:
    calls = {"n": 0}

    def handler(user: str) -> ProfileParse:
        calls["n"] += 1
        return ProfileParse(buying_power=1.0, needs_clarification=["account_type", "risk_profile"])

    rb = RuleBasedProvider({"parse_profile": handler})
    fp = FixtureProvider(tmp_path, rb, record=True)
    out1, u1 = fp.complete(
        task="parse_profile", model="m", system="s", user="u", schema=ProfileParse, max_tokens=10
    )
    assert not u1.cached and calls["n"] == 1
    out2, u2 = fp.complete(
        task="parse_profile", model="m", system="s", user="u", schema=ProfileParse, max_tokens=10
    )
    assert u2.cached and calls["n"] == 1 and out2 == out1


def test_llm_client_none_mode_parses(config: AppConfig) -> None:
    client = LLMClient.from_config(config, mode="none")
    out = client.parse_profile("I have 40k cash, conservative")
    assert out.buying_power == 40000 and out.account_type == "cash"
    assert client.usage and client.usage[0].task == "parse_profile"


@pytest.mark.parametrize("mode", ["live", "anthropic", "openrouter"])
def test_llm_client_live_modes_degrade_without_key(config: AppConfig, mode: str) -> None:
    client = LLMClient.from_config(config, mode=mode)  # type: ignore[arg-type]
    assert client.mode == "fixture" and not client.is_live
    assert client.provider.name == "fixture"
    expected = mode if mode != "live" else config.settings.llm.provider
    assert client.models is config.settings.llm.providers[expected]
