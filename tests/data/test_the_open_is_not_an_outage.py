"""`MARKET DATA DOWN` fired at every open, and every one was false.

Counted in the live log: 26, 27, 28 August, 31 August, 1, 2, 4 and 7 September -
EIGHT trading days, all at 00:05 UTC, which is 10:05 AEST, five minutes after the
ASX opens. Yahoo publishes ASX intraday about twenty minutes late, so at the open
nothing has printed yet and the feed is not down; it has not started.

⚠️ THIS IS THE SIBLING OF THE yfinance RAIL FIXED IN M167, AND IT WAS MISSED.
That one logged its own false `market data is down` at 10:04 - seven for seven -
and was corrected by measurement. The identical defect one layer up went
unlooked-for, so removing the first alarm only left the operator receiving the
second. This codebase's own idiom is "check whether the fix has a sibling"
(`from_ib_trade`); it was not applied.

The distinction the rail could not make:

* **never ticked** - the warm-up window. Benign, happens daily, and saying
  ERROR about it eight times teaches the operator to ignore the word.
* **ticked, then stopped** - a real outage, and the case this rail exists for.

⚠️ THE EVENT IS UNCHANGED IN BOTH CASES. `MarketDataFeedEvent(healthy=False)` is
still published, so the UI banner still says the feed is not flowing - which is
TRUE at the open. Only the log severity and wording change. Verified before
writing this: the sole consumer is `main_window._on_feed_health`, a banner, and
`kill_switch.py` records that this is deliberately not a trigger (M119).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest

from qat.data.market_data import MarketDataFeed, RawTick
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataFeedEvent


class _NeverTicks:
    async def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]:
        while True:
            await asyncio.sleep(0.01)
        yield  # pragma: no cover - keeps this an async generator


class _OneTickThenSilence:
    async def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]:
        yield RawTick(symbol=symbols[0], ts=datetime.now(UTC), price=100.0, volume=1.0)
        while True:
            await asyncio.sleep(0.01)


async def _run(source: object, bus: EventBus) -> None:
    feed = MarketDataFeed(
        bus,
        source,  # type: ignore[arg-type]
        ["AAA"],
        staleness_check_interval=0.02,
        feed_down_seconds=0.05,
    )
    await feed.start()
    await asyncio.sleep(0.4)
    await feed.stop()


async def _events(bus: EventBus) -> list[MarketDataFeedEvent]:
    seen: list[MarketDataFeedEvent] = []

    async def record(event: MarketDataFeedEvent) -> None:
        seen.append(event)

    bus.subscribe(MarketDataFeedEvent, record)
    return seen


@pytest.mark.asyncio
async def test_a_feed_that_has_never_ticked_is_not_reported_as_an_outage(caplog) -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR - the 8-for-8 false alarm."""
    bus = EventBus()
    with caplog.at_level(logging.WARNING):
        await _run(_NeverTicks(), bus)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], f"the open was reported as an outage: {[r.message for r in errors]}"
    assert "has not started" in caplog.text.lower() or "not an outage" in caplog.text.lower()


@pytest.mark.asyncio
async def test_the_warm_up_still_tells_the_operator_something(caplog) -> None:
    """Removing a false alarm must not trade it for silence."""
    bus = EventBus()
    with caplog.at_level(logging.WARNING):
        await _run(_NeverTicks(), bus)

    assert "market data" in caplog.text.lower()


@pytest.mark.asyncio
async def test_the_banner_still_learns_the_feed_is_not_flowing(caplog) -> None:
    """⚠️ The EVENT must not change - it is what the UI banner reads, and at
    the open 'not flowing' is true."""
    bus = EventBus()
    seen = await _events(bus)
    await _run(_NeverTicks(), bus)

    assert any(not e.healthy for e in seen), "the banner would show a healthy feed with no data"


@pytest.mark.asyncio
async def test_a_feed_that_ticked_and_then_stopped_is_still_an_ERROR(caplog) -> None:
    """⚠️ THE CASE THE RAIL EXISTS FOR. Once a price has printed, silence is a
    real outage and must keep its severity."""
    bus = EventBus()
    with caplog.at_level(logging.WARNING):
        await _run(_OneTickThenSilence(), bus)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a feed that went quiet after ticking was not reported as down"
    assert "MARKET DATA DOWN" in caplog.text
