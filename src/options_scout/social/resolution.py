"""Entity → ticker resolution (4.4): brand map → fuzzy SEC → optional LLM, all SEC-validated."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

from options_scout.core.models import Materiality, TickerResolution
from options_scout.data.cache import SQLiteCache
from options_scout.social.adapters.sec import SECAdapter

log = logging.getLogger(__name__)

_SUFFIXES = re.compile(
    r"\b(inc|corp|corporation|co|company|ltd|plc|holdings?|group|the|llc|sa|nv|ag|lp|l\.p\.)\b\.?",
    re.IGNORECASE,
)
FUZZY_MIN_SCORE = 92  # conservative: a wrong ticker is worse than a miss


@dataclass(frozen=True)
class Brand:
    brand: str
    aliases: tuple[str, ...]
    company: str
    ticker: str | None
    materiality: Materiality
    sector: str
    type: str
    wikipedia: str | None

    @property
    def names(self) -> tuple[str, ...]:
        return (self.brand, *self.aliases)


class BrandMap:
    def __init__(self, brands: list[Brand]) -> None:
        self.brands = brands
        self._index: dict[str, Brand] = {}
        for b in brands:
            for n in b.names:
                self._index.setdefault(_norm(n), b)

    @classmethod
    def load(cls, path: Path) -> BrandMap:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        brands: list[Brand] = []
        for item in raw.get("brands", []):
            brands.append(
                Brand(
                    brand=str(item["brand"]),
                    aliases=tuple(str(a) for a in item.get("aliases", []) or []),
                    company=str(item.get("company", "")),
                    ticker=(str(item["ticker"]).upper() if item.get("ticker") else None),
                    materiality=item.get("materiality", "medium"),
                    sector=str(item.get("sector", "Unknown")),
                    type=str(item.get("type", "brand")),
                    wikipedia=(str(item["wikipedia"]) if item.get("wikipedia") else None),
                )
            )
        return cls(brands)

    def lookup(self, name: str) -> Brand | None:
        """Exact alias match first; otherwise the longest alias contained in the name as whole
        words ("lulu leggings" → Lululemon, "Teva sandals" → Teva). Aliases shorter than 3 chars
        never match by containment."""
        hit = self._index.get(_norm(name))
        if hit is not None:
            return hit
        q = f" {_norm(name)} "
        best: tuple[int, Brand] | None = None
        for alias, brand in self._index.items():
            if len(alias) < 3:
                continue
            if f" {alias} " in q and (best is None or len(alias) > best[0]):
                best = (len(alias), brand)
        return best[1] if best else None

    def by_brand(self, brand: str) -> Brand | None:
        return next((b for b in self.brands if b.brand == brand), None)

    def alias_patterns(self) -> list[tuple[re.Pattern[str], Brand]]:
        """Compiled word-boundary patterns for every alias, longest first (rule-based extractor)."""
        pairs: list[tuple[str, Brand]] = [
            (n, b) for b in self.brands for n in b.names if len(n) >= 3
        ]
        pairs.sort(key=lambda x: -len(x[0]))
        return [
            (re.compile(rf"(?<![\w$]){re.escape(n)}(?:'s|s)?(?![\w])", re.IGNORECASE), b)
            for n, b in pairs
        ]


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_company(s: str) -> str:
    return _norm(_SUFFIXES.sub(" ", s))


class Resolver:
    """brand map → fuzzy SEC match → LLM proposal (validated) → private/unresolved."""

    def __init__(
        self,
        brand_map: BrandMap,
        sec: SECAdapter,
        cache: SQLiteCache | None = None,
        llm_propose: Callable[[str], str | None] | None = None,
    ) -> None:
        self.brand_map = brand_map
        self.sec = sec
        self.cache = cache
        self.llm_propose = llm_propose
        self._sec_names: dict[str, str] | None = None  # normalised company name → ticker
        self.hallucinated_rejections = 0

    def _sec_index(self) -> dict[str, str]:
        if self._sec_names is None:
            self._sec_names = {}
            for t, c in self.sec.companies().items():
                self._sec_names.setdefault(_norm_company(c.title), t)
        return self._sec_names

    def resolve(self, entity: str) -> TickerResolution:
        key = f"resolve:{_norm(entity)}"
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return TickerResolution.model_validate(hit)
        res = self._resolve_uncached(entity)
        if self.cache is not None:
            self.cache.set(key, res.model_dump(mode="json"), ttl_seconds=30 * 86400)
        return res

    def _resolve_uncached(self, entity: str) -> TickerResolution:
        # 1. curated brand map
        b = self.brand_map.lookup(entity)
        if b is not None:
            if b.ticker and self.sec.is_valid_ticker(b.ticker):
                return TickerResolution(
                    entity=entity,
                    company_name=self.sec.name_of(b.ticker) or b.company,
                    ticker=b.ticker,
                    investable=True,
                    method="brand_map",
                    confidence=0.98,
                    materiality=b.materiality,
                    sector=b.sector,
                )
            return TickerResolution(
                entity=entity,
                company_name=b.company or None,
                ticker=None,
                investable=False,
                method="private",
                confidence=0.95,
                materiality=b.materiality,
                sector=b.sector,
            )
        # 2. fuzzy match against SEC company names
        index = self._sec_index()
        q = _norm_company(entity)
        if q:
            match = process.extractOne(
                q, list(index.keys()), scorer=fuzz.WRatio, score_cutoff=FUZZY_MIN_SCORE
            )
            if match is not None:
                name, score, _ = match
                ticker = index[name]
                return TickerResolution(
                    entity=entity,
                    company_name=self.sec.name_of(ticker),
                    ticker=ticker,
                    investable=True,
                    method="fuzzy_sec",
                    confidence=float(score) / 100.0,
                    materiality="medium",
                    sector=None,
                )
        # 3. LLM proposal, must validate against SEC or be discarded
        if self.llm_propose is not None:
            proposed = self.llm_propose(entity)
            if proposed:
                t = proposed.strip().upper()
                if self.sec.is_valid_ticker(t):
                    return TickerResolution(
                        entity=entity,
                        company_name=self.sec.name_of(t),
                        ticker=t,
                        investable=True,
                        method="llm_validated",
                        confidence=0.7,
                        materiality="low",
                        sector=None,
                    )
                self.hallucinated_rejections += 1
                log.info("discarded unvalidated ticker %r for %r", proposed, entity)
        return TickerResolution(
            entity=entity,
            company_name=None,
            ticker=None,
            investable=False,
            method="unresolved",
            confidence=0.0,
        )
