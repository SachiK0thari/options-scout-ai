"""Specialist agents (PRD section 5.0): one compiled LangGraph subgraph per file.

Each module exposes ``NAME`` (the parent-graph node name) and ``build_<name>_agent(deps)`` which
returns a compiled subgraph that runs standalone on a fixture state and fills only its slice
(``agent/state.py``). ``agent/graph.py`` composes them in data-dependency order:

    orchestrator → market_intelligence → market_data → strategy → portfolio ⇄ risk
                 → education ⇄ compliance → report

Market Intelligence runs before Market Data because the universe node orders the curated list by
trend score. The node bodies are unchanged from Phase 9 (``agent/nodes/``); the agents only group
and wire them. Specialists never import each other; shared logic lives in ``core/`` and ``social/``.
"""
