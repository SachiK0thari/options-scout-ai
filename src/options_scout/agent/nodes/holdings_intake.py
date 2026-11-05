"""holdings_intake_node (Portfolio, Phase 12 step 12.4): the positions a chat turn lists.

The LLM (``parse_holdings``) or the regex stand-in reads "200 AAPL at 150", "AAPL 200 @ 300",
"300 shares of NKE" and CSV lines. Lots of one ticker are merged. Tickers the model proposes are
kept only if they are real listed symbols (the SEC company list the app already ships), so a
mis-read word never becomes a position. Nothing is priced here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.holdings import merge_holdings
from options_scout.core.models import Holding
from options_scout.llm.rules import rule_parse_holdings

CLARIFICATION = (
    "I could not read any positions. List them as 'ticker shares [at cost]', for example "
    "'200 AAPL at 150, MSFT 100 @ 300, 40 SPY', or paste CSV lines 'ticker,shares,cost'."
)


def known_tickers(deps: Deps) -> set[str]:
    """Listed symbols: the curated universe plus the SEC company list when it is available."""
    known = set(deps.cfg.quality.symbols)
    try:
        from options_scout.social.adapters.sec import SECAdapter

        sec = SECAdapter(
            deps.cfg.settings.data_mode,
            deps.cfg.paths.fixtures_dir / "sec_company_tickers.json",
            deps.cfg.paths.cache_db.parent / "sec_company_tickers.json",
        )
        known |= set(sec.companies())
    except Exception:  # the fixture is bundled; a failure here must not block the turn
        pass
    return known


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def holdings_intake_node(state: AgentState) -> dict[str, Any]:
        text = (state.get("holdings_text") or state.get("message") or "").strip()
        errors: list[str] = []
        usage_before = len(deps.llm.usage)
        try:
            parsed = deps.llm.parse_holdings(text)
        except Exception as exc:
            errors.append(f"holdings_intake: LLM parser failed ({exc}); using the regex parser")
            parsed = rule_parse_holdings(f"<message>\n{text}\n</message>")
        listed = known_tickers(deps)
        kept: list[Holding] = []
        dropped: list[str] = []
        for h in parsed.holdings:
            if h.ticker in listed:
                kept.append(h)
            else:
                dropped.append(h.ticker)
        if dropped:
            unknown = ", ".join(sorted(set(dropped)))
            errors.append(f"holdings_intake: unknown symbols dropped: {unknown}")
        holdings = merge_holdings(kept)
        return {
            "holdings": holdings,
            "holdings_analysis": None,
            "token_usage": deps.llm.usage[usage_before:],
            "errors": errors,
        }

    return holdings_intake_node
