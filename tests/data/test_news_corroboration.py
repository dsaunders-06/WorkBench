"""M115: news reaches the advisor only when two independent sources carry it.

The original application pulled news for a ticker; the current one has no news
source at all, and `ai_advisory/context.py` calls that a regression. Restoring it
is not just a fetch, because news is the one input to this system written by
people who are not the operator, and anyone can publish.

**The operator's rule, recorded 20 August: at least two independent sources
before anything is pushed.** It is a quality rule and an injection defence at the
same time - a single planted story cannot reach the model, so an attacker needs
two outlets rather than one blog.

Measured against live Yahoo data on 20 August, which is what these tests encode:

* `RIO.AX` returned two items about **LSE:RIO**, the London listing. Yahoo
  conflates cross-listings, so an ASX position would be reasoned about using
  another exchange's news.
* `MGR.AX` returned an item about **(MRVGF)**, the US OTC line - the same
  problem in the other direction.
* A December 2025 story appeared in a "latest news" list, so the vendor's
  ordering cannot be trusted as recency.
* Providers were aggregators - GuruFocus, Simply Wall St - and Simply Wall St
  appeared TWICE for one symbol. Two items are not two sources.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qat.data.news import NewsItem, corroborate

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _item(title: str, provider: str, days_ago: float = 0.0, symbol: str = "MGR.AX") -> NewsItem:
    return NewsItem(
        symbol=symbol,
        title=title,
        provider=provider,
        published=NOW - timedelta(days=days_ago),
    )


def test_a_single_source_is_never_surfaced() -> None:
    """THE RULE. One outlet is not enough, however plausible it reads - which is
    exactly the property that makes a planted story unable to reach the model."""
    items = [_item("Mirvac Group FY 2026 earnings call highlights", "GuruFocus")]

    assert corroborate(items, now=NOW) == []


def test_two_independent_providers_on_one_story_are_surfaced() -> None:
    items = [
        _item("Mirvac Group FY 2026 earnings call highlights", "GuruFocus"),
        _item("Mirvac Group posts record FY 2026 earnings, says call", "Reuters"),
    ]

    stories = corroborate(items, now=NOW)

    assert len(stories) == 1
    assert set(stories[0].providers) == {"GuruFocus", "Reuters"}


def test_the_same_provider_twice_is_ONE_source() -> None:
    """Simply Wall St. appeared twice for RIO.AX on 20 August. Counting items
    rather than sources would have passed that as corroborated."""
    items = [
        _item("Rio Tinto secures long term renewable power for Tomago", "Simply Wall St."),
        _item("Rio Tinto secures long term renewable power deal Tomago", "Simply Wall St."),
    ]

    assert corroborate(items, now=NOW) == []


def test_provider_names_are_compared_loosely_enough_to_catch_a_rename() -> None:
    """ "Simply Wall St." and "Simply Wall St" are one outlet. Punctuation and
    case must not buy a second vote."""
    items = [
        _item("Mirvac posts record full year operating profit", "Simply Wall St."),
        _item("Mirvac posts record full year operating profit", "simply wall st"),
    ]

    assert corroborate(items, now=NOW) == []


def test_unrelated_stories_do_not_corroborate_each_other() -> None:
    """Two providers is not enough if they are talking about different things."""
    items = [
        _item("Mirvac Group FY 2026 earnings call highlights", "GuruFocus"),
        _item("Westpac director survives investor backlash over ASX ties", "Reuters"),
    ]

    assert corroborate(items, now=NOW) == []


def test_a_stale_item_cannot_corroborate_a_fresh_one() -> None:
    """A December 2025 story appeared in a LATEST news list. Order is not
    recency, so age is checked rather than trusted."""
    items = [
        _item("Mirvac Group FY 2026 earnings call highlights", "GuruFocus", days_ago=0.5),
        _item("Mirvac Group FY 2026 earnings call highlights", "Reuters", days_ago=250),
    ]

    assert corroborate(items, now=NOW, max_age=timedelta(days=7)) == []


def test_a_surfaced_story_carries_its_evidence() -> None:
    """A reader must be able to see WHY it passed - which outlets, and when -
    without going back to the vendor."""
    items = [
        _item("Mirvac Group FY 2026 earnings call highlights", "GuruFocus", days_ago=1),
        _item("Mirvac Group FY 2026 earnings call highlights", "Reuters", days_ago=0.5),
    ]

    story = corroborate(items, now=NOW)[0]

    assert len(story.providers) == 2
    assert story.published == NOW - timedelta(days=1), "the EARLIEST report, not the latest echo"
    assert "Mirvac" in story.title


def test_no_items_and_junk_degrade_to_nothing_rather_than_raising() -> None:
    assert corroborate([], now=NOW) == []
    assert corroborate([_item("", "GuruFocus"), _item("", "Reuters")], now=NOW) == []


def test_three_sources_still_produce_one_story() -> None:
    items = [
        _item("Mirvac Group FY 2026 earnings call highlights", "GuruFocus"),
        _item("Mirvac Group FY 2026 earnings call highlights", "Reuters"),
        _item("Mirvac Group FY 2026 earnings call highlights", "AFR"),
    ]

    stories = corroborate(items, now=NOW)

    assert len(stories) == 1
    assert len(stories[0].providers) == 3


# --- the cross-listing problem, measured on 20 August ------------------------


from qat.data.news import drop_other_listings  # noqa: E402


def test_an_explicitly_foreign_listing_is_dropped() -> None:
    """RIO.AX returned these two. Rio Tinto is dual-listed, the London line is a
    different security at a different price in a different currency, and an ASX
    position must not be reasoned about using it."""
    items = [
        _item(
            "Rio Tinto Group (LSE:RIO), Why Is It Back In The Spotlight?",
            "Simply Wall St.",
            symbol="RIO.AX",
        ),
        _item(
            "Rio Tinto (LSE:RIO) Secures Long Term Renewable Power For Tomago",
            "GuruFocus",
            symbol="RIO.AX",
        ),
    ]

    assert drop_other_listings(items) == []


def test_the_local_listing_is_kept() -> None:
    items = [
        _item("Mirvac Group (ASX:MGR) (FY 2026) Earnings Call Highlights", "GuruFocus"),
    ]

    assert len(drop_other_listings(items)) == 1


def test_a_bare_foreign_ticker_is_dropped_when_nothing_local_is_named() -> None:
    """MGR.AX returned "Mirvac Group (MRVGF) (H1 2026) Earnings Call Highlights".
    MRVGF is the US over-the-counter line - no exchange prefix to match on, just
    a ticker that is not this one."""
    items = [_item("Mirvac Group (MRVGF) (H1 2026) Earnings Call Highlights", "GuruFocus")]

    assert drop_other_listings(items) == []


def test_a_year_in_brackets_is_not_mistaken_for_a_ticker() -> None:
    """(FY 2026) and (H1 2026) are in these titles too. Dropping on any
    parenthesised token would throw away every earnings story there is."""
    items = [_item("Mirvac Group (FY 2026) earnings call highlights", "GuruFocus")]

    assert len(drop_other_listings(items)) == 1


def test_a_title_with_no_brackets_at_all_is_kept() -> None:
    items = [_item("Mirvac posts record full year operating profit", "Reuters")]

    assert len(drop_other_listings(items)) == 1


def test_the_pipeline_drops_then_corroborates() -> None:
    """The order matters. Two foreign-listing items would otherwise corroborate
    each other and surface London news against an ASX holding - which is exactly
    what the live RIO.AX sample would have done."""
    items = [
        _item(
            "Rio Tinto Group (LSE:RIO) back in the spotlight today",
            "Simply Wall St.",
            symbol="RIO.AX",
        ),
        _item("Rio Tinto Group (LSE:RIO) back in the spotlight today", "Reuters", symbol="RIO.AX"),
    ]

    assert corroborate(drop_other_listings(items), now=NOW) == []


def test_the_company_name_does_not_count_as_its_ticker() -> None:
    """Found by measuring, not by review. RIO.AX kept "Rio Tinto Ltd (RTNTF)
    (Q2 2026) Earnings Call Highlights" - RTNTF is the US over-the-counter line,
    and the filter let it through because "RIO" appears INSIDE "RIO TINTO" once
    the title is upper-cased. A ticker is a word, not a substring."""
    items = [
        _item(
            "Rio Tinto Ltd (RTNTF) (Q2 2026) Earnings Call Highlights", "GuruFocus", symbol="RIO.AX"
        ),
    ]

    assert drop_other_listings(items) == []


def test_the_local_ticker_as_a_whole_word_still_keeps_the_item() -> None:
    items = [
        _item("RIO leads the miners higher after a strong quarter", "AFR", symbol="RIO.AX"),
    ]

    assert len(drop_other_listings(items)) == 1


# --- the threshold, loosened 0.50 -> 0.40 on 20 August ------------------------


def test_the_rio_pair_that_0_50_rejected_now_corroborates() -> None:
    """The measured case that prompted the change: two outlets, one earnings
    call, similarity 0.44 - a true match thrown away by the old threshold.

    The live GuruFocus title carried "(RTNTF)" and is now dropped by
    `drop_other_listings` as the US over-the-counter line, so that exact pair no
    longer reaches `corroborate` from the real feed. The marker is removed here
    deliberately: this test isolates the THRESHOLD, and the listing filter has
    its own tests above. Loosening still shows on live data - RIO surfaced
    Oilprice.com and Proactive on the Tomago power deal instead."""
    items = [
        _item(
            "Rio Tinto Ltd (Q2 2026) Earnings Call Highlights: Strong Financials",
            "GuruFocus",
            symbol="RIO.AX",
        ),
        _item("Rio Tinto H1 Earnings Call Highlights", "MarketBeat", symbol="RIO.AX"),
    ]

    stories = corroborate(items, now=NOW)

    assert len(stories) == 1
    assert set(stories[0].providers) == {"GuruFocus", "MarketBeat"}


def test_loosening_did_not_reach_far_enough_to_merge_different_events() -> None:
    """The guard on the change. Two Mirvac stories about genuinely different
    things must still stay apart - otherwise the rule stops meaning
    "two outlets on ONE story" and starts meaning "two outlets on this company",
    which is a different and much weaker claim."""
    items = [
        _item("Mirvac Group FY 2026 earnings call highlights record profit", "GuruFocus"),
        _item("Mirvac appoints new chief financial officer from Lendlease", "Reuters"),
    ]

    assert corroborate(items, now=NOW) == []


# --- the primary-source exception --------------------------------------------


def test_a_single_PRIMARY_source_is_surfaced_alone() -> None:
    """Operator decision, 20 August. Corroboration defends against unreliable
    SECONDARY reporting - two outlets agreeing makes a claim harder to plant.
    An exchange filing is not a report about the news, it IS the news: the
    company lodged it, and the outlets below are reporting on this.

    Requiring a second source for a primary filing would discard the most
    authoritative input available because only one place published it, and the
    one place is the company itself."""
    items = [
        NewsItem(
            symbol="MGR.AX",
            title="Mirvac Group - FY26 Results Announcement",
            provider="ASX Company Announcements",
            published=NOW - timedelta(hours=2),
            primary=True,
        )
    ]

    stories = corroborate(items, now=NOW)

    assert len(stories) == 1
    assert stories[0].primary is True


def test_a_primary_source_does_not_make_secondary_stories_pass() -> None:
    """The exception is per-story, not a mode. An ASX filing about results must
    not drag an unrelated single-source blog post through with it."""
    items = [
        NewsItem(
            symbol="MGR.AX",
            title="Mirvac Group - FY26 Results Announcement",
            provider="ASX Company Announcements",
            published=NOW,
            primary=True,
        ),
        _item("Mirvac tipped to soar on secret takeover talk", "SomeBlog"),
    ]

    stories = corroborate(items, now=NOW)

    assert len(stories) == 1
    assert stories[0].primary is True


def test_secondary_reports_of_a_primary_filing_join_it() -> None:
    """When outlets do report the filing, they attach to it rather than forming
    a second story - the reader should see one event with its evidence."""
    items = [
        NewsItem(
            symbol="MGR.AX",
            title="Mirvac Group FY26 results announcement record profit",
            provider="ASX Company Announcements",
            published=NOW - timedelta(hours=3),
            primary=True,
        ),
        _item(
            "Mirvac Group FY26 results announcement shows record profit",
            "Reuters",
            days_ago=0.05,
        ),
    ]

    stories = corroborate(items, now=NOW)

    assert len(stories) == 1
    assert stories[0].primary is True
    assert len(stories[0].providers) == 2


def test_a_story_with_no_primary_source_is_marked_as_such() -> None:
    items = [
        _item("Mirvac Group FY 2026 earnings call highlights", "GuruFocus"),
        _item("Mirvac Group FY 2026 earnings call highlights", "Reuters"),
    ]

    assert corroborate(items, now=NOW)[0].primary is False


def test_stories_render_to_the_plain_dicts_the_advisory_context_takes() -> None:
    """`AdvisoryContext` imports nothing from the rest of the system - that is
    what lets the safety tests build one in isolation - so the mapping lives
    here rather than there, and is a function rather than glue in a Qt screen
    so it can be tested without one."""
    from qat.data.news import as_context_dicts

    items = [
        _item("Mirvac FY26 results record profit", "GuruFocus", days_ago=1),
        _item("Mirvac FY26 results show record profit", "Reuters", days_ago=0.5),
    ]

    dicts = as_context_dicts(corroborate(items, now=NOW))

    assert len(dicts) == 1
    story = dicts[0]
    assert set(story) == {"title", "providers", "published", "primary"}
    assert story["providers"] == ["GuruFocus", "Reuters"]
    assert story["published"] == "2026-08-19"
    assert story["primary"] is False
    assert isinstance(story["providers"], list), "must be JSON-plain, not a tuple"
