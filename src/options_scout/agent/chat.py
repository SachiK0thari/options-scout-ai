"""Multi-turn conversations over the routed graph (PRD 10, step 10.5).

A ``ChatSession`` sends one user message at a time to a thread, lets the Orchestrator route it,
and turns the outcome into an assistant ``ChatTurn`` whose text always carries the
``ComplianceReport`` it passed:

* ``concept`` / ``why`` / ``off_topic`` / ``goal`` → the graph's ``answer`` and its compliance
  report;
* ``what_if`` → the Orchestrator's diff reply, then a **full run on a new thread** seeded with the
  hypothetical profile (``<thread>-2``, ``<thread>-3`` …);
* ``new_screen`` / ``refine_profile`` on a thread that already holds a report → a **handoff**: the
  new screen runs on a new thread (refinements pause at ``human_review`` for confirmation);
* a first-turn screen runs in place; when it pauses for human review the reply is the review
  prompt and ``resume`` continues it.

Turns are stored on the thread (``chat_history``, a list reducer): the assistant turn produced by
one call is written with the next call's input, so a paused interrupt is never disturbed;
``history`` merges the pending turn. Deterministic texts (summaries, review prompts) are checked
by ``run_compliance`` too, so the invariant "no reply without an audit entry" has no exceptions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    build_graph,
    initial_state,
    next_turn_state,
    pending_interrupt,
    stream_resume,
    stream_run,
    thread_config,
)
from options_scout.core.compliance import WITHHELD_NOTICE, run_compliance
from options_scout.core.models import (
    ChatTurn,
    ComplianceReport,
    Intent,
    Narrative,
    Paragraph,
    ProfileParse,
    ScreeningReport,
)

Status = str  # "completed" | "interrupted" | "handoff"
OnUpdate = Callable[[str, dict[str, Any]], None]


@dataclass
class ChatResult:
    turn: ChatTurn
    thread_id: str  # the thread whose state now holds the reply (may be a new one)
    status: Status
    interrupt: dict[str, Any] | None = None
    new_thread_id: str | None = None
    handoff: dict[str, Any] | None = None  # set when ``run_handoffs=False`` left a screen to start


@dataclass
class ChatSession:
    deps: Deps
    checkpointer: BaseCheckpointSaver[Any] | None = None
    graph: Any = None
    _pending: dict[str, list[ChatTurn]] = field(default_factory=dict)
    _related: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.graph is None:
            self.graph = build_graph(self.deps, self.checkpointer)

    # ------------------------------------------------------------------ public API
    def send(
        self,
        thread_id: str,
        message: str,
        *,
        run_handoffs: bool = True,
        on_update: OnUpdate | None = None,
    ) -> ChatResult:
        user = ChatTurn(role="user", text=message, thread_id=thread_id)
        carried = [*self._pending.pop(thread_id, []), user]
        existing = self._values(thread_id)
        if existing:
            # the previous turn's intent, texts and answer are cleared; the compliance retry
            # counter is per text, so a fresh turn starts at zero
            payload: dict[str, Any] = {
                **next_turn_state(existing),
                "message": message,
                "chat_history": carried,
            }
        else:
            payload = dict(initial_state())
            payload["message"] = message
            payload["chat_history"] = carried
        self._stream(stream_run(self.graph, payload, thread_id), on_update)  # type: ignore[arg-type]
        values = self._values(thread_id)
        intent: Intent | None = values.get("intent")

        if intent == "what_if" and values.get("what_if_profile"):
            handoff = {
                "intent": "what_if",
                "request_text": "",
                "profile": values["what_if_profile"],
                "review_requested": False,
                "diff": list(values.get("what_if_diff") or []),
                "holdings": list(values.get("holdings") or []),
            }
            answer: Narrative = values["answer"]
            return self._start_handoff(
                thread_id,
                handoff,
                carried,
                run_handoffs,
                on_update,
                prefix=answer.markdown,
                compliance=values["compliance"],
            )
        if values.get("handoff"):
            handoff = dict(values["handoff"])
            handoff.setdefault("holdings", list(values.get("holdings") or []))
            return self._start_handoff(thread_id, handoff, carried, run_handoffs, on_update)
        return self._finish(thread_id, intent, values)

    def resume(
        self, thread_id: str, answer: dict[str, Any], *, on_update: OnUpdate | None = None
    ) -> ChatResult:
        """Continue a thread paused at human_review with the confirmed / corrected profile.

        An empty ``answer`` means "confirmed as shown"; LangGraph treats an empty resume value as
        no resume at all, so a harmless marker is sent (``human_review`` ignores unknown keys).
        """
        self._stream(stream_resume(self.graph, thread_id, answer or {"confirmed": True}), on_update)
        values = self._values(thread_id)
        return self._finish(thread_id, values.get("intent"), values)

    def history(self, thread_id: str) -> list[ChatTurn]:
        stored = list(self._values(thread_id).get("chat_history") or [])
        return [*stored, *self._pending.get(thread_id, [])]

    def related_threads(self, thread_id: str) -> list[str]:
        return list(self._related.get(thread_id, []))

    def run_handoff(self, result: ChatResult, *, on_update: OnUpdate | None = None) -> ChatResult:
        """Start a screen that ``send(run_handoffs=False)`` left pending (used by the API)."""
        assert result.handoff is not None and result.new_thread_id is not None
        return self._run_new_thread(
            result.new_thread_id,
            result.handoff,
            self._pending.pop(result.new_thread_id, []),
            on_update,
            prefix=result.turn.text,
            compliance=result.turn.compliance,
        )

    # ------------------------------------------------------------------ internals
    def _values(self, thread_id: str) -> dict[str, Any]:
        snap = self.graph.get_state(thread_config(thread_id))
        return dict(getattr(snap, "values", {}) or {})

    @staticmethod
    def _stream(it: Any, on_update: OnUpdate | None) -> None:
        for update in it:
            if on_update is not None:
                for node, payload in update.items():
                    on_update(node, payload if isinstance(payload, dict) else {})

    def _new_thread_id(self, thread_id: str) -> str:
        base = thread_id.rsplit("-", 1)[0] if thread_id.rsplit("-", 1)[-1].isdigit() else thread_id
        n = len(self._related.get(base, [])) + 2
        new_id = f"{base}-{n}"
        self._related.setdefault(base, []).append(new_id)
        return new_id

    def _start_handoff(
        self,
        thread_id: str,
        handoff: dict[str, Any],
        carried: list[ChatTurn],
        run_handoffs: bool,
        on_update: OnUpdate | None,
        *,
        prefix: str = "",
        compliance: ComplianceReport | None = None,
    ) -> ChatResult:
        new_id = self._new_thread_id(thread_id)
        diff = handoff.get("diff") or []
        if not prefix:
            what = "A refined screen" if handoff["intent"] == "refine_profile" else "A new screen"
            prefix = f"**{what}** is running on thread `{new_id}`" + (
                f" with these changes: {'; '.join(diff)}." if diff else "."
            )
        self._pending[new_id] = [*self.history(thread_id)[:-1], carried[-1]]
        if not run_handoffs:
            notice = compliance or self._check(prefix, {}, extra={"prefix": prefix})
            turn = self._assistant(thread_id, prefix, handoff["intent"], notice, new_id)
            self._pending.setdefault(thread_id, []).append(turn)
            return ChatResult(turn, thread_id, "handoff", new_thread_id=new_id, handoff=handoff)
        return self._run_new_thread(
            new_id,
            handoff,
            self._pending.pop(new_id, []),
            on_update,
            prefix=prefix,
            compliance=compliance,
            origin=thread_id,
        )

    def _run_new_thread(
        self,
        new_id: str,
        handoff: dict[str, Any],
        carried: list[ChatTurn],
        on_update: OnUpdate | None,
        *,
        prefix: str,
        compliance: ComplianceReport | None,
        origin: str | None = None,
    ) -> ChatResult:
        seed = dict(initial_state(handoff.get("request_text") or "", handoff.get("profile")))
        seed["review_requested"] = bool(handoff.get("review_requested"))
        if handoff.get("holdings"):  # Phase 12: what the user owns follows them to the new screen
            seed["holdings"] = list(handoff["holdings"])
        if handoff.get("profile"):  # the review prompt shows the merged profile, not "unknown"
            fields = {k: v for k, v in handoff["profile"].items() if k in ProfileParse.model_fields}
            seed["parsed"] = ProfileParse.model_validate(fields)
        seed["chat_history"] = carried
        self._stream(stream_run(self.graph, seed, new_id), on_update)  # type: ignore[arg-type]
        values = self._values(new_id)
        result = self._finish(new_id, handoff["intent"], values, prefix=prefix)
        if compliance is not None and result.status == "completed":
            # the what-if diff text was checked on the origin thread; keep the earliest report
            result.turn.compliance = result.turn.compliance or compliance
        result.new_thread_id = new_id
        result.turn.new_thread_id = new_id
        if origin is not None:
            self._pending.setdefault(origin, []).append(
                result.turn.model_copy(update={"thread_id": origin})
            )
        return result

    def _finish(
        self, thread_id: str, intent: Intent | None, values: dict[str, Any], *, prefix: str = ""
    ) -> ChatResult:
        interrupt = pending_interrupt(self.graph, thread_id)
        # a prefix (what-if diff, handoff notice) was already checked on its own thread; the
        # disclaimer must appear exactly once, at the end of the combined reply
        prefix = prefix.replace(self.deps.cfg.settings.disclaimer, "").strip()
        if interrupt is not None:
            # the Orchestrator paused before its delta reached the parent state; only a screen
            # (new or refined) ever pauses for human review
            intent = intent or "new_screen"
            text = (prefix + "\n\n" if prefix else "") + review_prompt(interrupt)
            report: ComplianceReport | None = self._check(
                text, values, extra={"review": interrupt, "prefix": prefix}
            )
            turn = self._assistant(thread_id, text, intent, report, None)
            self._pending.setdefault(thread_id, []).append(turn)
            return ChatResult(turn, thread_id, "interrupted", interrupt=interrupt)
        answer: Narrative | None = values.get("answer")
        rep: ScreeningReport | None = values.get("report")
        reply_intents = (
            "concept",
            "why",
            "what_if",
            "off_topic",
            "goal",
            "holdings",
            "news",
            "tax",
        )
        if intent in reply_intents and answer is not None:
            text = answer.markdown
            report = values.get("compliance")
            citations = list(values.get("citations") or [])
        elif rep is not None and (
            rep.withheld or rep.compliance is None or not rep.compliance.passed
        ):
            # W12: the screen failed the gate; the turn carries the fixed notice, never a summary
            # of the positions the gate refused
            text = (prefix + "\n\n" if prefix else "") + withheld_summary(rep)
            report = self._check(text, values, extra={"prefix": prefix})
            citations = []
        elif rep is not None:
            drop = round(self.deps.cfg.risk.realistic_loss_drop * 100)
            text = (prefix + "\n\n" if prefix else "") + screen_summary(rep, drop)
            report = self._check(text, values, summary_of=rep, extra={"prefix": prefix})
            citations = list(rep.citations)
        else:
            text = "The run produced no reply."
            report = self._check(text, values)
            citations = []
        if report is None:  # 13.1 invariant
            raise RuntimeError("chat reply produced without a ComplianceReport")
        turn = self._assistant(thread_id, text, intent, report, None, citations)
        self._pending.setdefault(thread_id, []).append(turn)
        return ChatResult(turn, thread_id, "completed")

    def _assistant(
        self,
        thread_id: str,
        text: str,
        intent: Intent | None,
        compliance: ComplianceReport | None,
        new_thread_id: str | None,
        citations: list[Any] | None = None,
    ) -> ChatTurn:
        return ChatTurn(
            role="assistant",
            text=text,
            intent=intent,
            compliance=compliance,
            citations=citations or [],
            thread_id=thread_id,
            new_thread_id=new_thread_id,
        )

    def _check(
        self,
        text: str,
        values: dict[str, Any],
        *,
        summary_of: ScreeningReport | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ComplianceReport:
        """Compliance for a deterministic reply (summary / review prompt): notice paragraphs."""
        disclaimer = self.deps.cfg.settings.disclaimer
        paragraphs = [Paragraph(mode="notice", text=t) for t in text.split("\n\n") if t.strip()]
        if disclaimer not in text:
            paragraphs.append(Paragraph(mode="notice", text=disclaimer))
        drop = round(self.deps.cfg.risk.realistic_loss_drop * 100)
        payload: dict[str, Any] = (
            {"summary": summary_numbers(summary_of, drop)} if summary_of else {}
        )
        payload["profile_fields"] = values.get("profile_override") or {}
        payload.update(extra or {})  # e.g. the interrupt payload the review prompt echoes
        return run_compliance(
            Narrative(paragraphs=paragraphs),
            payload=payload,
            sources=[],
            facts=None,
            cfg=self.deps.cfg.compliance,
            disclaimer=disclaimer,
            text_kind="answer",
            run_tickers=[],
            rel_tol=self.deps.cfg.settings.agent.verifier_number_tolerance,
            today=self.deps.md.today(),
        )


# ---------------------------------------------------------------------- deterministic texts
def summary_numbers(rep: ScreeningReport, drop_pct: int = 30) -> dict[str, Any]:
    return {
        "decline_pct": drop_pct,
        "positions": len(rep.portfolio.positions),
        "csp": len(rep.csp_candidates),
        "leaps": len(rep.leaps_candidates),
        "passed": sum(1 for q in rep.quality if q.passed),
        "excluded": sum(1 for q in rep.quality if not q.passed),
        "cash_reserve": round(rep.portfolio.totals.cash_reserve),
        "realistic_loss": round(rep.portfolio.totals.realistic_loss),
    }


def screen_summary(rep: ScreeningReport, drop_pct: int = 30) -> str:
    n = summary_numbers(rep, drop_pct)
    return (
        f"**Screen complete** (run `{rep.run_id}`). {n['passed']} underlying(s) passed the "
        f"good-to-own gate and {n['excluded']} were excluded; the screen found {n['csp']} "
        f"cash-secured put and {n['leaps']} LEAPS candidate(s) and sized {n['positions']} "
        f"position(s), keeping {n['cash_reserve']:,} in reserve with a realistic loss of "
        f"{n['realistic_loss']:,} at a {n['decline_pct']}% decline. See the Candidates and "
        f"Portfolio tabs for the tables and the Explanation for the cited narrative. Market data "
        f"is delayed.\n\n"
        f"{rep.disclaimer}"
    )


def withheld_summary(rep: ScreeningReport) -> str:
    """The chat turn for a withheld screen (W12): the fixed notice and its reason codes."""
    reasons = rep.withheld_reasons or (
        [c.name for c in rep.compliance.failed_checks]
        if rep.compliance
        else ["no compliance report"]
    )
    return (
        f"{WITHHELD_NOTICE} Reason codes: {', '.join(reasons)}. The Candidates tab still shows the "
        "screened candidates and the constraint checks; no position is proposed for this "
        f"profile. Market data is delayed.\n\n{rep.disclaimer}"
    )


def review_prompt(interrupt: dict[str, Any]) -> str:
    missing = ", ".join(str(f).replace("_", " ") for f in interrupt.get("needs_clarification", []))
    parsed = interrupt.get("parsed") or {}
    known = ", ".join(
        f"{k.replace('_', ' ')} {v}"
        for k, v in parsed.items()
        if v not in (None, [], {}) and k != "needs_clarification"
    )
    text = "**Please confirm your profile before the screen runs.**"
    if known:
        text += f" Understood so far: {known}."
    if missing:
        text += f" Still needed: {missing}."
    return text
