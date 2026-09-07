"""Eight IBKR provider codes are TWO publishers, and counting codes would lie.

The corroboration rule counts distinct `_outlet(provider)` strings, so feeding
IBKR's raw codes would make `DJ-N` and `DJ-RTA` two outlets for ONE Dow Jones
wire story. Measured 4 September: "Albermarle Hires BHP's Ragnar Udd as
President, CEO" came back under both codes on the same day.

⚠️ THAT WOULD BE WORSE THAN THE CURRENT STATE. `news_min_sources` was loosened
from 2 to 1 on 21 August precisely because nothing could corroborate a lone
Yahoo story. Restoring 2 on top of code-counting would report corroboration for
a single wire story - a rule that LOOKS restored while being weaker than the one
it replaced, because it would pass while claiming two independent outlets.

So the mapping lives in the adapter: `NewsItem.provider` carries the PUBLISHER,
and `news.py`'s counting stays vendor-agnostic and unchanged.

The account's eight subscribed codes, measured the same day:
    BRFG, BRFUPDN                        -> Briefing.com
    DJ-N, DJ-RTA, DJ-RTE, DJ-RTG,
    DJ-RTPRO, DJNL                       -> Dow Jones
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qat.data.ibkr_news import IBKRNewsSource, publisher_for

from qat.data.news import corroborate


def test_every_dow_jones_channel_is_one_publisher() -> None:
    codes = ["DJ-N", "DJ-RTA", "DJ-RTE", "DJ-RTG", "DJ-RTPRO", "DJNL"]
    assert {publisher_for(c) for c in codes} == {"Dow Jones"}


def test_every_briefing_channel_is_one_publisher() -> None:
    assert {publisher_for(c) for c in ("BRFG", "BRFUPDN")} == {"Briefing.com"}


def test_an_unknown_code_is_kept_rather_than_guessed() -> None:
    """⚠️ A new provider must NOT silently collapse into an existing publisher.
    Keeping the code is the honest answer: it counts as its own outlet, which
    is the strict direction until someone maps it deliberately."""
    assert publisher_for("XYZ-NEW") == "XYZ-NEW"


def test_two_channels_of_one_publisher_do_not_corroborate() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR - the real 4 September headline."""
    now = datetime.now(UTC)
    headline = "Albermarle Hires BHP's Ragnar Udd as President, CEO"
    items = [
        IBKRNewsSource.to_item("BHP.AX", headline, "DJ-N", now),
        IBKRNewsSource.to_item("BHP.AX", headline, "DJ-RTA", now - timedelta(minutes=3)),
    ]

    assert corroborate(items, min_sources=2) == []


def test_two_genuine_publishers_do_corroborate() -> None:
    """Dow Jones AND Briefing.com is a real second outlet - which is the whole
    point of adding a second vendor."""
    now = datetime.now(UTC)
    headline = "Albermarle Hires BHP's Ragnar Udd as President, CEO"
    items = [
        IBKRNewsSource.to_item("BHP.AX", headline, "DJ-N", now),
        IBKRNewsSource.to_item("BHP.AX", headline, "BRFG", now - timedelta(minutes=3)),
    ]

    stories = corroborate(items, min_sources=2)

    assert len(stories) == 1
    assert set(stories[0].providers) == {"Dow Jones", "Briefing.com"}


def test_the_metadata_prefix_is_stripped_from_the_headline() -> None:
    """IBKR wraps headlines as `{A:800015,...:L:en,...}Real headline here`.
    Left in, it would reach the model as text and defeat title clustering,
    because two reports of one story carry DIFFERENT prefixes."""
    raw = (
        "{A:800015,800008:L:en,Chinese (Simplified and Traditional)}"
        "Rio Tinto Initiated at Underweight"
    )
    item = IBKRNewsSource.to_item("RIO.AX", raw, "DJ-N", datetime.now(UTC))

    assert item.title == "Rio Tinto Initiated at Underweight"


def test_a_headline_with_no_prefix_is_untouched() -> None:
    item = IBKRNewsSource.to_item("RIO.AX", "Plain headline", "DJ-N", datetime.now(UTC))

    assert item.title == "Plain headline"


def test_a_wire_story_is_never_marked_primary() -> None:
    """⚠️ `primary` means the COMPANY lodged it with the exchange. A wire
    service is reliable and still secondary - it reports on the news rather
    than being it - and marking one primary would bypass the two-source bar
    entirely via the filing exception."""
    item = IBKRNewsSource.to_item("BHP.AX", "Anything at all", "DJ-N", datetime.now(UTC))

    assert item.primary is False
