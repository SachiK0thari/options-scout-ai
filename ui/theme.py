"""One colour scheme and one layout for every Plotly chart in the app.

Colour is assigned by the job it does (identity, magnitude, polarity, state), never cycled:

* ``SERIES`` is the fixed categorical order for distinct entities (tickers, sources);
* ``SEQUENTIAL`` is one hue, light to dark, for ordered magnitudes (−10 / −20 / −30 %);
* ``POSITIVE`` / ``NEGATIVE`` are the diverging pair for P&L and z-scores around zero;
* ``GOOD`` / ``WARNING`` / ``CRITICAL`` are status colours, always paired with a text label.

Every chart gets a title, axis labels with units and a one-line caption via :func:`caption`.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
import streamlit as st

SERIES: tuple[str, ...] = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#6250d6",  # violet
    "#e34948",  # red
)
SEQUENTIAL: tuple[str, ...] = ("#86b6ef", "#3987e5", "#1c5cab", "#0d366b")
ACCENT = SERIES[0]
MUTED = "#898781"  # de-emphasis gray for context series
POSITIVE = "#2a78d6"  # diverging pair: blue (gain / above baseline)
NEGATIVE = "#d03b3b"  # red (loss / below baseline)
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
TEXT_IN_FILL = "#ffffff"

CHART_HEIGHT = 360


def series_color(index: int) -> str:
    """Fixed slot per entity; the ninth and later entities share the de-emphasis gray."""
    return SERIES[index] if index < len(SERIES) else MUTED


def color_map(names: list[str]) -> dict[str, str]:
    """Stable entity → colour assignment in first-seen order (never by rank or filter)."""
    return {name: series_color(i) for i, name in enumerate(dict.fromkeys(names))}


def style(
    fig: go.Figure,
    title: str,
    x_label: str,
    y_label: str,
    *,
    height: int = CHART_HEIGHT,
    legend: bool = True,
) -> go.Figure:
    """Recessive chrome: hairline grid, no plot background, legend on top, units in the labels."""
    fig.update_layout(
        title={"text": title, "x": 0.0, "xanchor": "left"},
        height=height,
        margin={"l": 8, "r": 8, "t": 56, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="closest",
        hoverlabel={"namelength": -1},
        showlegend=legend,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "right", "x": 1.0},
        bargap=0.35,
        bargroupgap=0.08,
    )
    axis: dict[str, Any] = {
        "showgrid": True,
        "gridcolor": GRID,
        "gridwidth": 1,
        "zeroline": True,
        "zerolinecolor": AXIS,
        "zerolinewidth": 1,
        "linecolor": AXIS,
        "ticks": "outside",
        "tickcolor": AXIS,
    }
    fig.update_xaxes(title_text=x_label, **axis)
    fig.update_yaxes(title_text=y_label, **axis)
    return fig


def show(fig: go.Figure, caption_text: str) -> None:
    """Render a chart with its caption (what it shows, in one line)."""
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption(caption_text)


def badge(passed: bool) -> str:
    return "✓" if passed else "✗"
