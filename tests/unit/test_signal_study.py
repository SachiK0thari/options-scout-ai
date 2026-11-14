"""W36: the signal study prints no interval it has not earned."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "signal_study", ROOT / "evals" / "signal_study.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["signal_study"] = mod  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


ss = _load()
D0 = datetime(2026, 9, 1)
INTERVAL = re.compile(r"\[[+-]\d+\.\d+%, [+-]\d+\.\d+%\]")


def _obs(n_dates: int, n_tickers: int, gap_days: int = 31) -> list[object]:
    out = []
    for i in range(n_dates):
        for j in range(n_tickers):
            r = 0.01 * ((i * n_tickers + j) % 7 - 3)
            out.append(
                ss.Observation(
                    D0 + timedelta(days=gap_days * i),
                    f"T{j}",
                    (f"T{j}",),
                    float(j * 3 + i),
                    {30: r, 60: None, 90: None},
                    {30: 0.0, 60: None, 90: None},
                )
            )
    return out


def test_entities_on_one_ticker_collapse_to_one_observation() -> None:
    rows = [
        (D0, "Costco", "COST", 42.0),
        (D0, "Kirkland Signature", "COST", 36.0),
        (D0, "Nike", "NKE", 30.0),
    ]
    collapsed = ss.collapse_by_ticker(rows)
    assert [(t, e, s) for _, t, e, s in collapsed] == [
        ("COST", ("Costco", "Kirkland Signature"), 42.0),
        ("NKE", ("Nike",), 30.0),
    ]


def test_overlapping_forward_windows_are_not_counted_twice() -> None:
    weekly = [D0 + timedelta(days=7 * k) for k in range(10)]
    assert ss.independent_dates(weekly, 30) == [D0, D0 + timedelta(days=35)]
    assert len(ss.usable(_obs(3, 4, gap_days=7), 30)) == 4  # one date of the three survives


def test_no_interval_below_the_minimum() -> None:
    iv = ss.mean_interval([0.05, 0.10, 0.08, 0.12, 0.09, 0.11, 0.07, 0.10])
    assert iv is not None and iv.lo is None and iv.hi is None


def test_interval_is_a_t_interval() -> None:
    from scipy.stats import t

    xs = [0.01 * (k % 9 - 4) for k in range(30)]
    iv = ss.mean_interval(xs)
    assert iv is not None and iv.lo is not None and iv.hi is not None
    half = (iv.hi - iv.lo) / 2
    import statistics

    se = statistics.stdev(xs) / len(xs) ** 0.5
    assert half == pytest.approx(t.ppf(0.975, 29) * se)
    assert half > 1.96 * se


def test_synthetic_corpus_prints_no_interval_and_labels_every_table() -> None:
    text = "\n".join(ss.render_trend_study(_obs(4, 30), synthetic=True))  # 120 independent rows
    assert not INTERVAL.search(text)
    assert "suppressed (synthetic)" in text
    tables = text.count("| Horizon |") + text.count("| as of |")
    assert text.count(ss.SYNTHETIC_LABEL) == tables == 2
    assert text.index("insufficient data") < text.index("| Horizon |")


def test_small_real_sample_prints_mean_without_interval_and_banner_first() -> None:
    text = "\n".join(ss.render_trend_study(_obs(1, 12), synthetic=False))
    assert not INTERVAL.search(text)
    assert "no interval: n < 30" in text
    assert text.index("insufficient data") < text.index("| Horizon |")


def test_large_real_sample_earns_an_interval_and_no_banner() -> None:
    text = "\n".join(ss.render_trend_study(_obs(4, 30), synthetic=False))
    assert INTERVAL.search(text)
    assert "insufficient data" not in text


def test_committed_notebook_has_no_interval_on_the_synthetic_corpus() -> None:
    nb = json.loads((ROOT / "notebooks" / "signal_study.ipynb").read_text(encoding="utf-8"))
    out = "".join(
        o["data"]["text/markdown"]
        for c in nb["cells"]
        if c["cell_type"] == "code"
        for o in c["outputs"]
    )
    assert "synthetic social data" in out
    assert ss.SYNTHETIC_LABEL in out
    assert not INTERVAL.search(out)
    assert "95% CI" not in out
