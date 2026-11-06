"""Typed theme map (PRD section 4A.4): theme → supply-chain layer → company.

The YAML is the curated half of the method (steps 1, 2 and 5 of ``bottleneck-arbitrage.md``):
which themes have real money behind them, which layers they depend on and which companies sell into
each layer. Two rules keep the file honest:

* ``curated`` is **never stored**. It is derived from ``config/quality_universe.yaml`` at load, so
  the theme map and the good-to-own list cannot disagree about who is on the list.
* every ticker is validated against the SEC company list (the offline fixture copy by default);
  an unknown ticker fails the whole load loudly.

A ``customer`` confirms demand (``customer_confirmation`` in section 4A.7) and is never scored, so
it may not carry the supplier fields ``materiality``, ``pricing_power`` and ``capacity``.
"""

from __future__ import annotations

import json
import operator
from collections.abc import Callable, Collection, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from options_scout.core.models import Materiality

Role = Literal["supplier", "customer"]
PricingPower = Literal["high", "medium", "low"]
Capacity = Literal["constrained", "ample"]
SupplierCount = Literal["few", "several", "many"]
SeriesSource = Literal["fred", "csv"]
# Signals a falsifier may test (section 4A.7); the thesis monitor (step 11.3) evaluates them.
FalsifierSignal = Literal[
    "tightness_z",
    "customer_confirmation",
    "price_trend",
    "price_deceleration",
    "supply_response_z",
    "cross_source_norm",
    "priced_in",
]
FalsifierOp = Literal[">", ">=", "<", "<="]
SUPPLIER_FIELDS: tuple[str, ...] = ("materiality", "pricing_power", "capacity")

_OPS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SpendEvidence(_Strict):
    """Step 1: a link that shows real money flowing into the theme."""

    label: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")


class PriceSeriesRef(_Strict):
    """A price or lead-time series for the layer (FRED id, or a CSV the operator drops in)."""

    source: SeriesSource
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class Falsifier(_Strict):
    """A predicate on a computed signal that, when it holds for ``snapshots`` consecutive daily
    snapshots, marks the layer's thesis as weakening (section 4A.9)."""

    signal: FalsifierSignal
    op: FalsifierOp
    value: float
    snapshots: int = Field(default=1, ge=1)

    def holds(self, observed: float) -> bool:
        """True when ``observed`` satisfies the predicate (the thesis is *contradicted*)."""
        return _OPS[self.op](observed, self.value)

    def describe(self) -> str:
        return f"{self.signal} {self.op} {self.value:g} for {self.snapshots} snapshot(s)"


class ThemeCompany(_Strict):
    """Step 5: one company's exposure to a layer. ``curated`` is set by the loader, not by hand."""

    ticker: str = Field(min_length=1, max_length=10)
    role: Role
    materiality: Materiality | None = None
    pricing_power: PricingPower | None = None
    capacity: Capacity | None = None
    note: str | None = None
    curated: bool = False

    @field_validator("ticker", mode="before")
    @classmethod
    def _upper(cls, v: object) -> str:
        return str(v).strip().upper()

    @model_validator(mode="after")
    def _fields_match_role(self) -> ThemeCompany:
        present = [f for f in SUPPLIER_FIELDS if getattr(self, f) is not None]
        if self.role == "customer" and present:
            raise ValueError(
                f"{self.ticker}: a customer confirms demand and is never scored; remove {present}"
            )
        if self.role == "supplier" and len(present) != len(SUPPLIER_FIELDS):
            missing = [f for f in SUPPLIER_FIELDS if f not in present]
            raise ValueError(f"{self.ticker}: a supplier needs {missing}")
        return self

    @property
    def is_supplier(self) -> bool:
        return self.role == "supplier"


class Layer(_Strict):
    """Step 2 (the tree) and step 3 (how hard it is to add supply)."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    price_series: list[PriceSeriesRef] = Field(default_factory=list)
    supplier_count: SupplierCount
    capacity_lead_years: float = Field(ge=0.0)
    thesis: str = Field(min_length=10)
    falsifiers: list[Falsifier] = Field(default_factory=list)
    companies: list[ThemeCompany] = Field(min_length=1)

    @field_validator("keywords")
    @classmethod
    def _non_empty_keywords(cls, v: list[str]) -> list[str]:
        cleaned = [k.strip() for k in v if k.strip()]
        if not cleaned:
            raise ValueError("a layer needs at least one keyword")
        return cleaned

    @model_validator(mode="after")
    def _companies_consistent(self) -> Layer:
        tickers = [c.ticker for c in self.companies]
        dupes = sorted({t for t in tickers if tickers.count(t) > 1})
        if dupes:
            raise ValueError(f"layer {self.id!r}: duplicate tickers {dupes}")
        if not any(c.is_supplier for c in self.companies):
            raise ValueError(f"layer {self.id!r}: at least one supplier is required")
        series_ids = [f"{s.source}:{s.id}" for s in self.price_series]
        if len(set(series_ids)) != len(series_ids):
            raise ValueError(f"layer {self.id!r}: duplicate price series")
        return self

    @property
    def suppliers(self) -> list[ThemeCompany]:
        return [c for c in self.companies if c.is_supplier]

    @property
    def customers(self) -> list[ThemeCompany]:
        return [c for c in self.companies if not c.is_supplier]

    @property
    def tickers(self) -> list[str]:
        return [c.ticker for c in self.companies]


class Theme(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    spend_evidence: list[SpendEvidence] = Field(min_length=1)
    layers: list[Layer] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_layers(self) -> Theme:
        ids = [layer.id for layer in self.layers]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"theme {self.id!r}: duplicate layer ids {dupes}")
        return self

    def get_layer(self, layer_id: str) -> Layer | None:
        return next((layer for layer in self.layers if layer.id == layer_id), None)


class ThemeMap(_Strict):
    """Everything in ``config/themes.yaml``, validated, with ``curated`` filled in."""

    themes: list[Theme] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_themes(self) -> ThemeMap:
        ids = [t.id for t in self.themes]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate theme ids {dupes}")
        return self

    def get(self, theme_id: str) -> Theme | None:
        return next((t for t in self.themes if t.id == theme_id), None)

    def layers(self) -> Iterator[tuple[Theme, Layer]]:
        for theme in self.themes:
            for layer in theme.layers:
                yield theme, layer

    @property
    def tickers(self) -> list[str]:
        """Every ticker in the map, sorted, once."""
        return sorted({c.ticker for _, layer in self.layers() for c in layer.companies})

    def companies_for(self, ticker: str) -> list[tuple[Theme, Layer, ThemeCompany]]:
        """Every (theme, layer, entry) a ticker appears in; a company in several layers takes the
        maximum company score (section 4A.7)."""
        t = ticker.strip().upper()
        return [
            (theme, layer, c)
            for theme, layer in self.layers()
            for c in layer.companies
            if c.ticker == t
        ]

    def supplier_tickers(self, *, curated_only: bool = False) -> list[str]:
        out = {
            c.ticker
            for _, layer in self.layers()
            for c in layer.suppliers
            if c.curated or not curated_only
        }
        return sorted(out)

    def not_curated(self) -> list[str]:
        """Suppliers shown on the board as context only (not on the good-to-own list)."""
        return sorted(
            {c.ticker for _, layer in self.layers() for c in layer.suppliers if not c.curated}
        )


# ------------------------------------------------------------------------------- loading
def _reject_stored_curated(raw: dict[str, Any]) -> None:
    for theme in raw.get("themes") or []:
        for layer in (theme or {}).get("layers") or []:
            for company in (layer or {}).get("companies") or []:
                if isinstance(company, dict) and "curated" in company:
                    raise ValueError(
                        f"themes.yaml: {company.get('ticker')!r} carries a `curated` key; the flag "
                        "is derived from config/quality_universe.yaml and must not be stored"
                    )


def _mark_curated(raw: dict[str, Any], curated: Collection[str]) -> dict[str, Any]:
    good = {t.strip().upper() for t in curated}
    out: dict[str, Any] = json.loads(json.dumps(raw))  # deep copy of plain YAML data
    for theme in out.get("themes") or []:
        for layer in (theme or {}).get("layers") or []:
            for company in (layer or {}).get("companies") or []:
                if isinstance(company, dict):
                    company["curated"] = str(company.get("ticker", "")).strip().upper() in good
    return out


@lru_cache(maxsize=4)
def _sec_tickers(path: str) -> frozenset[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return frozenset(str(v["ticker"]).upper() for v in data.values())


def sec_ticker_validator(fixtures_dir: Path) -> Callable[[str], bool]:
    """Offline validator over the SEC ``company_tickers.json`` fixture copy."""
    path = str(fixtures_dir / "sec_company_tickers.json")

    def is_valid(ticker: str) -> bool:
        return ticker.strip().upper() in _sec_tickers(path)

    return is_valid


def load_theme_map(
    path: Path,
    *,
    curated: Collection[str],
    is_valid_ticker: Callable[[str], bool],
) -> ThemeMap:
    """Load and validate ``config/themes.yaml``.

    ``curated`` is the good-to-own symbol list; ``is_valid_ticker`` answers against the SEC company
    list. Any ticker it rejects fails the load with every offender named.
    """
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict) or "themes" not in raw:
        raise ValueError(f"{path} must contain a mapping with a `themes` list")
    _reject_stored_curated(raw)
    theme_map = ThemeMap(**_mark_curated(raw, curated))
    unknown = [t for t in theme_map.tickers if not is_valid_ticker(t)]
    if unknown:
        raise ValueError(
            f"themes.yaml: ticker(s) not in the SEC company list: {unknown}; fix the symbol or "
            "refresh tests/fixtures/sec_company_tickers.json"
        )
    return theme_map
