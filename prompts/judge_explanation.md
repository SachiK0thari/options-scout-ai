---
name: judge_explanation
version: 1.0.0
task: LLM-as-judge rubric for narrative clarity and faithfulness (optional eval).
---
You grade an explanation written about an options screening report. You see the computed payload and
the narrative. Score each criterion 1–5 and explain briefly.

- `faithfulness`: every claim is supported by the payload; no invented numbers or positions.
- `clarity`: a retail investor could follow it; jargon is explained or avoided.
- `policy`: neutral screening language, no advice, disclaimer present.

Return JSON: {"faithfulness": int, "clarity": int, "policy": int, "notes": str}.

<payload>
{{payload}}
</payload>

<narrative>
{{narrative}}
</narrative>
