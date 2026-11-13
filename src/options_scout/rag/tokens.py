"""Config values written into the knowledge articles at load time (W26 step 2).

An article writes ``{{ranking.social_pct}}`` where it would otherwise type "10%", so a change to
``config/settings.yaml`` or ``config/risk_profiles.yaml`` reaches every article without an edit.
:func:`render` replaces each token; an unknown token is an error, never left in the text.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from options_scout.config import AppConfig, Constraints

TOKEN = re.compile(r"\{\{\s*([a-z0-9_.]+)\s*\}\}")
_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
# a constraint that applies only when the user entered holdings, and one only for margin accounts
HOLDINGS_ONLY = ("max_ticker_concentration_after_assignment",)
MARGIN_ONLY = ("max_margin_usage",)


def _pct(x: float) -> str:
    return f"{x * 100:g}%"


def _times(x: float) -> str:
    return f"{x:.1f}x"


def _word(n: int) -> str:
    return _WORDS[n] if 0 <= n < len(_WORDS) else str(n)


def knowledge_tokens(cfg: AppConfig) -> dict[str, str]:
    """Every token an article may use, rendered from the config in force."""
    w = cfg.settings.ranking.weights
    out: dict[str, str] = {
        "ranking.option_quality_pct": _pct(w.option_quality),
        "ranking.stock_quality_pct": _pct(w.stock_quality),
        "ranking.social_pct": _pct(w.social),
        "ranking.bottleneck_pct": _pct(w.bottleneck),
        "risk.realistic_loss_drop_pct": _pct(cfg.risk.realistic_loss_drop),
    }
    for name, value in cfg.settings.ranking.option_quality_weights.model_dump().items():
        out[f"ranking.option.{name}_pct"] = _pct(float(value))
    every = list(Constraints.model_fields)
    always = [f for f in every if f not in HOLDINGS_ONLY]
    out["risk.constraints_margin"] = _word(len(always))
    out["risk.constraints_cash"] = _word(len([f for f in always if f not in MARGIN_ONLY]))
    out["risk.constraints_with_holdings"] = _word(len(every))
    for profile, limits in cfg.risk.constraints.items():
        for name, value in limits.model_dump().items():
            fmt = _times if name.endswith("_x") else _pct
            out[f"risk.{profile}.{name}"] = fmt(float(value))
    return out


def render(text: str, tokens: Mapping[str, str], *, where: str = "") -> str:
    def one(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in tokens:
            raise ValueError(f"{where or '<text>'}: unknown knowledge token {{{{{key}}}}}")
        return tokens[key]

    return TOKEN.sub(one, text)
