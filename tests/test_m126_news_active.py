"""M126: Yahoo as the single news source, on by default, and visible.

The operator decision of 21 August 2026 settles item 2 of the outstanding list:
Yahoo is the news source for now. IBKR returned ZERO headlines for RIO.AX and
NHF.AX across 90 days, listcorp answers 403 on robots.txt itself, and ASX
ComNews is licensed even at its 20-minute tier - so free Yahoo is not the lazy
option here, it is the only one that returns anything on .AX at all.

Three things were left undone once that decision was made:

* the fetch was OFF by default, so none of it ran;
* the Workbench asked the same per-symbol question as the Advisor and was given
  strictly less to answer it with - no results date, no news;
* nothing was ever SHOWN. News was fetched, corroborated and handed to a model,
  and an operator reading the recommendation could not tell whether it rested
  on two stories or none.

Turning the fetch on does not weaken the injection stance. The two-source rule
still runs at the edge in `data/news.py`, the text still travels as inert data
rather than instruction, and the boundary is still guarded by
`tests/safety/test_prompt_injection_in_context_is_ignored.py`.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.presentation.advisory_inputs import news_enabled, news_for, next_earnings_for
from qat.presentation.ai_advisor import describe_sources


def test_yahoo_is_the_default_news_source() -> None:
    assert Settings(_env_file=None).news_source == "yfinance"


def test_it_can_still_be_switched_off() -> None:
    assert Settings(_env_file=None, news_source="none").news_source == "none"


# --- the shared inputs --------------------------------------------------------


class _Runtime:
    def __init__(self, source=None, calendar=None, news_setting="yfinance") -> None:
        self.news_source = source
        self.settings = Settings(_env_file=None, news_source=news_setting)
        self.signal_bridge = type("_B", (), {"earnings_calendar": calendar})()


class _Exploding:
    def fetch(self, symbol):
        raise RuntimeError("vendor down")


@pytest.mark.asyncio
async def test_a_broken_feed_never_stops_the_advisor_answering() -> None:
    """A third-party feed must not be able to take the screen down with it."""
    assert await news_for(_Runtime(source=_Exploding()), "RIO.AX") == []


@pytest.mark.asyncio
async def test_no_source_configured_is_simply_no_news() -> None:
    assert await news_for(_Runtime(source=None), "RIO.AX") == []


def test_an_exploding_calendar_degrades_to_unknown() -> None:
    class _Boom:
        def next_earnings(self, symbol):
            raise RuntimeError("no")

    assert next_earnings_for(_Runtime(calendar=_Boom()), "RIO.AX") == ""


def test_a_missing_calendar_degrades_to_unknown() -> None:
    assert next_earnings_for(_Runtime(calendar=None), "RIO.AX") == ""


def test_news_enabled_reads_the_setting() -> None:
    assert news_enabled(_Runtime(news_setting="yfinance")) is True
    assert news_enabled(_Runtime(news_setting="none")) is False


# --- what the operator is shown -----------------------------------------------


def test_off_and_nothing_found_are_different_sentences() -> None:
    """ "We did not ask" and "we asked and there was nothing" must not collapse
    into the same blank line - the distinction Status.UNKNOWN exists for."""
    off = describe_sources([], "", news_enabled=False)
    empty = describe_sources([], "", news_enabled=True)

    assert "OFF" in off
    assert "none corroborated" in empty
    assert off != empty


def test_the_stories_that_reached_the_model_are_named() -> None:
    news = [
        {
            "title": "Mirvac Group (ASX:MGR) FY 2026 Earnings Call Highlights",
            "providers": ["GuruFocus", "Simply Wall St"],
            "published": "2026-08-20",
            "primary": False,
        }
    ]

    shown = describe_sources(news, "2026-09-15", news_enabled=True)

    assert "Mirvac" in shown
    assert "GuruFocus" in shown and "Simply Wall St" in shown
    assert "2026-08-20" in shown
    assert "UNTRUSTED" in shown, "third-party text must be labelled where it is displayed"
    assert "2026-09-15" in shown


def test_a_primary_source_story_says_so_rather_than_listing_one_outlet() -> None:
    """M116's exception, named where it applies. One outlet because it is the
    company itself passed a different test from two aggregators agreeing, and
    the operator weighing the answer should see which."""
    news = [
        {"title": "FY26 results", "providers": ["ASX"], "published": "2026-08-20", "primary": True}
    ]

    shown = describe_sources(news, "", news_enabled=True)

    assert "primary source" in shown


def test_an_unknown_results_date_is_stated_not_omitted() -> None:
    assert "unknown" in describe_sources([], "", news_enabled=True)
