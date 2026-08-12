"""The only usable detection source, and its two traps (M39).

Account activities are useless: queried through a real split, MNST produced
`SPLIT: 0`, `CSD: 0`, `DIV: 0`. The announcements endpoint is all there is.

Two traps, both measured on 8 August:

* `target_symbol` is absent on roughly 10% of records - 32 of 291 reverse and 8
  of 63 forward splits in an 88-day sample - so a market-wide scan cannot
  attribute an announcement reliably. Per-symbol queries are the design.
* `payable_date` can precede `ex_date`. Nothing keys on the payable date.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qat.data.broker.mock_broker import MockBroker
from qat.domain.corporate_actions.announcements import Announcement


def _split(symbol: str = "SFBS", ex_date: date = date(2026, 8, 21)) -> Announcement:
    return Announcement(
        symbol=symbol,
        ex_date=ex_date,
        ratio=2.0,
        action_id="ca-1",
        payable_date=date(2026, 8, 20),
        fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_the_mock_returns_what_was_queued():
    broker = MockBroker(seed=1)
    broker.queue_announcement(_split())

    found = await broker.announcements("SFBS", date(2026, 8, 1), date(2026, 9, 1))

    assert [a.ratio for a in found] == [2.0]


@pytest.mark.asyncio
async def test_it_filters_by_symbol():
    """Per-symbol is the design, because target_symbol is missing on ~10% of
    records and a scan cannot be trusted to attribute them."""
    broker = MockBroker(seed=1)
    broker.queue_announcement(_split(symbol="SFBS"))

    assert await broker.announcements("AMD", date(2026, 8, 1), date(2026, 9, 1)) == []


@pytest.mark.asyncio
async def test_a_symbol_with_no_announcements_is_empty_not_an_error():
    broker = MockBroker(seed=1)

    assert await broker.announcements("AMD", date(2026, 8, 1), date(2026, 9, 1)) == []


@pytest.mark.asyncio
async def test_it_bounds_on_the_ex_date():
    """The window is the caller's, and it is applied to the date the detector
    keys on rather than to the payable date."""
    broker = MockBroker(seed=1)
    broker.queue_announcement(_split(ex_date=date(2026, 11, 2)))

    assert await broker.announcements("SFBS", date(2026, 8, 1), date(2026, 9, 1)) == []
    assert len(await broker.announcements("SFBS", date(2026, 8, 1), date(2026, 12, 1))) == 1


@pytest.mark.asyncio
async def test_the_default_mock_announces_nothing():
    """A broker that invented corporate actions would make every other test in
    the suite non-deterministic."""
    assert await MockBroker(seed=1).announcements("AMD", date(2020, 1, 1), date(2030, 1, 1)) == []
