"""Thesis monitor (PRD 4A.9): falsifier predicates over consecutive daily snapshots, decay, flags.

A falsifier is ``signal op value for N snapshots``. It trips when the predicate holds on the last
``N`` consecutive daily snapshots (the current run included); a signal that is missing on any of
those days cannot trip it (not evaluable is not the same as holding). When any falsifier of a
layer trips, every company score in the layer is multiplied by ``easing_decay`` and the
``bottleneck_easing`` flag is set. The report says *thesis weakening*; it never says exit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from options_scout.bottleneck.themes import Layer
from options_scout.config import BottleneckScoreConfig
from options_scout.core.models import FalsifierStatus

FLAG_SUPPORT = "bottleneck_support"
FLAG_EASING = "bottleneck_easing"
FLAG_WEAKENING = "thesis_weakening"
FLAG_NO_PRICE_DATA = "no_price_data"

History = Sequence[tuple[date, Mapping[str, float | None]]]  # oldest → newest, current last


def evaluate_falsifiers(layer: Layer, history: History) -> list[FalsifierStatus]:
    """One status per falsifier of ``layer`` given the dated component history."""
    out: list[FalsifierStatus] = []
    for f in layer.falsifiers:
        observed = history[-1][1].get(f.signal) if history else None
        run_start: date | None = None
        run_len = 0
        for day, comps in reversed(history):
            value = comps.get(f.signal)
            if value is None or not f.holds(float(value)):
                break
            run_len += 1
            run_start = day
        tripped = run_len >= f.snapshots
        out.append(
            FalsifierStatus(
                signal=f.signal,
                op=f.op,
                value=f.value,
                snapshots=f.snapshots,
                tripped=tripped,
                since=run_start if tripped else None,
                observed=float(observed) if observed is not None else None,
            )
        )
    return out


def easing_signalled(components: Mapping[str, float | None], cfg: BottleneckScoreConfig) -> bool:
    """4A.8: ``price_deceleration`` or ``supply_response_z`` above its flag threshold."""
    decel = components.get("price_deceleration")
    srz = components.get("supply_response_z")
    return (decel is not None and decel > cfg.flags.price_deceleration_max) or (
        srz is not None and srz > cfg.flags.supply_response_z_max
    )


def apply_thesis(
    score: float, falsifiers: Sequence[FalsifierStatus], cfg: BottleneckScoreConfig
) -> tuple[float, bool]:
    """Return ``(decayed score, weakening)``: the score × ``easing_decay`` when any falsifier
    tripped, unchanged otherwise."""
    weakening = any(f.tripped for f in falsifiers)
    return (round(score * cfg.easing_decay, 2) if weakening else score), weakening


def company_flags(
    score: float,
    components: Mapping[str, float | None],
    falsifiers: Sequence[FalsifierStatus],
    cfg: BottleneckScoreConfig,
) -> list[str]:
    flags: list[str] = []
    if score >= cfg.flags.support_min:
        flags.append(FLAG_SUPPORT)
    weakening = any(f.tripped for f in falsifiers)
    if weakening or easing_signalled(components, cfg):
        flags.append(FLAG_EASING)
    if weakening:
        flags.append(FLAG_WEAKENING)
    if components.get("price_trend") is None:
        flags.append(FLAG_NO_PRICE_DATA)
    return flags
