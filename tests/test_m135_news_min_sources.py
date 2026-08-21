"""The corroboration bar is an operator setting, and the screen says what it is.

The two-source rule was surfacing NOTHING on the ASX names actually being asked
about. `data/news.py` already recorded why: NHF's six items came from one
outlet, so nothing could corroborate them, and the binding limit is Yahoo's
coverage of .AX names rather than the threshold. A rule that discards
everything is not a strict rule, it is a silent one.

Loosened to one outlet by operator decision on 21 August 2026. What that costs
is not hidden: a single planted story can now reach the model, which is exactly
what the two-source rule existed to prevent. What still holds is everything
that never depended on counting outlets - the text travels as inert `news`
rather than as instruction, `drop_other_listings` still runs, and
`tests/safety/test_prompt_injection_in_context_is_ignored.py` still guards the
boundary. So these tests pin the two things that make the looser bar readable:
the setting is honoured, and the screen states the bar it actually applied.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.data.news import NewsItem
from qat.presentation.advisory_inputs import news_for
from qat.presentation.ai_advisor import _sources_html, describe_sources


class _Runtime:
    def __init__(self, source=None, min_sources: int | None = None) -> None:
        self.news_source = source
        overrides = {} if min_sources is None else {"news_min_sources": min_sources}
        self.settings = Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


class _OneOutlet:
    """Six items from a single outlet - the live NHF.AX shape, measured
    20 August. Nothing here can corroborate anything."""

    def fetch(self, symbol: str) -> list[NewsItem]:
        now = datetime.now(UTC)
        return [
            NewsItem(
                symbol=symbol,
                title=f"nib holdings interim result commentary {index}",
                provider="Simply Wall St",
                published=now - timedelta(hours=index),
                url=f"https://example.invalid/{index}",
            )
            for index in range(6)
        ]


def test_one_source_is_the_shipped_default() -> None:
    assert Settings(_env_file=None).news_min_sources == 1


def test_the_bar_cannot_be_set_below_one() -> None:
    """Zero would not be a looser rule, it would be no rule - and a story
    carried by nobody is not a story."""
    with pytest.raises(ValueError):
        Settings(_env_file=None, news_min_sources=0)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_single_outlet_now_surfaces() -> None:
    """The whole point of the change. Under the old bar this returned []."""
    stories = await news_for(_Runtime(source=_OneOutlet()), "NHF.AX")
    assert stories, "one outlet should clear a bar of one"


@pytest.mark.asyncio
async def test_the_old_rule_is_still_reachable() -> None:
    """Set it to 2 and the previous behaviour returns exactly - the setting is
    a dial, not a demolition."""
    stories = await news_for(_Runtime(source=_OneOutlet(), min_sources=2), "NHF.AX")
    assert stories == []


def test_the_screen_names_the_bar_it_actually_applied() -> None:
    """The message used to say "the two-source rule" as a fixed phrase. Said
    while the rule was one, that is a screen misreporting its own control."""
    at_one = describe_sources([], "", news_enabled=True, min_sources=1)
    at_two = describe_sources([], "", news_enabled=True, min_sources=2)

    assert "1 outlet" in at_one
    assert "2 independent outlets" in at_two
    assert "none corroborated" in at_one


def test_a_headline_containing_markup_is_shown_as_words_not_markup() -> None:
    """The conversation is a rich-text widget and a headline is third-party
    text. The prompt already treats it as untrusted; the display has to as
    well, or the two disagree about what it is."""
    news = [
        {
            "title": "<b>Buy now</b> <script>alert(1)</script>",
            "providers": ["Somewhere"],
            "published": "2026-08-21",
            "primary": False,
        }
    ]

    rendered = _sources_html(describe_sources(news, "", news_enabled=True, min_sources=1))

    assert "<b>Buy now</b>" not in rendered
    assert "&lt;b&gt;Buy now&lt;/b&gt;" in rendered
    assert "<script>" not in rendered


def test_the_sources_block_still_breaks_into_lines() -> None:
    """Escaping happens BEFORE newlines become breaks. The other order would
    escape the breaks too and render the whole block as one run-on line, which
    is the defect that moved this out of a one-line label in the first place."""
    news = [
        {
            "title": "A result",
            "providers": ["Somewhere"],
            "published": "2026-08-21",
            "primary": False,
        }
    ]

    rendered = _sources_html(describe_sources(news, "", news_enabled=True, min_sources=1))

    assert "<br>" in rendered
    assert "&lt;br&gt;" not in rendered
