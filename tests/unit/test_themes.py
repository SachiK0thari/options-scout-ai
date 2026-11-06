"""Theme map loader (PRD section 4A.4): loads, SEC validation, derived `curated`, role rules."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from options_scout.bottleneck.themes import (
    Falsifier,
    Layer,
    ThemeCompany,
    ThemeMap,
    load_theme_map,
    sec_ticker_validator,
)
from options_scout.config import AppConfig


def _raw(config: AppConfig) -> dict[str, object]:
    with (config.root / "config" / "themes.yaml").open(encoding="utf-8") as fh:
        data: dict[str, object] = yaml.safe_load(fh)
    return data


def _load(tmp_path: Path, raw: dict[str, object], config: AppConfig) -> ThemeMap:
    path = tmp_path / "themes.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_theme_map(
        path,
        curated=config.quality.symbols,
        is_valid_ticker=sec_ticker_validator(config.paths.fixtures_dir),
    )


# ---------------------------------------------------------------------------- the real file
def test_committed_theme_map_loads_with_two_themes(config: AppConfig) -> None:
    tm = config.themes
    assert [t.id for t in tm.themes] == ["ai_datacenter", "electrification"]
    ai = tm.get("ai_datacenter")
    assert ai is not None
    assert {layer.id for layer in ai.layers} >= {
        "power",
        "memory",
        "cooling",
        "networking",
        "materials",
    }
    elec = tm.get("electrification")
    assert elec is not None and {layer.id for layer in elec.layers} >= {"grid", "battery"}
    for _, layer in tm.layers():
        assert layer.suppliers, layer.id
        assert layer.keywords and layer.thesis
        assert all(s.source in {"fred", "csv"} for s in layer.price_series)
        for f in layer.falsifiers:
            assert isinstance(f, Falsifier) and f.snapshots >= 1
    assert "GEV" in tm.tickers and "HON" in tm.tickers


def test_curated_is_derived_from_quality_universe(config: AppConfig) -> None:
    tm = config.themes
    good = set(config.quality.symbols)
    for _, layer in tm.layers():
        for c in layer.companies:
            assert c.curated == (c.ticker in good), c.ticker
    # the honest-constraint comment in the YAML is true: pure plays are not on the list
    assert {"GEV", "MU", "VRT", "ANET", "ETN"} <= set(tm.not_curated())
    assert "HON" in tm.supplier_tickers(curated_only=True)
    assert "HON" not in tm.not_curated()


def test_companies_for_ticker_spans_layers(config: AppConfig) -> None:
    hits = config.themes.companies_for("hon")
    assert len(hits) >= 2  # Honeywell sells into several layers; the score takes the maximum
    assert all(c.ticker == "HON" and c.is_supplier for _, _, c in hits)
    assert config.themes.companies_for("ZZZZ") == []
    assert {c.role for _, _, c in config.themes.companies_for("MSFT")} == {"customer"}


def test_every_ticker_is_in_the_sec_fixture(config: AppConfig) -> None:
    valid = sec_ticker_validator(config.paths.fixtures_dir)
    assert all(valid(t) for t in config.themes.tickers)
    assert not valid("NOTATICKER")


# ------------------------------------------------------------------------------ validation
def test_unknown_ticker_fails_loudly(tmp_path: Path, config: AppConfig) -> None:
    raw = _raw(config)
    themes = raw["themes"]
    assert isinstance(themes, list)
    themes[0]["layers"][0]["companies"].append(
        {
            "ticker": "ZZZQ",
            "role": "supplier",
            "materiality": "high",
            "pricing_power": "high",
            "capacity": "ample",
        }
    )
    with pytest.raises(ValueError, match=r"not in the SEC company list: \['ZZZQ'\]"):
        _load(tmp_path, raw, config)


def test_stored_curated_flag_is_rejected(tmp_path: Path, config: AppConfig) -> None:
    raw = _raw(config)
    themes = raw["themes"]
    assert isinstance(themes, list)
    themes[0]["layers"][0]["companies"][0]["curated"] = True
    with pytest.raises(ValueError, match="curated"):
        _load(tmp_path, raw, config)


def test_customer_may_not_carry_supplier_fields() -> None:
    with pytest.raises(ValueError, match="never scored"):
        ThemeCompany(ticker="MSFT", role="customer", materiality="high")
    with pytest.raises(ValueError, match="a supplier needs"):
        ThemeCompany(ticker="HON", role="supplier", materiality="high")
    ok = ThemeCompany(ticker="msft", role="customer")
    assert ok.ticker == "MSFT" and not ok.is_supplier and ok.curated is False


def _layer(**overrides: object) -> Layer:
    base: dict[str, object] = {
        "id": "power",
        "name": "Power",
        "keywords": ["power constraint"],
        "supplier_count": "few",
        "capacity_lead_years": 3,
        "thesis": "Demand outruns supply for a few years.",
        "companies": [
            {
                "ticker": "HON",
                "role": "supplier",
                "materiality": "medium",
                "pricing_power": "high",
                "capacity": "constrained",
            },
            {"ticker": "MSFT", "role": "customer"},
        ],
    }
    base.update(overrides)
    return Layer(**base)  # type: ignore[arg-type]


def test_layer_rules() -> None:
    layer = _layer()
    assert [c.ticker for c in layer.suppliers] == ["HON"]
    assert [c.ticker for c in layer.customers] == ["MSFT"]
    with pytest.raises(ValueError, match="at least one supplier"):
        _layer(companies=[{"ticker": "MSFT", "role": "customer"}])
    with pytest.raises(ValueError, match="duplicate tickers"):
        _layer(
            companies=[
                {
                    "ticker": "HON",
                    "role": "supplier",
                    "materiality": "low",
                    "pricing_power": "low",
                    "capacity": "ample",
                },
                {"ticker": "HON", "role": "customer"},
            ]
        )
    with pytest.raises(ValueError):
        _layer(id="Power Layer")  # ids are snake_case
    with pytest.raises(ValueError):
        _layer(falsifiers=[{"signal": "made_up", "op": ">", "value": 1}])


def test_falsifier_predicate() -> None:
    f = Falsifier(signal="price_deceleration", op=">", value=0.5, snapshots=2)
    assert f.holds(0.6) and not f.holds(0.5)
    assert Falsifier(signal="tightness_z", op="<=", value=-1.0).holds(-1.0)
    assert f.describe() == "price_deceleration > 0.5 for 2 snapshot(s)"


def test_theme_map_rejects_duplicate_ids(tmp_path: Path, config: AppConfig) -> None:
    raw = _raw(config)
    themes = raw["themes"]
    assert isinstance(themes, list)
    themes.append(themes[0])
    with pytest.raises(ValueError, match="duplicate theme ids"):
        _load(tmp_path, raw, config)
