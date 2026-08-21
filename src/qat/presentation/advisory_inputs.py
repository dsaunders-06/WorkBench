"""The per-symbol material an advisory answer is entitled to (M126).

Extracted from the AI Advisor screen because the Workbench asks the same
question about the same company and was given strictly less to answer it with -
no results date, no news - so the two screens could reach different views of one
company at one moment for no stated reason. Two copies of this would drift; one
copy cannot.

Functions rather than a mixin, and no Qt in here, so the fetching rules can be
tested without constructing a screen - the same reasoning `as_context_dicts`
gives for living in `data/news.py`.

Every path degrades to "nothing known". A third-party feed must never be able
to stop the advisor answering, and an advisory screen is the last place that
should raise.
"""

from __future__ import annotations

import asyncio
import logging

from qat.data.news import as_context_dicts, corroborate, drop_other_listings

logger = logging.getLogger(__name__)


def news_enabled(runtime: object) -> bool:
    settings = getattr(runtime, "settings", None)
    return getattr(settings, "news_source", "none") != "none"


async def news_for(runtime: object, symbol: str) -> list[dict[str, object]]:
    """Corroborated company news, or nothing.

    The fetch runs in a thread because the vendor client is blocking and the
    caller is the UI thread.

    THE CORROBORATION RULE IS APPLIED HERE, deterministically, before the text
    reaches a model - never by asking the model whether its sources agree. An
    attacker who controls one article also controls anything that article
    claims about its own corroboration.

    How many outlets it takes is `QAT_NEWS_MIN_SOURCES`, and it is read from
    settings rather than left at the function's default so that the operator
    can change it without a rebuild. It defaulted to two until 21 August; the
    reasoning for the change, and what it costs, is recorded at the setting.
    """
    source = getattr(runtime, "news_source", None)
    if source is None:
        return []
    settings = getattr(runtime, "settings", None)
    min_sources = int(getattr(settings, "news_min_sources", 2) or 2)
    try:
        items = await asyncio.to_thread(source.fetch, symbol)
        return as_context_dicts(corroborate(drop_other_listings(items), min_sources=min_sources))
    except Exception:  # noqa: BLE001 - news is never worth failing the screen for
        logger.debug("News fetch failed for %s", symbol, exc_info=True)
        return []


def next_earnings_for(runtime: object, symbol: str) -> str:
    """The next scheduled results date, ISO, or "" when unknown.

    Read from the calendar the ENTRY GATE already consults, so the advisor and
    the rail cannot disagree about when results land.
    """
    bridge = getattr(runtime, "signal_bridge", None)
    calendar = getattr(bridge, "earnings_calendar", None)
    if calendar is None:
        return ""
    try:
        when = calendar.next_earnings(symbol)
    except Exception:  # noqa: BLE001 - advisory context is never worth raising for
        logger.debug("Earnings lookup failed for %s", symbol, exc_info=True)
        return ""
    return when.isoformat() if when else ""
