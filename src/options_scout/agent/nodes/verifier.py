"""Deprecated name (Phase 10, step 10.1): ``verifier_node`` is now ``compliance_node``.

Re-exported for one release; import from ``options_scout.agent.nodes.compliance`` instead.
"""

from __future__ import annotations

from options_scout.agent.nodes.compliance import make, make_router

__all__ = ["make", "make_router"]
