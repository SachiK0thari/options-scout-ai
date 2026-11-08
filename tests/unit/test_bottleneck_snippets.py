"""Snippet windowing, HTML stripping and near-duplicate dedupe (PRD 4A.3, step 11.2)."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from options_scout.bottleneck.snippets import (
    SNIPPET_MAX_CHARS,
    dedupe_snippets,
    headline_to_snippet,
    make_snippet,
    post_to_snippets,
    snippet_id,
    strip_html,
    window_text,
)
from options_scout.core.models import NewsItem, SocialPost

FILLER = "The company designs manufactures and sells industrial equipment to utilities. " * 12
DOC = (
    FILLER
    + "Lead times for distribution transformers extended to 104 weeks as transformer lead time "
    + "remained a constraint. "
    + FILLER
    + "Separately, switchgear lead time also lengthened in the period. "
    + FILLER
)


def test_window_text_is_bounded_and_contains_the_keyword() -> None:
    windows = window_text(DOC, ["transformer lead time", "switchgear lead time"])
    assert len(windows) == 2
    for w, kw in zip(windows, ["transformer lead time", "switchgear lead time"], strict=True):
        assert len(w) <= SNIPPET_MAX_CHARS and kw in w
        assert not w.startswith(" ") and not w.endswith(" ")
    # word boundaries: a window never starts or ends mid-word
    assert all(w[0].isalnum() or w[0] in "([\"'" for w in windows)


def test_window_text_merges_overlapping_hits_and_caps_count() -> None:
    dense = "transformer lead time rose; transformer lead time rose again; " * 3
    assert len(window_text(dense, ["transformer lead time"])) == 1  # one window covers all hits
    many = (FILLER + "switchgear lead time grew. ") * 10
    assert len(window_text(many, ["switchgear lead time"], max_windows=4)) == 4
    assert window_text(FILLER, ["helium shortage"]) == []  # no keyword, no snippet
    assert window_text("", ["x"]) == []


def test_window_text_handles_a_short_document() -> None:
    assert window_text("HBM sold out.", ["hbm sold out"]) == ["HBM sold out."]
    assert (
        window_text("x" * 50 + " DRAM contract price " + "y" * 50, ["DRAM contract price"])[0]
        == "x" * 50 + " DRAM contract price " + "y" * 50
    )


def test_strip_html_drops_scripts_tags_and_entities() -> None:
    markup = (
        "<html><head><style>p{color:red}</style><script>var x=1;</script></head>"
        "<body><p>Lead&nbsp;times&nbsp;rose&amp;fell.</p><table><tr><td>a</td><td>b</td></tr>"
        "</table><br/>Risk<b>factors</b></body></html>"
    )
    assert strip_html(markup) == "Lead times rose&fell. a b Risk factors"


def test_snippet_id_matches_the_fixture_generator_formula() -> None:
    day = date(2026, 9, 1)
    expected = hashlib.sha1(f"edgar|hello|HON|{day.isoformat()}".encode()).hexdigest()[:16]
    assert snippet_id("edgar", "hello", "HON", day) == expected
    snip = make_snippet(
        source="edgar", text="  hello  ", day=day, url=None, filer_ticker="hon", form="10-K"
    )
    assert snip.id == expected and snip.text == "hello" and snip.filer_ticker == "HON"


def test_headline_and_post_conversion() -> None:
    item = NewsItem(
        id="n1",
        title="  Transformer lead times stretch to 120 weeks ",
        published_at=datetime(2026, 9, 3, 12, tzinfo=UTC),
        source="Grid Weekly",
        url="https://example.com/a",
        query="transformer lead time",
    )
    snip = headline_to_snippet(item, theme_id="electrification", layer_id="grid")
    assert snip is not None
    assert snip.text == "Transformer lead times stretch to 120 weeks (Grid Weekly)"
    assert snip.date == date(2026, 9, 3) and snip.layer_hint == "grid" and snip.source == "news"
    assert (
        headline_to_snippet(item.model_copy(update={"title": "  "}), theme_id=None, layer_id=None)
        is None
    )

    post = SocialPost(
        id="p1",
        source="reddit",
        subreddit="electricians",
        author_id="u_42",
        created_at=datetime(2026, 9, 4, tzinfo=UTC),
        title="Anyone else seeing transformer lead time?",
        body="Quoted 64 weeks last month. " + FILLER,
        url="https://www.reddit.com/r/electricians/comments/p1/",
    )
    snips = post_to_snippets(post, ["transformer lead time"], theme_id=None, layer_id="grid")
    assert len(snips) == 1 and snips[0].source == "reddit"
    assert snips[0].text.startswith("Anyone else seeing transformer lead time? Quoted 64 weeks")
    assert "u_42" not in snips[0].text and len(snips[0].text) <= SNIPPET_MAX_CHARS
    assert post_to_snippets(post, ["helium shortage"], theme_id=None, layer_id=None) == []


def test_dedupe_collapses_near_duplicates_and_keeps_the_earliest() -> None:
    base = (
        "transformer lead time is among the industry conditions discussed under risk factors in "
        "this report; we cannot predict its effect on our grid solutions results."
    )
    a = make_snippet(source="edgar", text=base, day=date(2026, 8, 1), url=None, filer_ticker="HON")
    b = make_snippet(
        source="edgar",
        text=base + " No material change since the annual report.",
        day=date(2026, 9, 1),
        url=None,
        filer_ticker="HON",
    )
    c = make_snippet(
        source="news",
        text="HON announces new switchgear plant in Virginia to address transformer lead time",
        day=date(2026, 7, 15),
        url=None,
    )
    kept, dropped = dedupe_snippets([b, a, c, a])
    assert dropped == 2  # the exact repeat of `a` and the near-duplicate `b`
    assert [s.id for s in kept] == [c.id, a.id]  # date order, earliest of the pair kept
    kept2, dropped2 = dedupe_snippets([a, b], threshold=1.01)  # impossible threshold: keep both
    assert dropped2 == 0 and len(kept2) == 2
