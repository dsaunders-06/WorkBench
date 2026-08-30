"""A symbol the feed has never delivered is ABSENT, and the rail says so.

Item 33. `_check_staleness_once` skips a symbol with no recorded print - `if
last is None: continue` - so it is never marked stale, never publishes
`DataStaleEvent`, and never reaches `StrategyEngine._stale_symbols`. Nothing
said so anywhere.

The gate refuses; this reports. They are deliberately not the same mechanism: a
periodic pass cannot close a race, and a gate that runs only on an order cannot
tell you the state of the book before one is attempted.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from qat.data.market_data import MarketDataFeed, SyntheticMarketDataSource
from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent


def _feed(symbols: list[str]) -> MarketDataFeed:
    # A real source rather than a stub: nothing here starts the feed, the tests
    # drive `_check_staleness_once` directly, and a stub of the wrong shape is
    # how a fixture ends up proving something the production path does not do.
    return MarketDataFeed(EventBus(), SyntheticMarketDataSource(), symbols)


def test_last_print_at_is_none_for_a_symbol_that_has_never_printed() -> None:
    assert _feed(["AAA", "BBB"]).last_print_at("AAA") is None


def test_last_print_at_reports_the_print_time_once_seen() -> None:
    feed = _feed(["AAA"])
    seen = datetime(2026, 8, 31, 0, 5, tzinfo=UTC)
    feed._last_seen["AAA"] = seen

    assert feed.last_print_at("AAA") == seen


@pytest.mark.asyncio
async def test_absent_symbols_are_reported_with_a_count(caplog) -> None:
    """⚠️ A COUNT, not an adjective (M154). M151 asserted a suppression that
    never reached the log - 678 claimed against 774 still present - and a line
    carrying no number cannot be checked against anything."""
    feed = _feed(["AAA", "BBB", "CCC"])
    feed._last_seen["AAA"] = datetime.now(UTC)

    with caplog.at_level(logging.WARNING):
        await feed._check_staleness_once()

    line = next((m for m in caplog.messages if "have not printed" in m), None)
    assert line is not None, "absence was not reported at all"
    assert "2 of 3" in line


@pytest.mark.asyncio
async def test_nothing_is_reported_before_the_first_tick(caplog) -> None:
    """⚠️ THE NOISE CASE, and the reason the trigger is not "the session has
    opened": MarketDataFeed holds no market and no session and cannot express
    that. At the bell, and on every launch outside hours, NOTHING has printed -
    and "94 of 94 absent" on every pass would be noise, not a signal."""
    feed = _feed(["AAA", "BBB", "CCC"])

    with caplog.at_level(logging.WARNING):
        await feed._check_staleness_once()

    assert not [m for m in caplog.messages if "have not printed" in m]


@pytest.mark.asyncio
async def test_absence_is_reported_once_not_on_every_pass(caplog) -> None:
    feed = _feed(["AAA", "BBB"])
    feed._last_seen["AAA"] = datetime.now(UTC)

    with caplog.at_level(logging.WARNING):
        await feed._check_staleness_once()
        await feed._check_staleness_once()

    assert len([m for m in caplog.messages if "have not printed" in m]) == 1


@pytest.mark.asyncio
async def test_absence_never_publishes_a_stale_event() -> None:
    """⚠️ `DataStaleEvent` means "last printed N seconds ago", which is FALSE of
    a symbol that never printed. Routing absence through it would make the log
    lie in the exact way item 33 exists to stop."""
    feed = _feed(["AAA", "BBB"])
    feed._last_seen["AAA"] = datetime.now(UTC)
    seen: list[DataStaleEvent] = []

    async def _record(event: DataStaleEvent) -> None:
        seen.append(event)

    feed.bus.subscribe(DataStaleEvent, _record)
    await feed._check_staleness_once()

    assert not [e for e in seen if e.symbol == "BBB"]
