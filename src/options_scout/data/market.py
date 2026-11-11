"""Market data layer: typed tool functions over MarketData.app / Tradier (live) or JSON fixtures.

Everything is cached (SQLite, TTLs from config) and every live HTTP call is retried with
exponential backoff. Live providers need a user-supplied API token; fixture mode needs nothing.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from options_scout.config import AppConfig, DataMode, MarketProviderName
from options_scout.core import pricing, volatility
from options_scout.core.models import OptionChain, OptionQuote, SpotQuote, TickerSnapshot
from options_scout.data.cache import MemoryCache, SQLiteCache
from options_scout.data.fixtures import FixtureStore, IndexFixture, TickerFixture
from options_scout.jobs.snapshot_iv import IVSnapshotStore

log = logging.getLogger(__name__)

_NEW_YORK = ZoneInfo("America/New_York")

FRED_VIX_SERIES = "VIXCLS"
# FRED's suggested citation for VIXCLS ("Copyrighted: Citation Required") and the notice the FRED
# API terms require (https://fred.stlouisfed.org/docs/api/terms_of_use.html), checked 2026-11-11
FRED_VIX_CITATION = (
    "Chicago Board Options Exchange, CBOE Volatility Index: VIX [VIXCLS], retrieved from FRED, "
    "Federal Reserve Bank of St. Louis; https://fred.stlouisfed.org/series/VIXCLS"
)
FRED_NOTICE = (
    "This product uses the FRED® API but is not endorsed or certified by the Federal Reserve "
    "Bank of St. Louis (terms: https://fred.stlouisfed.org/docs/api/terms_of_use.html)."
)


class FredVix:
    """VIX daily closes from FRED (VIXCLS) for providers without index data (W27 follow-up).

    Values are kept in memory for the day only, never in the SQLite cache. Needs the free
    ``FRED_API_KEY``; errors carry the status code and host, never the key (the bottleneck
    engine's adapter does the request)."""

    LOOKBACK_CALENDAR_DAYS = 400  # a 252-session window with weekends and holidays

    def __init__(self, fetch: Any) -> None:
        self._fetch = fetch  # (series_id, start, end) -> list[SeriesPoint]
        self._memo: dict[date, list[tuple[date, float]]] = {}

    @classmethod
    def from_env(cls) -> FredVix | None:
        from options_scout.bottleneck.adapters.fred import FredSeriesAdapter
        from options_scout.config import FredSourceConfig

        cfg = FredSourceConfig()
        if not os.environ.get(cfg.api_key_env, "").strip():
            return None
        adapter = FredSeriesAdapter("live", cfg, cache=None)

        def fetch(series_id: str, start: date, end: date) -> list[Any]:
            points = adapter.fetch(series_id, start, end)
            if not points and adapter.status().errors:
                raise MarketDataError(f"FRED {series_id}: {adapter.status().errors[-1]}")
            return points

        return cls(fetch)

    def closes(self, today: date) -> list[tuple[date, float]]:
        if today not in self._memo:
            start = today - timedelta(days=self.LOOKBACK_CALENDAR_DAYS)
            points = self._fetch(FRED_VIX_SERIES, start, today)
            self._memo = {today: [(p.day, float(p.value)) for p in points if p.value > 0]}
        return self._memo[today]


RISK_FREE_FALLBACK = 0.04
MIN_IV_HISTORY = 30


class Cache(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...


class MarketSource(Protocol):
    """Raw source. Live = MarketData.app / Tradier, fixture = JSON. Plain models, no caching."""

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


class AuthenticationError(MarketDataError):
    """The provider rejected the key (401): no fallback request can succeed either."""


class QuotaExceededError(MarketDataError):
    """The provider's credit or rate quota is spent, or would be by the next call (W27).

    Not a fact about the ticker: the agent reports it as ``quota`` and never runs the quality
    gate on what was fetched, so a spent plan cannot read as "implied volatility unavailable"."""


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
# Transport errors and 5xx only: a 401/402/429 will not fix itself, so it is raised at once.
_RETRY_HTTP = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type(httpx.HTTPError),
)


class MarketDataAppSource:
    """Keyed provider: MarketData.app REST API v1 (https://api.marketdata.app/v1/).

    One token gives quotes, daily candles, option expirations, option chains with IV and
    Greeks, upcoming earnings dates and index series (VIX etc.).

    **Chains (W27).** With ``chain_feed="historical"`` (the default) a ticker's whole chain, every
    expiry and strike, comes from one request for the previous session's close
    (``/options/chain/{t}/?date=…&expiration=all``), billed at about one credit per 1,000
    contracts: SBUX's 1,074 contracts cost 2 credits on 2026-11-10, against 383 for the same
    chain without ``date``. The plans this app targets serve delayed data, a session behind, so
    nothing fresher is lost. ``chain_feed="live"`` asks for the current chain per expiry, billed
    per contract, trimmed by ``strike_limit`` (0 = full chain).

    **Budget.** Every response's ``X-Api-Ratelimit-Remaining`` is recorded;
    :meth:`ensure_budget` raises :class:`QuotaExceededError` before a ticker is fetched when
    fewer credits are left than it needs, and a 429 is a :class:`QuotaExceededError` too.

    **Candles.** One year of adjusted daily candles and one year of split-only candles are
    fetched once per ticker and session and sliced for the average volume, the close history
    and the dividend estimate (two requests where there were five).

    What MarketData.app does not have:

    * dividends: the yield is derived from the gap between the dividend-adjusted and the
      split-only daily candle series over the last year (raises when that fails, so the
      facade marks the yield unknown rather than assuming none, W5);
    * ^IRX (13-week T-bill): :meth:`get_index_last` raises, and the facade falls back to
      :data:`RISK_FREE_FALLBACK`;
    * sector: quotes carry none; the curated universe supplies it.

    Responses are columnar (every field is a parallel list); ``s`` is ``ok``, ``no_data`` or
    ``error``. HTTP 203 is a cache hit and means success; 204/404 mean no data. 4xx errors are
    not retried (a bad token or an exhausted plan will not fix itself); transport errors and 5xx
    are. The token is only ever sent as a bearer header; it is never logged, cached or echoed.
    """

    name = "marketdata"
    BASE_URL = "https://api.marketdata.app/v1"
    _INDEX_SYMBOLS = {"^VIX": "VIX", "^SPX": "SPX", "^NDX": "NDX", "^RUT": "RUT", "^DJI": "DJI"}
    AVG_VOLUME_DAYS = 63  # ~3 months of sessions, like Yahoo's threeMonthAverageVolume
    DIVIDEND_LOOKBACK_DAYS = 252
    EARNINGS_HORIZON_DAYS = 180

    HISTORY_DAYS = 252  # the one-year candle series every price lookup is sliced from
    SESSION_LOOKBACK = 6  # weekdays tried back from yesterday for the last session with a chain

    def __init__(
        self,
        api_key: str,
        *,
        strike_limit: int = 0,
        chain_feed: str = "historical",
        http_client: httpx.Client | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise MarketDataError("MarketData.app API token is empty")
        if chain_feed not in ("historical", "live"):
            raise MarketDataError(f"unknown MarketData.app chain feed {chain_feed!r}")
        self.strike_limit = max(0, int(strike_limit))
        self.chain_feed = chain_feed
        self.credits_remaining: int | None = None  # from the last response's headers
        self.credits_used = 0  # summed X-Api-Ratelimit-Consumed over this source's life
        self.requests = 0
        # per-session memos: (ticker, day) -> whole-chain body / candle series
        self._chains: dict[tuple[str, date], tuple[date, dict[str, Any]]] = {}
        self._series: dict[tuple[str, bool, date], dict[str, Any]] = {}
        self._client = http_client or httpx.Client(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=20.0,
        )

    def __repr__(self) -> str:  # never leak the token
        return (
            f"MarketDataAppSource(chain_feed={self.chain_feed}, strike_limit={self.strike_limit})"
        )

    # -- transport ----------------------------------------------------------------------
    @_RETRY_HTTP
    def _fetch(self, path: str, params: dict[str, Any]) -> httpx.Response:
        resp = self._client.get(path, params=params)
        if resp.status_code >= 500:
            resp.raise_for_status()  # retried by the decorator
        return resp

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        """GET and normalise: returns the JSON body, ``{"s": "no_data"}`` when there is none."""
        clean = {k: v for k, v in params.items() if v is not None}
        resp = self._fetch(path, clean)
        self._record_credits(resp)
        code = resp.status_code
        if code in (204, 404):
            return {"s": "no_data"}
        if code == 401:
            raise AuthenticationError("MarketData.app rejected the API token (401 Unauthorized)")
        if code == 402:
            raise MarketDataError(f"MarketData.app: your plan does not allow {path} (402)")
        if code == 429:
            raise QuotaExceededError("MarketData.app: credit or rate limit reached (429)")
        try:
            body = resp.json()
        except ValueError as exc:
            raise MarketDataError(f"MarketData.app returned non-JSON for {path}") from exc
        if not isinstance(body, dict):
            raise MarketDataError(f"MarketData.app returned an unexpected body for {path}")
        if code >= 400 or body.get("s") == "error":
            raise MarketDataError(
                f"MarketData.app error on {path}: {body.get('errmsg') or f'HTTP {code}'}"
            )
        return body

    def _record_credits(self, resp: httpx.Response) -> None:
        self.requests += 1
        remaining = resp.headers.get("x-api-ratelimit-remaining")
        consumed = resp.headers.get("x-api-ratelimit-consumed")
        try:
            if remaining is not None:
                self.credits_remaining = int(remaining)
            if consumed is not None:
                self.credits_used += int(consumed)
        except ValueError:
            pass

    def ensure_budget(self, needed: int) -> None:
        """Raise :class:`QuotaExceededError` when the plan is known to have fewer than ``needed``
        credits left (W27 step 4). Unknown (no response yet) passes: the first call reports it."""
        if self.credits_remaining is not None and self.credits_remaining < needed:
            raise QuotaExceededError(
                f"MarketData.app: {self.credits_remaining} credits left today, a ticker needs "
                f"about {needed}"
            )

    @staticmethod
    def _col(body: dict[str, Any], key: str) -> list[Any]:
        value = body.get(key)
        return list(value) if isinstance(value, list) else []

    @staticmethod
    def _today() -> date:
        """The US market's date (New York). The last session is the weekday before it: asking
        by ``date`` for the session still running in New York is refused as not historical,
        which a UTC date does every evening after 7 or 8 pm Eastern."""
        return datetime.now(tz=_NEW_YORK).date()

    def _year_series(self, symbol: str, *, raw: bool) -> dict[str, Any]:
        """One year of daily stock candles, dividend-adjusted (default) or split-only, fetched
        once per ticker and day (W27 step 6)."""
        key = (symbol, raw, self._today())
        if key not in self._series:
            extra = {"adjustsplits": "true", "adjustdividends": "false"} if raw else {}
            self._series[key] = self._candles("stocks", symbol, self.HISTORY_DAYS, **extra)
        return self._series[key]

    def _candles(self, kind: str, symbol: str, days: int, **extra: Any) -> dict[str, Any]:
        """Daily candles for a stock (``kind="stocks"``) or index (``kind="indices"``)."""
        return self._get(
            f"/{kind}/candles/D/{symbol}/",
            countback=int(days),
            to=datetime.now(tz=UTC).date().isoformat(),
            **extra,
        )

    def _closes(self, kind: str, symbol: str, days: int, **extra: Any) -> list[float]:
        body = self._candles(kind, symbol, days, **extra)
        return [_f(c) for c in self._col(body, "c") if _f(c) > 0][-days:]

    # -- MarketSource -------------------------------------------------------------------
    def _session_spot(self, sym: str) -> tuple[float, datetime] | None:
        """The underlying's price at the session the chain is from (``underlyingPrice``), so the
        stock and its options are quoted at the same moment (W27; see W28)."""
        try:
            _day, body = self._session_chain(sym)
        except (AuthenticationError, QuotaExceededError):
            raise  # a rejected key or a spent plan fails the quote as well
        except MarketDataError:
            return None  # no chain for this ticker: price it from a quote
        prices = [_f(x) for x in self._col(body, "underlyingPrice") if _f(x) > 0]
        stamps = [_i(u) for u in self._col(body, "updated") if _i(u) > 0]
        if not prices:
            return None
        when = datetime.fromtimestamp(max(stamps), tz=UTC) if stamps else datetime.now(tz=UTC)
        return prices[0], when

    def get_spot(self, ticker: str) -> SpotQuote:
        sym = ticker.upper()
        if self.chain_feed == "historical":
            session = self._session_spot(sym)
            if session is not None:
                return SpotQuote(
                    ticker=sym,
                    price=session[0],
                    avg_volume=self._average_volume(sym),
                    as_of=session[1],
                    sector="Unknown",
                )
        body = self._get(f"/stocks/quotes/{sym}/")
        last = self._col(body, "last")
        mid = self._col(body, "mid")
        if body.get("s") != "ok" or not (last or mid):
            raise MarketDataError(f"MarketData.app returned no quote for {sym}")
        price = _f(last[0] if last else None) or _f(mid[0] if mid else None)
        if price <= 0:
            raise MarketDataError(f"MarketData.app quote for {sym} has no price")
        return SpotQuote(
            ticker=sym,
            price=price,
            avg_volume=self._average_volume(sym),
            as_of=datetime.now(tz=UTC),
            sector="Unknown",  # MarketData.app quotes carry no sector; the curated list supplies it
        )

    def _session_chain(self, sym: str) -> tuple[date, dict[str, Any]]:
        """The whole chain at the last session's close, one request (W27): yesterday, or the
        weekday before it when that session has no data (a weekend or a holiday)."""
        key = (sym, self._today())
        if key in self._chains:
            return self._chains[key]
        day = self._today() - timedelta(days=1)
        tried = 0
        while tried < self.SESSION_LOOKBACK:
            if day.weekday() < 5:
                tried += 1
                body = self._get(f"/options/chain/{sym}/", date=day.isoformat(), expiration="all")
                if body.get("s") == "ok" and self._col(body, "strike"):
                    self._chains[key] = (day, body)
                    return self._chains[key]
            day -= timedelta(days=1)
        raise MarketDataError(f"{sym}: MarketData.app has no chain in the last sessions")

    def _average_volume(self, sym: str) -> float:
        """Quotes carry only the session volume; average the last ~3 months of candles."""
        try:
            candles = self._year_series(sym, raw=False)
        except QuotaExceededError:
            raise
        except Exception as exc:
            log.info("marketdata average volume unavailable for %s: %s", sym, type(exc).__name__)
            return 0.0
        vols = [_f(v) for v in self._col(candles, "v")[-self.AVG_VOLUME_DAYS :] if _f(v) > 0]
        return sum(vols) / len(vols) if vols else 0.0

    def list_expiries(self, ticker: str) -> list[date]:
        sym = ticker.upper()
        if self.chain_feed == "historical":
            _day, body = self._session_chain(sym)
            found = {_as_date(raw) for raw in self._col(body, "expiration")}
            return sorted(d for d in found if d is not None)
        body = self._get(f"/options/expirations/{sym}/")
        out: list[date] = []
        for raw in self._col(body, "expirations"):
            parsed = _as_date(raw)
            if parsed is not None:
                out.append(parsed)
        return sorted(out)

    def get_option_chain(self, ticker: str, expiry: date) -> OptionChain:
        sym = ticker.upper()
        if self.chain_feed == "historical":
            _day, full = self._session_chain(sym)
            keep = [
                i for i, raw in enumerate(self._col(full, "expiration")) if _as_date(raw) == expiry
            ]
            if not keep:
                raise MarketDataError(f"{sym}: MarketData.app has no chain for {expiry}")
            body = {
                k: [v[i] for i in keep if i < len(v)] if isinstance(v, list) else v
                for k, v in full.items()
            }
        else:
            body = self._get(
                f"/options/chain/{sym}/",
                expiration=expiry.isoformat(),
                strikeLimit=self.strike_limit or None,
            )
        if body.get("s") != "ok":
            raise MarketDataError(f"{sym}: MarketData.app has no chain for {expiry}")
        cols = {
            k: self._col(body, k)
            for k in (
                "optionSymbol",
                "side",
                "strike",
                "bid",
                "ask",
                "last",
                "volume",
                "openInterest",
                "iv",
            )
        }

        def cell(key: str, i: int) -> Any:
            col = cols[key]
            return col[i] if i < len(col) else None

        calls: list[OptionQuote] = []
        puts: list[OptionQuote] = []
        for i in range(len(cols["strike"])):
            kind = str(cell("side", i) or "").lower()
            if kind not in {"call", "put"}:
                continue
            try:
                quote = OptionQuote(
                    contract_symbol=str(cell("optionSymbol", i) or f"{sym}{expiry}{kind}"),
                    kind="call" if kind == "call" else "put",
                    strike=float(cell("strike", i)),
                    expiry=expiry,
                    bid=_f(cell("bid", i)),
                    ask=_f(cell("ask", i)),
                    last=_f(cell("last", i)),
                    volume=_i(cell("volume", i)),
                    open_interest=_i(cell("openInterest", i)),
                    iv=_f(cell("iv", i)),
                )
            except (ValueError, TypeError) as exc:
                log.debug("skipping bad MarketData.app row %s: %s", cell("optionSymbol", i), exc)
                continue
            (calls if kind == "call" else puts).append(quote)
        stamps = [_i(u) for u in self._col(body, "updated") if _i(u) > 0]
        as_of = datetime.fromtimestamp(max(stamps), tz=UTC) if stamps else datetime.now(tz=UTC)
        return OptionChain(ticker=sym, expiry=expiry, as_of=as_of, calls=calls, puts=puts)

    def get_earnings_date(self, ticker: str) -> date | None:
        """Next projected report date from /stocks/earnings; None when nothing is scheduled.

        A provider error propagates (W5): the facade records it and marks the date unknown, so
        a failed lookup never reads as "no earnings before expiry".
        """
        today = datetime.now(tz=UTC).date()
        body = self._get(
            f"/stocks/earnings/{ticker.upper()}/",
            **{
                "from": today.isoformat(),
                "to": (today + timedelta(days=self.EARNINGS_HORIZON_DAYS)).isoformat(),
            },
        )
        upcoming: list[date] = []
        for raw in self._col(body, "reportDate") or self._col(body, "date"):
            d = _as_date(raw)
            if d is not None and d >= today:
                upcoming.append(d)
        return min(upcoming) if upcoming else None

    def get_close_history(self, ticker: str, days: int) -> list[float]:
        sym = ticker.upper()
        if days > self.HISTORY_DAYS:
            return self._closes("stocks", sym, days)
        series = self._year_series(sym, raw=False)
        return [_f(c) for c in self._col(series, "c") if _f(c) > 0][-days:]

    def get_dividend_yield(self, ticker: str) -> float:
        """Trailing yield implied by dividend adjustment: 1 - adjusted/split-only first close.

        MarketData.app has no dividends endpoint. Its daily candles are dividend-adjusted by
        default; the split-only series is the raw price. Over one year the ratio of the two
        oldest closes is the product of (1 - D/P) over every ex-date, i.e. ~ the trailing yield.

        Provider errors and series that cannot support the estimate raise (W5) rather than
        returning 0.0, so the facade can mark the yield unknown instead of assuming none.
        """
        sym = ticker.upper()
        days = self.DIVIDEND_LOOKBACK_DAYS
        adjusted = [_f(c) for c in self._col(self._year_series(sym, raw=False), "c") if _f(c) > 0][
            -days:
        ]
        raw = [_f(c) for c in self._col(self._year_series(sym, raw=True), "c") if _f(c) > 0][-days:]
        if len(adjusted) != len(raw):
            raise MarketDataError(f"{sym}: dividend series mismatch")
        if len(adjusted) < MIN_IV_HISTORY or raw[0] <= 0:
            raise MarketDataError(f"{sym}: too little price history to infer a dividend yield")
        implied = 1.0 - adjusted[0] / raw[0]
        if implied > 0.20:
            raise MarketDataError(f"{sym}: implausible implied dividend yield {implied:.1%}")
        return max(implied, 0.0)  # a tiny negative is rounding on a non-payer

    def get_index_history(self, symbol: str, days: int) -> list[float]:
        mapped = self._INDEX_SYMBOLS.get(symbol.upper())
        if not mapped:
            raise MarketDataError(f"MarketData.app cannot serve index history for {symbol}")
        return self._closes("indices", mapped, days)

    def get_index_last(self, symbol: str) -> float:
        mapped = self._INDEX_SYMBOLS.get(symbol.upper())
        if not mapped:  # ^IRX: no T-bill index; the facade falls back to RISK_FREE_FALLBACK
            raise MarketDataError(f"MarketData.app cannot serve index quote for {symbol}")
        body = self._get(f"/indices/quotes/{mapped}/")
        last = self._col(body, "last") or self._col(body, "mid")
        if body.get("s") != "ok" or not last or _f(last[0]) <= 0:
            raise MarketDataError(f"MarketData.app returned no quote for {symbol}")
        return _f(last[0])

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class TradierSource:
    """Keyed provider: Tradier Brokerage REST API (sandbox or production).

    Tradier gives quotes, expirations, option chains with IV and daily history for one API key.
    A free developer (sandbox) key returns 15-minute delayed data, which is all this educational
    screener needs. Earnings dates and dividends come from Tradier's *beta* fundamentals endpoints
    and degrade to ``None`` / ``0.0`` when unavailable; index series (^VIX, ^IRX) fall back to
    ``fallback`` (a :class:`MarketDataAppSource` when a MarketData.app token is configured).

    The key is only ever sent as a bearer header; it is never logged, cached or echoed in errors.
    """

    name = "tradier"
    SANDBOX_URL = "https://sandbox.tradier.com/v1"
    PRODUCTION_URL = "https://api.tradier.com/v1"
    _INDEX_SYMBOLS = {"^VIX": "VIX", "^SPX": "SPX"}

    def __init__(
        self,
        api_key: str,
        *,
        sandbox: bool = True,
        http_client: Any | None = None,
        fallback: MarketSource | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise MarketDataError("Tradier API key is empty")
        self.sandbox = sandbox
        self.base_url = self.SANDBOX_URL if sandbox else self.PRODUCTION_URL
        self._client = http_client or httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=20.0,
        )
        self._fallback = fallback

    def __repr__(self) -> str:  # never leak the key
        return f"TradierSource(sandbox={self.sandbox})"

    # -- transport ----------------------------------------------------------------------
    @_RETRY
    def _get(self, path: str, **params: Any) -> Any:
        resp = self._client.get(path, params=params)
        if resp.status_code == 401:
            raise MarketDataError("Tradier rejected the API key (401 Unauthorized)")
        if resp.status_code == 403:
            raise MarketDataError("Tradier: this key is not allowed to call " + path)
        if resp.status_code in (400, 429) and "quota violation" in resp.text.lower():
            # Tradier signals its rate limit as a 400 with a "Quota Violation" body
            raise QuotaExceededError("Tradier: rate limit reached (Quota Violation)")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _as_list(node: Any) -> list[Any]:
        """Tradier returns a dict for one record and a list for many; normalise."""
        if node is None or node == "null":
            return []
        return node if isinstance(node, list) else [node]

    # -- MarketSource -------------------------------------------------------------------
    def get_spot(self, ticker: str) -> SpotQuote:
        data = self._get("/markets/quotes", symbols=ticker.upper(), greeks="false")
        quotes = self._as_list((data.get("quotes") or {}).get("quote"))
        if not quotes:
            raise MarketDataError(f"Tradier returned no quote for {ticker}")
        q = quotes[0]
        price = _f(q.get("last")) or _f(q.get("close")) or _f(q.get("prevclose"))
        if price <= 0:
            raise MarketDataError(f"Tradier quote for {ticker} has no price")
        return SpotQuote(
            ticker=ticker.upper(),
            price=price,
            avg_volume=_f(q.get("average_volume")),
            as_of=datetime.now(tz=UTC),
            sector="Unknown",  # Tradier quotes carry no sector; the curated list supplies it
        )

    def list_expiries(self, ticker: str) -> list[date]:
        data = self._get(
            "/markets/options/expirations",
            symbol=ticker.upper(),
            includeAllRoots="true",
            strikes="false",
        )
        dates = self._as_list((data.get("expirations") or {}).get("date"))
        return sorted(date.fromisoformat(str(d)) for d in dates)

    def get_option_chain(self, ticker: str, expiry: date) -> OptionChain:
        data = self._get(
            "/markets/options/chains",
            symbol=ticker.upper(),
            expiration=expiry.isoformat(),
            greeks="true",
        )
        calls: list[OptionQuote] = []
        puts: list[OptionQuote] = []
        for rec in self._as_list((data.get("options") or {}).get("option")):
            kind = str(rec.get("option_type", "")).lower()
            if kind not in {"call", "put"}:
                continue
            greeks = rec.get("greeks") or {}
            iv = _f(greeks.get("mid_iv")) or _f(greeks.get("smv_vol")) or _f(greeks.get("bid_iv"))
            try:
                quote = OptionQuote(
                    contract_symbol=str(rec.get("symbol") or f"{ticker}{expiry}{kind}"),
                    kind="call" if kind == "call" else "put",
                    strike=float(rec["strike"]),
                    expiry=expiry,
                    bid=_f(rec.get("bid")),
                    ask=_f(rec.get("ask")),
                    last=_f(rec.get("last")),
                    volume=_i(rec.get("volume")),
                    open_interest=_i(rec.get("open_interest")),
                    iv=iv,
                )
            except (KeyError, ValueError, TypeError) as exc:
                log.debug("skipping bad Tradier row %s: %s", rec.get("symbol"), exc)
                continue
            (calls if kind == "call" else puts).append(quote)
        return OptionChain(
            ticker=ticker.upper(), expiry=expiry, as_of=datetime.now(tz=UTC), calls=calls, puts=puts
        )

    def get_earnings_date(self, ticker: str) -> date | None:
        """Next report date via the beta fundamentals calendar; None when nothing is scheduled.

        Errors (including a plan without fundamentals access) propagate (W5).
        """
        data = self._get("/beta/markets/fundamentals/calendars", symbols=ticker.upper())
        today = datetime.now(tz=UTC).date()
        upcoming: list[date] = []
        for result in self._as_list(data):
            tables = (result or {}).get("tables") or {}
            for ev in self._as_list(tables.get("corporate_calendars")):
                text = f"{ev.get('event', '')} {ev.get('event_type', '')}".lower()
                if "earnings" not in text and "results" not in text:
                    continue
                raw = str(ev.get("begin_date_time") or ev.get("date") or "")[:10]
                try:
                    d = date.fromisoformat(raw)
                except ValueError:
                    continue
                if d >= today:
                    upcoming.append(d)
        return min(upcoming) if upcoming else None

    def get_close_history(self, ticker: str, days: int) -> list[float]:
        end = datetime.now(tz=UTC).date()
        start = end - timedelta(days=int(days * 1.6) + 7)  # trading days → calendar days
        data = self._get(
            "/markets/history",
            symbol=ticker.upper(),
            interval="daily",
            start=start.isoformat(),
            end=end.isoformat(),
        )
        rows = self._as_list((data.get("history") or {}).get("day"))
        closes = [_f(r.get("close")) for r in rows if _f(r.get("close")) > 0]
        return closes[-days:]

    def get_dividend_yield(self, ticker: str) -> float:
        """Trailing 12-month cash dividends / price via the beta fundamentals endpoint.

        Errors propagate (W5); 0.0 only for a successful response with no recent dividends.
        """
        data = self._get("/beta/markets/fundamentals/dividends", symbols=ticker.upper())
        price = self.get_spot(ticker).price
        if price <= 0:
            raise MarketDataError(f"Tradier quote for {ticker} has no price")
        cutoff = datetime.now(tz=UTC).date() - timedelta(days=365)
        total = 0.0
        for result in self._as_list(data):
            tables = (result or {}).get("tables") or {}
            for div in self._as_list(tables.get("cash_dividends")):
                raw = str(div.get("ex_date") or "")[:10]
                try:
                    if date.fromisoformat(raw) >= cutoff:
                        total += _f(div.get("cash_amount"))
                except ValueError:
                    continue
        return total / price

    def get_index_history(self, symbol: str, days: int) -> list[float]:
        mapped = self._INDEX_SYMBOLS.get(symbol.upper())
        if mapped:
            try:
                closes = self.get_close_history(mapped, days)
                if len(closes) >= MIN_IV_HISTORY:
                    return closes
            except Exception as exc:
                log.info("tradier index history %s failed: %s", symbol, type(exc).__name__)
        if self._fallback is None:
            raise MarketDataError(f"Tradier cannot serve index history for {symbol}")
        return self._fallback.get_index_history(symbol, days)

    def get_index_last(self, symbol: str) -> float:
        mapped = self._INDEX_SYMBOLS.get(symbol.upper())
        if mapped:
            try:
                return self.get_spot(mapped).price
            except Exception as exc:
                log.info("tradier index quote %s failed: %s", symbol, type(exc).__name__)
        if self._fallback is None:
            raise MarketDataError(f"Tradier cannot serve index quote for {symbol}")
        return self._fallback.get_index_last(symbol)

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


def _as_date(x: Any) -> date | None:
    """MarketData.app dates: unix seconds (US Eastern midnight) or ISO strings."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, int | float):
        try:
            return datetime.fromtimestamp(float(x), tz=UTC).date()
        except (OverflowError, OSError, ValueError):
            return None
    raw = str(x).strip()
    if raw.isdigit():
        return _as_date(int(raw))
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------------- facade
class UnavailableSource:
    """W42: the live default for a server that has no market-data key of its own.

    The server still starts and serves everything that needs no quotes (health, concept
    questions, requests that bring their own key); any quote it is asked for raises
    :class:`MarketDataError` with the reason, instead of every route failing at start-up."""

    name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def _fail(self) -> MarketDataError:
        return MarketDataError(self.reason)

    def get_spot(self, ticker: str) -> SpotQuote:
        raise self._fail()

    def list_expiries(self, ticker: str) -> list[date]:
        raise self._fail()

    def get_option_chain(self, ticker: str, expiry: date) -> OptionChain:
        raise self._fail()

    def get_earnings_date(self, ticker: str) -> date | None:
        raise self._fail()

    def get_close_history(self, ticker: str, days: int) -> list[float]:
        raise self._fail()

    def get_dividend_yield(self, ticker: str) -> float:
        raise self._fail()

    def get_index_history(self, symbol: str, days: int) -> list[float]:
        raise self._fail()

    def get_index_last(self, symbol: str) -> float:
        raise self._fail()

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


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
        credits_per_ticker: int = 0,
        vix_fallback: FredVix | None = None,
    ) -> None:
        self.source = source
        self.vix_fallback = vix_fallback  # used when the provider has no index data
        self.vix_source: str | None = None  # citation of where the last VIX came from
        self.credits_per_ticker = credits_per_ticker  # W27: 0 = no budget check
        self.cache = cache
        self.ttl = ttl
        self.iv_store = iv_store
        self.near_dte = near_dte
        self.far_dte_min = far_dte_min
        self.status: dict[str, str] = {}
        self._ns = source.name  # cache namespace so providers never read each other's quotes

    @classmethod
    def from_config(
        cls,
        cfg: AppConfig,
        mode: DataMode | None = None,
        *,
        provider: MarketProviderName | None = None,
        api_key: str | None = None,
    ) -> MarketData:
        """Build the facade.

        ``mode`` fixture → bundled JSON. Live → ``provider`` (argument, else
        ``OPTIONS_SCOUT_MARKET_PROVIDER``, else ``settings.market_data.provider``). Both live
        providers are keyed: ``api_key`` (argument wins; else the env var named in settings) and
        :class:`MarketDataError` is raised when none is available, so a missing key fails loudly
        up front. Tradier uses MarketData.app for ^VIX/^IRX when that token is also configured.
        """
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
        md_cfg = cfg.settings.market_data
        env_provider = os.environ.get("OPTIONS_SCOUT_MARKET_PROVIDER", "").strip().lower()
        chosen = provider or env_provider or md_cfg.provider
        source: MarketSource
        if chosen == "tradier":
            key = api_key or os.environ.get(md_cfg.tradier.api_key_env, "")
            if not key.strip():
                raise MarketDataError(
                    "Tradier selected but no API key given (paste one in the UI or set "
                    f"{md_cfg.tradier.api_key_env})"
                )
            fallback: MarketSource | None = None
            md_key = os.environ.get(md_cfg.marketdata.api_key_env, "")
            if md_key.strip():
                fallback = MarketDataAppSource(
                    md_key,
                    strike_limit=md_cfg.marketdata.strike_limit,
                    chain_feed=md_cfg.marketdata.chain_feed,
                )
            source = TradierSource(key, sandbox=md_cfg.tradier.sandbox, fallback=fallback)
        elif chosen == "marketdata":
            key = api_key or os.environ.get(md_cfg.marketdata.api_key_env, "")
            if not key.strip():
                raise MarketDataError(
                    "MarketData.app selected but no API token given (paste one in the UI or set "
                    f"{md_cfg.marketdata.api_key_env})"
                )
            source = MarketDataAppSource(
                key,
                strike_limit=md_cfg.marketdata.strike_limit,
                chain_feed=md_cfg.marketdata.chain_feed,
            )
        else:
            raise MarketDataError(f"unknown market data provider {chosen!r}")
        return cls(
            source,
            SQLiteCache(cfg.paths.cache_db),
            ttl,
            iv_store,
            near_dte=near,
            far_dte_min=far,
            credits_per_ticker=md_cfg.marketdata.credits_per_ticker,
            vix_fallback=FredVix.from_env() if md_cfg.vix_fallback == "fred" else None,
        )

    @classmethod
    def unavailable(cls, cfg: AppConfig, reason: str) -> MarketData:
        """A facade over :class:`UnavailableSource` (W42: a live server with no key of its own)."""
        return cls(
            UnavailableSource(reason),
            MemoryCache(),
            cfg.settings.cache_ttl_seconds.model_dump(),
            IVSnapshotStore(cfg.paths.iv_snapshot_db),
            near_dte=(cfg.rules.csp.dte_min - 10, cfg.rules.csp.dte_max + 15),
            far_dte_min=cfg.rules.leaps.dte_min - 35,
        )

    @property
    def available(self) -> bool:
        return not isinstance(self.source, UnavailableSource)

    @property
    def unavailable_reason(self) -> str | None:
        return self.source.reason if isinstance(self.source, UnavailableSource) else None

    # -- cached primitives -----------------------------------------------------------
    def _cached(self, key: str, ttl_key: str, fetch: Any, parse: Any) -> Any:
        key = f"{self._ns}:{key}"
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
        key = f"{self._ns}:earnings:{ticker}"
        hit = self.cache.get(key)
        if hit is not None:
            return date.fromisoformat(hit) if hit != "none" else None
        value = self.source.get_earnings_date(ticker)  # raises on failure: nothing is cached
        self.cache.set(key, value.isoformat() if value else "none", self.ttl["earnings"])
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

    MIN_VIX_HISTORY = 20  # fewer closes than this cannot place today's VIX in its year

    def get_vix_percentile(self, lookback_days: int = 252) -> tuple[float, float]:
        """Returns (vix_now, percentile 0-100 within the lookback window).

        From the provider; when it has no index data (MarketData.app answered empty on the
        user's plan, 2026-11-11), from FRED's VIXCLS, cited in :attr:`vix_source`."""
        try:
            return self._provider_vix(lookback_days)
        except Exception as exc:
            if self.vix_fallback is None:
                raise
            provider_error = exc
        try:
            closes = self.vix_fallback.closes(self.today())
        except Exception as exc:
            raise MarketDataError(
                f"VIX unavailable from the provider ({provider_error}) and FRED ({exc})"
            ) from None
        values = [v for _, v in closes][-lookback_days:]
        if len(values) < self.MIN_VIX_HISTORY:
            raise MarketDataError(f"FRED VIXCLS returned {len(values)} closes; too few")
        last_day = closes[-1][0]
        self.vix_source = f"{FRED_VIX_CITATION} (close of {last_day.isoformat()}). {FRED_NOTICE}"
        self.status["^VIX"] = f"FRED VIXCLS, close of {last_day.isoformat()}"
        return values[-1], volatility.percentile_rank(values[-1], values)

    def _provider_vix(self, lookback_days: int) -> tuple[float, float]:
        history = self._cached(
            f"index_hist:^VIX:{lookback_days}",
            "history",
            lambda: self.source.get_index_history("^VIX", lookback_days),
            lambda v: [float(x) for x in v],
        )
        if len(history) < self.MIN_VIX_HISTORY:
            raise MarketDataError(f"the provider returned {len(history)} VIX closes")
        vix_now = self._cached(
            "index_last:^VIX", "spot", lambda: self.source.get_index_last("^VIX"), float
        )
        self.vix_source = None
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

    def credits_remaining(self) -> int | None:
        """Credits the live provider reported left, or None when it has no such counter or has
        not answered yet."""
        value = getattr(self.source, "credits_remaining", None)
        return value if isinstance(value, int) else None

    def fit_to_budget(self, tickers: Sequence[str]) -> tuple[list[str], str | None]:
        """W27 step 4: before the fan-out, keep only as many tickers as the remaining credits
        cover at ``credits_per_ticker`` each, with one note naming the cut. Asks for the first
        ticker's quote (needed anyway, then cached) when the provider has not reported yet."""
        if not self.credits_per_ticker or not tickers or not hasattr(self.source, "ensure_budget"):
            return list(tickers), None
        if self.credits_remaining() is None:
            try:
                self.get_spot(tickers[0])
            except QuotaExceededError as exc:
                return [], f"data quota reached: {exc}; no ticker was fetched"
            except Exception:
                return list(tickers), None  # the per-ticker fetch reports the real error
        left = self.credits_remaining()
        if left is None:
            return list(tickers), None
        fits = max(left // self.credits_per_ticker, 0)
        if fits >= len(tickers):
            return list(tickers), None
        kept = list(tickers)[:fits]
        return kept, (
            f"data quota: {left} credits left today, about {self.credits_per_ticker} per ticker, "
            f"so {fits} of {len(tickers)} tickers were fetched"
            + (f" ({', '.join(kept)})" if kept else "")
        )

    def build_snapshot(self, ticker: str, expiries: Sequence[date] | None = None) -> TickerSnapshot:
        ticker = ticker.upper()
        errors: list[str] = []
        ensure = getattr(self.source, "ensure_budget", None)
        if self.credits_per_ticker and ensure is not None:
            ensure(self.credits_per_ticker)  # QuotaExceededError before anything is spent
        now = self.now()
        spot = self.get_spot(ticker)
        chains: list[OptionChain] = []
        for e in expiries if expiries is not None else self.relevant_expiries(ticker, now.date()):
            try:
                chains.append(self.get_option_chain(ticker, e))
            except QuotaExceededError:
                raise  # W27 step 5: a spent plan is not a fact about the ticker
            except Exception as exc:
                errors.append(f"chain {e}: {exc}")
        earnings: date | None = None
        earnings_known = True
        try:
            earnings = self.get_earnings_date(ticker)
        except QuotaExceededError:
            raise
        except Exception as exc:
            errors.append(f"earnings: lookup failed ({exc})")
            earnings_known = False
        hv30: float | None = None
        try:
            hv30 = self.get_hist_vol(ticker, 30)
        except QuotaExceededError:
            raise
        except Exception as exc:
            errors.append(f"hv30: {exc}")
        divy = 0.0
        dividend_yield_known = True
        try:
            divy = self.get_dividend_yield(ticker)
        except QuotaExceededError:
            raise
        except Exception as exc:
            errors.append(f"dividend: lookup failed ({exc})")
            dividend_yield_known = False

        atm_iv = atm_implied_vol(
            chains, spot.price, now.date(), self.near_dte, r=self.get_risk_free_rate(), q=divy
        )
        iv_rank, iv_source = self._iv_rank(ticker, atm_iv, hv30)
        self.status[ticker] = "ok" if not errors else f"partial: {len(errors)} errors"
        return TickerSnapshot(
            ticker=ticker,
            as_of=now,
            spot=spot,
            chains=chains,
            earnings_date=earnings,
            earnings_known=earnings_known,
            hv30=hv30,
            dividend_yield=divy,
            dividend_yield_known=dividend_yield_known,
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
    chains: Sequence[OptionChain],
    spot: float,
    today: date,
    near_dte: tuple[int, int],
    *,
    r: float = RISK_FREE_FALLBACK,
    q: float = 0.0,
) -> float | None:
    """Average IV of the ATM call and put on the nearest chain inside the near-DTE window.

    The provider's figure when it has one; otherwise the vol solved from the quote's mid (W27:
    MarketData.app's previous-session chains carry no IV), as the screeners do since W1."""
    near = [c for c in chains if near_dte[0] <= (c.expiry - today).days <= near_dte[1]]
    pool = near or list(chains)
    if not pool:
        return None
    target = min(pool, key=lambda c: abs((c.expiry - today).days - 37))
    t = max((target.expiry - today).days, 1) / 365.0
    ivs: list[float] = []
    for side in (target.calls, target.puts):
        if not side:
            continue
        quote = min(side, key=lambda x: abs(x.strike - spot))
        if quote.iv > 0:
            ivs.append(quote.iv)
        elif quote.mid > 0 and spot > 0:
            solved = pricing.implied_vol(quote.mid, spot, quote.strike, t, r, q, quote.kind)
            if solved is not None and solved > 0:
                ivs.append(solved)
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
    "FRED_NOTICE",
    "AuthenticationError",
    "FixtureSource",
    "FredVix",
    "MarketData",
    "MarketDataAppSource",
    "MarketDataError",
    "MarketSource",
    "QuotaExceededError",
    "TradierSource",
    "atm_implied_vol",
    "timedelta",
]
