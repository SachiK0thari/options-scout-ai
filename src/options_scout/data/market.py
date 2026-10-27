"""Market data layer: typed tool functions over yfinance (live) or JSON fixtures (offline).

Everything is cached (SQLite, TTLs from config) and every live call is retried with
exponential backoff. yfinance is an unofficial, delayed scraper; treat it accordingly.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from options_scout.config import AppConfig, DataMode
from options_scout.core import volatility
from options_scout.core.models import OptionChain, OptionQuote, SpotQuote, TickerSnapshot
from options_scout.data.cache import MemoryCache, SQLiteCache
from options_scout.data.fixtures import FixtureStore, IndexFixture, TickerFixture
from options_scout.jobs.snapshot_iv import IVSnapshotStore

log = logging.getLogger(__name__)

RISK_FREE_FALLBACK = 0.04
MIN_IV_HISTORY = 30


class Cache(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...


class MarketSource(Protocol):
    """Raw source. Live = yfinance, fixture = JSON. Returns plain models, no caching."""

    name: str

    def get_spot(self, ticker: str) -> SpotQuote: ...
    def list_expiries(self, ticker: str) -> list[date]: ...
    def get_option_chain(self, ticker: str, expiry: date) -> OptionChain: ...
    def get_earnings_date(self, ticker: str) -> date | None: ...
    def get_close_history(self, ticker: str, days: int) -> list[float]: ...
    def get_dividend_yield(self, ticker: str) -> float: ...
    def get_index_history(self, symbol: str, days: int) -> list[float]: ...
    def get_index_last(self, symbol: str) -> float: ...
    def now(self) -> datetime: ...


class MarketDataError(RuntimeError):
    pass


# --------------------------------------------------------------------------------- fixture
class FixtureSource:
    name = "fixture"

    def __init__(self, store: FixtureStore) -> None:
        self.store = store
        self._cache: dict[str, Any] = {}

    def _fx(self, ticker: str) -> TickerFixture:
        t = ticker.upper()
        if t not in self._cache:
            self._cache[t] = self.store.load(t)
        fx: TickerFixture = self._cache[t]
        return fx

    def _idx(self) -> IndexFixture:
        if "__indices__" not in self._cache:
            self._cache["__indices__"] = self.store.load_indices()
        idx: IndexFixture = self._cache["__indices__"]
        return idx

    def available(self) -> list[str]:
        return self.store.available()

    def get_spot(self, ticker: str) -> SpotQuote:
        return self._fx(ticker).snapshot.spot

    def list_expiries(self, ticker: str) -> list[date]:
        return self._fx(ticker).snapshot.expiries()

    def get_option_chain(self, ticker: str, expiry: date) -> OptionChain:
        for ch in self._fx(ticker).snapshot.chains:
            if ch.expiry == expiry:
                return ch
        raise MarketDataError(f"{ticker}: no fixture chain for {expiry}")

    def get_earnings_date(self, ticker: str) -> date | None:
        return self._fx(ticker).snapshot.earnings_date

    def get_close_history(self, ticker: str, days: int) -> list[float]:
        hist: list[float] = self._fx(ticker).close_history
        return hist[-days:]

    def get_dividend_yield(self, ticker: str) -> float:
        return float(self._fx(ticker).snapshot.dividend_yield)

    def get_index_history(self, symbol: str, days: int) -> list[float]:
        if symbol.upper() != "^VIX":
            raise MarketDataError(f"fixture has no index history for {symbol}")
        return self._idx().vix_history[-days:]

    def get_index_last(self, symbol: str) -> float:
        idx = self._idx()
        if symbol.upper() == "^VIX":
            return idx.vix_now
        if symbol.upper() == "^IRX":
            return idx.irx_now
        raise MarketDataError(f"fixture has no index {symbol}")

    def now(self) -> datetime:
        """Fixture 'now' is the recording time, so DTE windows line up with recorded expiries."""
        try:
            return self._idx().as_of
        except FileNotFoundError:
            avail = self.available()
            if not avail:
                return datetime.now(tz=UTC)
            return self._fx(avail[0]).snapshot.as_of


# ------------------------------------------------------------------------------------ live
_RETRY = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type(Exception),
)


class YFinanceSource:
    name = "yfinance"

    def __init__(self) -> None:
        import yfinance as yf  # imported lazily so fixture mode never needs it at import time

        self._yf = yf
        warnings.filterwarnings("ignore", module="yfinance")

    def _ticker(self, ticker: str) -> Any:
        return self._yf.Ticker(ticker)

    @_RETRY
    def get_spot(self, ticker: str) -> SpotQuote:
        t = self._ticker(ticker)
        fi = t.fast_info
        price = float(fi["lastPrice"])
        avg_vol = float(fi.get("threeMonthAverageVolume") or fi.get("tenDayAverageVolume") or 0)
        sector = "Unknown"
        try:
            info = t.info or {}
            sector = str(
                info.get("sector") or ("ETF" if info.get("quoteType") == "ETF" else "Unknown")
            )
        except Exception:  # yfinance .info is flaky; sector is cosmetic
            pass
        return SpotQuote(
            ticker=ticker.upper(),
            price=price,
            avg_volume=avg_vol,
            as_of=datetime.now(tz=UTC),
            sector=sector,
        )

    @_RETRY
    def list_expiries(self, ticker: str) -> list[date]:
        return [date.fromisoformat(e) for e in self._ticker(ticker).options]

    @_RETRY
    def get_option_chain(self, ticker: str, expiry: date) -> OptionChain:
        ch = self._ticker(ticker).option_chain(expiry.isoformat())

        def rows(frame: Any, kind: str) -> list[OptionQuote]:
            out: list[OptionQuote] = []
            for rec in frame.to_dict(orient="records"):
                try:
                    out.append(
                        OptionQuote(
                            contract_symbol=str(rec["contractSymbol"]),
                            kind="call" if kind == "call" else "put",
                            strike=float(rec["strike"]),
                            expiry=expiry,
                            bid=_f(rec.get("bid")),
                            ask=_f(rec.get("ask")),
                            last=_f(rec.get("lastPrice")),
                            volume=_i(rec.get("volume")),
                            open_interest=_i(rec.get("openInterest")),
                            iv=_f(rec.get("impliedVolatility")),
                        )
                    )
                except (ValueError, TypeError) as exc:  # bad row: skip, don't fail the chain
                    log.debug("skipping bad row %s: %s", rec.get("contractSymbol"), exc)
            return out

        return OptionChain(
            ticker=ticker.upper(),
            expiry=expiry,
            as_of=datetime.now(tz=UTC),
            calls=rows(ch.calls, "call"),
            puts=rows(ch.puts, "put"),
        )

    @_RETRY
    def get_earnings_date(self, ticker: str) -> date | None:
        cal = self._ticker(ticker).calendar or {}
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if not dates:
            return None
        first = dates[0] if isinstance(dates, list | tuple) else dates
        if isinstance(first, datetime):
            return first.date()
        if isinstance(first, date):
            return first
        return None

    @_RETRY
    def get_close_history(self, ticker: str, days: int) -> list[float]:
        period = "3mo" if days <= 60 else ("1y" if days <= 252 else "2y")
        hist = self._ticker(ticker).history(period=period, auto_adjust=True)
        closes = [float(x) for x in hist["Close"].tolist() if x == x]  # drop NaN
        return closes[-days:]

    @_RETRY
    def get_dividend_yield(self, ticker: str) -> float:
        try:
            info = self._ticker(ticker).info or {}
        except Exception:
            return 0.0
        # yfinance 1.x: `dividendYield` is in percent (0.31 == 0.31%); trailing is a fraction.
        if info.get("dividendYield") is not None:
            return float(info["dividendYield"]) / 100.0
        return float(info.get("trailingAnnualDividendYield") or 0.0)

    @_RETRY
    def get_index_history(self, symbol: str, days: int) -> list[float]:
        hist = self._ticker(symbol).history(period="1y" if days <= 252 else "2y")
        closes = [float(x) for x in hist["Close"].tolist() if x == x]
        return closes[-days:]

    @_RETRY
    def get_index_last(self, symbol: str) -> float:
        return float(self._ticker(symbol).fast_info["lastPrice"])

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def _f(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v != v else v  # NaN → 0


def _i(x: Any) -> int:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0
    return 0 if v != v else int(v)


# --------------------------------------------------------------------------------- facade
class MarketData:
    """Cached, typed facade used by tools and agent nodes."""

    def __init__(
        self,
        source: MarketSource,
        cache: Cache,
        ttl: dict[str, int],
        iv_store: IVSnapshotStore | None = None,
        *,
        near_dte: tuple[int, int] = (20, 60),
        far_dte_min: int = 330,
    ) -> None:
        self.source = source
        self.cache = cache
        self.ttl = ttl
        self.iv_store = iv_store
        self.near_dte = near_dte
        self.far_dte_min = far_dte_min
        self.status: dict[str, str] = {}

    @classmethod
    def from_config(cls, cfg: AppConfig, mode: DataMode | None = None) -> MarketData:
        mode = mode or cfg.settings.data_mode
        ttl = cfg.settings.cache_ttl_seconds.model_dump()
        iv_store = IVSnapshotStore(cfg.paths.iv_snapshot_db)
        near = (cfg.rules.csp.dte_min - 10, cfg.rules.csp.dte_max + 15)
        far = cfg.rules.leaps.dte_min - 35
        if mode == "fixture":
            return cls(
                FixtureSource(FixtureStore(cfg.paths.fixtures_dir)),
                MemoryCache(),
                ttl,
                iv_store,
                near_dte=near,
                far_dte_min=far,
            )
        return cls(
            YFinanceSource(),
            SQLiteCache(cfg.paths.cache_db),
            ttl,
            iv_store,
            near_dte=near,
            far_dte_min=far,
        )

    # -- cached primitives -----------------------------------------------------------
    def _cached(self, key: str, ttl_key: str, fetch: Any, parse: Any) -> Any:
        hit = self.cache.get(key)
        if hit is not None:
            return parse(hit)
        value = fetch()
        self.cache.set(key, _dump(value), self.ttl[ttl_key])
        return value

    def now(self) -> datetime:
        return self.source.now()

    def today(self) -> date:
        return self.now().date()

    def get_spot(self, ticker: str) -> SpotQuote:
        return self._cached(  # type: ignore[no-any-return]
            f"spot:{ticker}",
            "spot",
            lambda: self.source.get_spot(ticker),
            SpotQuote.model_validate,
        )

    def list_expiries(self, ticker: str) -> list[date]:
        return self._cached(  # type: ignore[no-any-return]
            f"expiries:{ticker}",
            "option_chain",
            lambda: self.source.list_expiries(ticker),
            lambda v: [date.fromisoformat(x) for x in v],
        )

    def get_option_chain(self, ticker: str, expiry: date) -> OptionChain:
        return self._cached(  # type: ignore[no-any-return]
            f"chain:{ticker}:{expiry.isoformat()}",
            "option_chain",
            lambda: self.source.get_option_chain(ticker, expiry),
            OptionChain.model_validate,
        )

    def get_earnings_date(self, ticker: str) -> date | None:
        hit = self.cache.get(f"earnings:{ticker}")
        if hit is not None:
            return date.fromisoformat(hit) if hit != "none" else None
        value = self.source.get_earnings_date(ticker)
        self.cache.set(
            f"earnings:{ticker}", value.isoformat() if value else "none", self.ttl["earnings"]
        )
        return value

    def get_close_history(self, ticker: str, days: int = 90) -> list[float]:
        return self._cached(  # type: ignore[no-any-return]
            f"closes:{ticker}:{days}",
            "history",
            lambda: self.source.get_close_history(ticker, days),
            lambda v: [float(x) for x in v],
        )

    def get_hist_vol(self, ticker: str, window: int = 30) -> float | None:
        closes = self.get_close_history(ticker, window + 10)
        if len(closes) < window + 1:
            return None
        return volatility.hist_vol(closes, window)

    def get_dividend_yield(self, ticker: str) -> float:
        return self._cached(  # type: ignore[no-any-return]
            f"divy:{ticker}",
            "dividends",
            lambda: self.source.get_dividend_yield(ticker),
            float,
        )

    def get_vix_percentile(self, lookback_days: int = 252) -> tuple[float, float]:
        """Returns (vix_now, percentile 0-100 within the lookback window)."""
        history = self._cached(
            f"index_hist:^VIX:{lookback_days}",
            "history",
            lambda: self.source.get_index_history("^VIX", lookback_days),
            lambda v: [float(x) for x in v],
        )
        vix_now = self._cached(
            "index_last:^VIX", "spot", lambda: self.source.get_index_last("^VIX"), float
        )
        return float(vix_now), volatility.percentile_rank(float(vix_now), history)

    def get_risk_free_rate(self) -> float:
        """13-week T-bill (^IRX quotes in percent) as a fraction; falls back to a constant."""
        try:
            irx = self._cached(
                "index_last:^IRX", "spot", lambda: self.source.get_index_last("^IRX"), float
            )
            rate = float(irx) / 100.0
            if 0.0 <= rate <= 0.20:
                return rate
        except Exception as exc:  # degrade gracefully, record why
            self.status["^IRX"] = f"error: {exc}"
        return RISK_FREE_FALLBACK

    # -- snapshot ----------------------------------------------------------------------
    def relevant_expiries(self, ticker: str, today: date | None = None) -> list[date]:
        today = today or self.today()
        lo, hi = self.near_dte
        out: list[date] = []
        for e in self.list_expiries(ticker):
            dte = (e - today).days
            if lo <= dte <= hi or dte >= self.far_dte_min:
                out.append(e)
        return out

    def build_snapshot(self, ticker: str, expiries: Sequence[date] | None = None) -> TickerSnapshot:
        ticker = ticker.upper()
        errors: list[str] = []
        now = self.now()
        spot = self.get_spot(ticker)
        chains: list[OptionChain] = []
        for e in expiries if expiries is not None else self.relevant_expiries(ticker, now.date()):
            try:
                chains.append(self.get_option_chain(ticker, e))
            except Exception as exc:
                errors.append(f"chain {e}: {exc}")
        earnings: date | None = None
        try:
            earnings = self.get_earnings_date(ticker)
        except Exception as exc:
            errors.append(f"earnings: {exc}")
        hv30: float | None = None
        try:
            hv30 = self.get_hist_vol(ticker, 30)
        except Exception as exc:
            errors.append(f"hv30: {exc}")
        divy = 0.0
        try:
            divy = self.get_dividend_yield(ticker)
        except Exception as exc:
            errors.append(f"dividend: {exc}")

        atm_iv = atm_implied_vol(chains, spot.price, now.date(), self.near_dte)
        iv_rank, iv_source = self._iv_rank(ticker, atm_iv, hv30)
        self.status[ticker] = "ok" if not errors else f"partial: {len(errors)} errors"
        return TickerSnapshot(
            ticker=ticker,
            as_of=now,
            spot=spot,
            chains=chains,
            earnings_date=earnings,
            hv30=hv30,
            dividend_yield=divy,
            atm_iv=atm_iv,
            iv_rank=iv_rank,
            iv_rank_source=iv_source,
            source_errors=errors,
        )

    def _iv_rank(
        self, ticker: str, atm_iv: float | None, hv30: float | None
    ) -> tuple[float | None, str]:
        if atm_iv is None:
            return None, "none"
        if self.iv_store is not None and self.iv_store.has_enough_history(ticker):
            rank = volatility.iv_rank(atm_iv, self.iv_store.history(ticker))
            if rank is not None:
                return rank, "history"
        if hv30:
            proxy = volatility.hv_proxy_iv_rank(atm_iv, hv30)
            if proxy is not None:
                return proxy, "hv_proxy"
        return None, "none"


def atm_implied_vol(
    chains: Sequence[OptionChain], spot: float, today: date, near_dte: tuple[int, int]
) -> float | None:
    """Average IV of the ATM call and put on the nearest chain inside the near-DTE window."""
    near = [c for c in chains if near_dte[0] <= (c.expiry - today).days <= near_dte[1]]
    pool = near or list(chains)
    if not pool:
        return None
    target = min(pool, key=lambda c: abs((c.expiry - today).days - 37))
    ivs: list[float] = []
    for side in (target.calls, target.puts):
        quotes = [q for q in side if q.iv > 0]
        if quotes:
            ivs.append(min(quotes, key=lambda q: abs(q.strike - spot)).iv)
    return sum(ivs) / len(ivs) if ivs else None


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def days_between(a: date, b: date) -> int:
    return (b - a).days


def default_cache_path(cfg: AppConfig) -> Path:
    return cfg.paths.cache_db


__all__ = [
    "FixtureSource",
    "MarketData",
    "MarketDataError",
    "MarketSource",
    "YFinanceSource",
    "atm_implied_vol",
    "timedelta",
]
