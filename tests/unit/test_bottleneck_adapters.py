"""Bottleneck adapters (PRD 4A.5, step 11.2): fixture search and mocked live transports.

Every live-mode test injects ``httpx.MockTransport``; nothing here touches the network.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from options_scout.bottleneck.adapters.base import fixtures_bottleneck_dir
from options_scout.bottleneck.adapters.csv_series import CsvSeriesAdapter
from options_scout.bottleneck.adapters.edgar_fts import (
    _DISPLAY_TICKER,
    EdgarFullTextSearch,
    _parse_hit,
)
from options_scout.bottleneck.adapters.fred import FredSeriesAdapter, parse_observations
from options_scout.bottleneck.adapters.social_bridge import (
    NewsHeadlineSource,
    RedditIndustrySource,
    TrendsSeriesSource,
)
from options_scout.bottleneck.adapters.transcripts import LIVE_UNAVAILABLE, TranscriptsAdapter
from options_scout.bottleneck.sources import sec_cik_to_ticker
from options_scout.bottleneck.themes import sec_ticker_validator
from options_scout.config import AppConfig, CsvSeriesSourceConfig, Subreddits
from options_scout.data.cache import MemoryCache
from options_scout.social.adapters.google_trends import GoogleTrendsAdapter
from options_scout.social.adapters.news import NewsAdapter
from options_scout.social.adapters.reddit import RedditAdapter

SINCE = datetime(2026, 6, 29, tzinfo=UTC)
NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
KW = ["transformer lead time", "switchgear lead time"]


def _fx(config: AppConfig) -> Path:
    return fixtures_bottleneck_dir(config.paths.fixtures_dir)


def _edgar(config: AppConfig, mode: str = "fixture", **kw: object) -> EdgarFullTextSearch:
    return EdgarFullTextSearch(
        mode,  # type: ignore[arg-type]
        config.bottleneck_sources.edgar,
        _fx(config) / "edgar_snippets.jsonl",
        is_valid_ticker=sec_ticker_validator(config.paths.fixtures_dir),
        cik_to_ticker=sec_cik_to_ticker(config.paths.fixtures_dir),
        now=NOW,
        **kw,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------------------- EDGAR
def test_edgar_fixture_searches_by_keyword_date_and_form(config: AppConfig) -> None:
    edgar = _edgar(config)
    rows = edgar.fetch(KW, SINCE, theme_id="electrification", layer_id="grid")
    assert rows and edgar.status().ok and edgar.status().items == len(rows)
    assert all(any(k in r.text.lower() for k in KW) for r in rows)
    assert all(r.date >= SINCE.date() and r.source == "edgar" for r in rows)
    assert all(r.theme_id == "electrification" and r.layer_hint == "grid" for r in rows)
    assert all(r.filer_ticker and r.url and r.form in {"10-K", "10-Q", "8-K"} for r in rows)
    form = rows[0].form
    only = edgar.fetch(KW, SINCE, forms=[form])  # type: ignore[list-item]
    assert only and all(r.form == form for r in only) and len(only) < len(rows)
    later = edgar.fetch(KW, datetime(2026, 10, 20, tzinfo=UTC))
    assert len(later) < len(rows)
    assert edgar.fetch(["no such phrase xyz"], SINCE) == []
    assert edgar.fixture_end() == datetime(2026, 10, 27, tzinfo=UTC)
    # designed labels and the adversarial ids come along for the offline LLM and the evals
    assert len(edgar.ground_truth) == 142 and len(edgar.adversarial_ids) == 14
    assert all(edgar.ground_truth[s.id].snippet_id == s.id for s in rows)


def test_edgar_fixture_missing_file_is_an_error_not_an_exception(config: AppConfig) -> None:
    edgar = EdgarFullTextSearch("fixture", config.bottleneck_sources.edgar, Path("/nope.jsonl"))
    assert edgar.fetch(KW, SINCE) == [] and not edgar.status().ok
    assert "fixture missing" in edgar.status().errors[0]
    assert edgar.fixture_end() is None


def _hits(cik: int, name: str, form: str = "10-Q") -> dict[str, object]:
    return {
        "hits": {
            "hits": [
                {
                    "_id": f"0000950170-26-012345:{name.lower()}-20260630.htm",
                    "_source": {
                        "ciks": [f"{cik:010d}"],
                        "display_names": [f"{name} INC  ({name})  (CIK {cik:010d})"],
                        "file_date": "2026-08-01",
                        "form_type": form,
                    },
                },
                {"_id": "garbage-without-colon", "_source": {}},
            ]
        }
    }


HTML_DOC = (
    "<html><body><p>Item 1A. Risk Factors.</p><p>"
    + "We sell electrical equipment to utilities. " * 20
    + "Lead times for distribution transformers extended to 104 weeks as transformer lead time "
    + "remained a constraint on our customers.</p><p>"
    + "Other matters. " * 40
    + "</p></body></html>"
)


def test_edgar_live_search_opens_documents_paces_and_caches(config: AppConfig) -> None:
    ciks = sec_cik_to_ticker(config.paths.fixtures_dir)
    hon_cik = next(c for c, t in ciks.items() if t == "HON")
    calls: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert "options-scout-ai" in request.headers["User-Agent"]
        if request.url.host == "efts.sec.gov":
            assert request.url.params["q"] == '"transformer lead time"'
            assert request.url.params["forms"] == "10-K,10-Q,8-K"
            assert request.url.params["startdt"] == "2026-06-29"
            return httpx.Response(200, json=_hits(hon_cik, "HON"))
        return httpx.Response(200, text=HTML_DOC)

    cache = MemoryCache()
    edgar = _edgar(
        config,
        "live",
        cache=cache,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        clock=lambda: 0.0,  # frozen clock: every request after the first waits 1/8 s
    )
    rows = edgar.fetch(
        ["transformer lead time"], SINCE, theme_id="electrification", layer_id="grid"
    )
    assert len(rows) == 1 and edgar.status().ok
    snip = rows[0]
    assert snip.filer_ticker == "HON" and snip.form == "10-Q" and snip.date == date(2026, 8, 1)
    assert (
        snip.url
        == f"https://www.sec.gov/Archives/edgar/data/{hon_cik}/000095017026012345/hon-20260630.htm"
    )
    assert "transformer lead time" in snip.text and len(snip.text) <= 400
    assert "<p>" not in snip.text and snip.layer_hint == "grid"
    assert len(calls) == 2 and sleeps == [pytest.approx(1 / 8)]
    # second run: both the search and the document come from the cache
    again = edgar.fetch(["transformer lead time"], SINCE)
    assert [s.id for s in again] == [snip.id] and len(calls) == 2


def test_edgar_live_4xx_is_final_and_5xx_is_retried(config: AppConfig) -> None:
    statuses: list[int] = []

    def forbidden(request: httpx.Request) -> httpx.Response:
        statuses.append(403)
        return httpx.Response(403, text="Forbidden")

    edgar = _edgar(config, "live", transport=httpx.MockTransport(forbidden), sleep=lambda _s: None)
    assert edgar.fetch(["transformer lead time"], SINCE) == []
    assert statuses == [403] and not edgar.status().ok and "403" in edgar.status().errors[0]

    seq: list[int] = []
    sleeps: list[float] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.host == "efts.sec.gov":
            seq.append(1)
            if len(seq) == 1:
                return httpx.Response(503)
            return httpx.Response(200, json=_hits(1, "ZZZT"))  # not in the SEC list
        return httpx.Response(200, text=HTML_DOC)

    edgar = _edgar(
        config, "live", transport=httpx.MockTransport(flaky), sleep=sleeps.append, clock=lambda: 1e9
    )
    rows = edgar.fetch(["transformer lead time"], SINCE)
    assert len(seq) == 2 and 1.0 in sleeps  # retried once after a 1 s backoff
    assert len(rows) == 1 and rows[0].filer_ticker is None  # unvalidated ticker is dropped
    assert edgar.status().ok

    exhausted = _edgar(
        config,
        "live",
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
        sleep=lambda _s: None,
        clock=lambda: 1e9,
    )
    assert exhausted.fetch(["x"], SINCE) == [] and "HTTP 500" in exhausted.status().errors[0]


def test_parse_hit_rejects_malformed_rows() -> None:
    assert _parse_hit({"_id": "nocolon", "_source": {}}) is None
    assert _parse_hit({"_id": "a:b", "_source": {"ciks": []}}) is None
    assert _parse_hit({"_id": "a:b", "_source": {"ciks": ["1"], "file_date": "bad"}}) is None
    doc = _parse_hit(
        {"_id": "0001-26-1:f.htm", "_source": {"ciks": ["0000000007"], "file_date": "2026-01-02"}}
    )
    assert doc is not None and doc["cik"] == 7 and doc["form"] is None
    assert doc["url"] == "https://www.sec.gov/Archives/edgar/data/7/0001261/f.htm"
    # the real API (checked 2026-11-06) names the form `form` / `file_type` and lists several
    # tickers in display_names; the fallback ticker parser takes the first one
    real = _parse_hit(
        {
            "_id": "0001829126-26-010462:x_10k.htm",
            "_source": {
                "ciks": ["0002109869"],
                "display_names": ["Exascale Labs Holdings Inc.  (XLAB, XLABW)  (CIK 0002109869)"],
                "file_date": "2026-09-28",
                "root_forms": ["10-K"],
                "form": "10-K",
                "file_type": "10-K",
            },
        }
    )
    assert real is not None and real["form"] == "10-K" and real["cik"] == 2109869
    assert real["url"].endswith("/2109869/000182912626010462/x_10k.htm")
    assert _DISPLAY_TICKER.search(real["display_name"]).group(1) == "XLAB"  # type: ignore[union-attr]
    assert _DISPLAY_TICKER.search("ACME CORP  (ACME)  (CIK 0000000001)").group(1) == "ACME"  # type: ignore[union-attr]


# -------------------------------------------------------------------------------- FRED
def test_fred_fixture_series_in_range(config: AppConfig) -> None:
    fred = FredSeriesAdapter(
        "fixture", config.bottleneck_sources.fred, _fx(config) / "fred_series.json"
    )
    pts = fred.fetch("WPU0543", date(2025, 10, 1), date(2026, 10, 27))
    assert len(pts) == 13 and pts == sorted(pts, key=lambda p: p.day)
    assert pts[-1].value > pts[0].value  # the power layer is designed to accelerate
    assert fred.fetch("NOPE", date(2025, 1, 1), date(2026, 1, 1)) == [] and fred.status().ok
    assert fred.status().items == 13
    # an empty series is not an error (the source worked) but it is never silent
    assert len(fred.status().errors) == 1 and "NOPE: no observations" in fred.status().errors[0]
    assert "discontinued" in fred.status().errors[0]


def test_fred_live_parses_skips_missing_and_caches(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    calls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        assert request.url.params["series_id"] == "WPU0543"
        assert request.url.params["api_key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "observations": [
                    {"date": "2026-01-01", "value": "101.5"},
                    {"date": "2026-02-01", "value": "."},
                    {"date": "2026-03-01", "value": "103.25"},
                ]
            },
        )

    cache = MemoryCache()
    fred = FredSeriesAdapter(
        "live", config.bottleneck_sources.fred, cache=cache, transport=httpx.MockTransport(handler)
    )
    pts = fred.fetch("WPU0543", date(2026, 1, 1), date(2026, 3, 31))
    assert [(p.day.isoformat(), p.value) for p in pts] == [
        ("2026-01-01", 101.5),
        ("2026-03-01", 103.25),
    ]
    assert fred.fetch("WPU0543", date(2026, 1, 1), date(2026, 3, 31)) == pts and len(calls) == 1
    assert "test-key" not in repr(fred)

    def discontinued(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"observations": []})  # FRED's answer for a dead series

    dead = FredSeriesAdapter(
        "live", config.bottleneck_sources.fred, transport=httpx.MockTransport(discontinued)
    )
    assert dead.fetch("PCU335921335921", date(2026, 1, 1), date(2026, 3, 31)) == []
    assert dead.status().ok and "PCU335921335921: no observations" in dead.status().errors[0]


def test_fred_live_errors(config: AppConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    fred = FredSeriesAdapter("live", config.bottleneck_sources.fred)
    assert fred.fetch("WPU0543", date(2026, 1, 1), date(2026, 2, 1)) == []
    assert not fred.status().ok and "FRED_API_KEY" in fred.status().errors[0]

    monkeypatch.setenv("FRED_API_KEY", "k")
    n_bad: list[int] = []

    def bad_request(request: httpx.Request) -> httpx.Response:
        n_bad.append(1)
        return httpx.Response(
            400, json={"error_message": "Bad Request. The series does not exist."}
        )

    fred = FredSeriesAdapter(
        "live",
        config.bottleneck_sources.fred,
        transport=httpx.MockTransport(bad_request),
        sleep=lambda _s: None,
    )
    assert fred.fetch("NOPE", date(2026, 1, 1), date(2026, 2, 1)) == [] and len(n_bad) == 1  # final
    assert "does not exist" in fred.status().errors[0]

    seq: list[int] = []
    sleeps: list[float] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        seq.append(1)
        if len(seq) < 3:
            return httpx.Response(502)
        return httpx.Response(200, json={"observations": [{"date": "2026-01-01", "value": "1"}]})

    fred = FredSeriesAdapter(
        "live",
        config.bottleneck_sources.fred,
        transport=httpx.MockTransport(flaky),
        sleep=sleeps.append,
    )
    assert len(fred.fetch("X", date(2026, 1, 1), date(2026, 2, 1))) == 1
    assert len(seq) == 3 and sleeps == [1.0, 2.0] and fred.status().ok


def test_parse_observations_tolerates_junk() -> None:
    pts = parse_observations(
        [
            {"date": "2026-02-01", "value": "2"},
            {"date": "bad", "value": "1"},
            {"day": "2026-01-01", "value": 1},
            {},
        ]
    )
    assert [p.day.isoformat() for p in pts] == ["2026-01-01", "2026-02-01"]


# --------------------------------------------------------------------------- CSV series
def test_csv_series_reads_operator_trackers(tmp_path: Path) -> None:
    (tmp_path / "memory_contract.csv").write_text(
        "Date,Value,note\n2026-01-15,4.10,x\n2026-02-15,4.55,\nnot-a-date,1\n2026-03-15,,\n2025-12-15,3.9,\n",
        encoding="utf-8",
    )
    (tmp_path / "bad_header.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    csv = CsvSeriesAdapter("fixture", CsvSeriesSourceConfig(directory=tmp_path))
    assert csv.available() == ["bad_header", "memory_contract"]
    pts = csv.fetch("memory_contract", date(2026, 1, 1), date(2026, 12, 31))
    assert [(p.day.isoformat(), p.value) for p in pts] == [
        ("2026-01-15", 4.1),
        ("2026-02-15", 4.55),
    ]
    assert csv.status().ok and csv.status().items == 2
    assert csv.fetch("memory_contract", date(2030, 1, 1), date(2030, 12, 31)) == []
    assert csv.status().ok and "no rows between 2030-01-01" in csv.status().errors[-1]
    assert csv.fetch("bad_header", date(2026, 1, 1), date(2026, 12, 31)) == []
    assert "header must contain" in csv.status().errors[-1]
    assert csv.fetch("missing", date(2026, 1, 1), date(2026, 12, 31)) == []
    assert csv.fetch("../etc/passwd", date(2026, 1, 1), date(2026, 12, 31)) == []
    assert not csv.status().ok and len(csv.status().errors) == 4

    empty = CsvSeriesAdapter("live", CsvSeriesSourceConfig(directory=tmp_path / "nothing"))
    assert empty.available() == [] and "no tracker CSVs" in empty.status().detail


# -------------------------------------------------------------------------- transcripts
def test_transcripts_fixture_only(config: AppConfig) -> None:
    fx = _fx(config) / "transcripts.jsonl"
    tr = TranscriptsAdapter("fixture", fx)
    rows = tr.fetch(
        [
            "HBM sold out",
            "DRAM contract price",
            "memory allocation",
            "memory supply tight",
            "wafer capacity",
            "HBM capacity",
        ],
        SINCE,
        layer_id="memory",
    )
    assert rows and all(r.source == "transcripts" and r.form is None for r in rows)
    assert all(r.layer_hint == "memory" for r in rows) and tr.ground_truth
    live = TranscriptsAdapter("live", fx)
    assert live.fetch(KW, SINCE) == [] and not live.status().ok
    assert live.status().errors == [LIVE_UNAVAILABLE] and live.status().detail == LIVE_UNAVAILABLE


# ------------------------------------------------------------------------------ bridges
def test_news_bridge_turns_headlines_into_labelled_snippets(config: AppConfig) -> None:
    fx = _fx(config) / "news.jsonl"
    cfg = config.bottleneck_sources.news
    news = NewsHeadlineSource(NewsAdapter("fixture", fx), cfg, fx)
    grid = config.themes.get("electrification")
    assert grid is not None
    layer = grid.get_layer("grid")
    assert layer is not None
    rows = news.fetch(layer.keywords, SINCE, theme_id="electrification", layer_id="grid")
    assert rows and len(rows) <= cfg.max_items_per_layer and news.status().ok
    assert all(r.source == "news" and r.filer_ticker is None and r.url for r in rows)
    assert all(r.text.endswith(")") for r in rows)  # "<title> (<outlet>)"
    assert all(r.id in news.ground_truth for r in rows)
    assert len(news.adversarial_ids) == 6
    capped = NewsHeadlineSource(
        NewsAdapter("fixture", fx), cfg.model_copy(update={"max_items_per_layer": 3}), fx
    )
    assert len(capped.fetch(layer.keywords, SINCE)) == 3


def test_reddit_bridge_filters_by_keyword_and_windows(config: AppConfig) -> None:
    fx = _fx(config) / "reddit_posts.jsonl"
    subs = Subreddits(
        consumer=list(config.subreddits.industry), stock=[], fetch=config.subreddits.fetch
    )
    bridge = RedditIndustrySource(
        RedditAdapter("fixture", subs, fx, config.sources.post_sources.reddit)
    )
    all_posts = bridge.posts(SINCE)
    assert len(all_posts) == 76 and bridge.status().ok
    assert {p.subreddit for p in all_posts} <= set(config.subreddits.industry)
    rows = bridge.fetch(KW, SINCE, layer_id="grid")
    assert rows and all("lead time" in r.text.lower() for r in rows)
    assert all(
        len(r.text) <= 400 and r.url and r.url.startswith("https://www.reddit.com/") for r in rows
    )
    assert not any("u_" in r.text for r in rows)
    assert bridge.fetch(["zebra crossing paint"], SINCE) == []  # noise posts carry no match
    until = datetime(2026, 8, 1, tzinfo=UTC)
    early = bridge.fetch(KW, SINCE, until=until)
    assert early and len(early) < len(rows) and all(r.date <= until.date() for r in early)


def test_trends_bridge_returns_float_series(config: AppConfig) -> None:
    fx = _fx(config) / "google_trends.json"
    bridge = TrendsSeriesSource(
        GoogleTrendsAdapter("fixture", config.sources.attention_sources.google_trends, fx)
    )
    pts = bridge.fetch("lithium price", date(2026, 10, 1), date(2026, 10, 27))
    assert len(pts) == 27 and all(isinstance(p.value, float) and 0 <= p.value <= 100 for p in pts)
    assert bridge.fetch("not a keyword", date(2026, 10, 1), date(2026, 10, 27)) == []


def test_fixture_corpus_is_consistent(config: AppConfig) -> None:
    """Every filer ticker is SEC-valid, every layer hint exists, every adversarial id is in a file."""
    fx = _fx(config)
    valid = sec_ticker_validator(config.paths.fixtures_dir)
    layer_ids = {layer.id for _, layer in config.themes.layers()}
    ids: set[str] = set()
    for name in ("edgar_snippets.jsonl", "transcripts.jsonl"):
        with (fx / name).open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                ids.add(row["id"])
                assert row["filer_ticker"] is None or valid(row["filer_ticker"])
                assert row["layer_hint"] in layer_ids and row["label"]["layer_id"] in layer_ids
                assert 1 <= len(row["text"]) <= 400
    adversarial = json.loads((fx / "adversarial.json").read_text(encoding="utf-8"))
    assert len(adversarial) == 20
    assert all(
        not valid(a["injected_ticker"]) or a["injected_ticker"] in {"GME", "AMC"}
        for a in adversarial
    )
    assert {a["id"] for a in adversarial if a["source"] == "edgar"} <= ids
