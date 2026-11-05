"""tax_math_node (Tax & Accounts, Phase 12 step 12.6): illustrative mechanics from the thread.

``core/tax.py`` on the screened put the question names (else the top-ranked put): assignment
basis, what the premium would be if the put expires, the LEAPS long-term threshold, the wash-sale
window around today, and the Section 1256 status of the run's tickers. Never a liability, never a
rate; without a screen the reply explains mechanics without an illustration.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core import tax
from options_scout.core.models import OptionCandidate, TaxFacts


def _pick_put(state: AgentState, question: str) -> OptionCandidate | None:
    puts = [c for c in state.get("candidates") or [] if c.strategy == "csp"]
    if not puts:
        return None
    named = set(re.findall(r"\b[A-Z]{1,5}\b", question))
    for r in state.get("ranked") or []:
        if r.candidate.strategy == "csp" and r.candidate.ticker in named:
            return r.candidate
    for r in state.get("ranked") or []:
        if r.candidate.strategy == "csp":
            return r.candidate
    return puts[0]


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def tax_math_node(state: AgentState) -> dict[str, Any]:
        cfg = deps.cfg.tax
        today = deps.md.today()
        question = state.get("question") or state.get("tax_text") or ""
        profile = state.get("profile")
        notes: list[str] = []
        facts = TaxFacts(as_of=today, account_type=profile.account_type if profile else None)
        put = _pick_put(state, question)
        if put is None:
            notes.append("no screen on this thread: mechanics only, no candidate to illustrate")
        else:
            basis = tax.assigned_share_basis(put.strike, put.mid, 1)
            expired = tax.short_put_outcome(put.mid, 1)
            facts = facts.model_copy(
                update={
                    "candidate_id": put.id,
                    "ticker": put.ticker,
                    "strike": put.strike,
                    "premium": round(put.mid, 2),
                    "assigned_basis_per_share": round(basis.basis_per_share, 2),
                    "assigned_total_basis": round(basis.total_basis, 2),
                    "cash_paid_at_assignment": round(basis.cash_paid, 2),
                    "premium_if_expired": round(expired.gain, 2),
                }
            )
        leaps = next((c for c in state.get("candidates") or [] if c.strategy == "leaps"), None)
        if leaps is not None:
            hp = tax.holding_period(today, today)
            facts = facts.model_copy(
                update={
                    "leaps_candidate_id": leaps.id,
                    "leaps_long_term_from": hp.long_term_from,
                    "leaps_days_to_long_term": hp.days_remaining,
                }
            )
        window = tax.wash_sale_window(today, cfg)
        tickers = sorted(set(state.get("universe") or []) | ({put.ticker} if put else set()))
        facts = facts.model_copy(
            update={
                "wash_sale_window_start": window.start,
                "wash_sale_window_end": window.end,
                "wash_sale_window_days": window.window_days,
                "section_1256": {t: tax.section_1256_status(t, cfg) for t in tickers},
                "notes": notes,
            }
        )
        return {"tax_facts": facts}

    return tax_math_node
