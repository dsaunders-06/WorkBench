"""The monitor end to end, including the two things it must not do (M39).

Shadow mode must place nothing, and a failed query must not mean acting blind:
the morning the announcements endpoint fails is exactly the morning it matters,
because the ex-date is the day the stop becomes lethal.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position, RestingStopOrder
from qat.domain.bus import EventBus
from qat.domain.corporate_actions.announcements import Announcement
from qat.domain.corporate_actions.monitor import CorporateActionMonitor
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _split(symbol: str = "MNST", ex_date: date = date(2026, 8, 11), ratio: float = 2.0):
    return Announcement(
        symbol=symbol,
        ex_date=ex_date,
        ratio=ratio,
        action_id="ca-1",
        payable_date=None,
        fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


class _Broker:
    """Holds MNST at the pre-split basis with its real resting stop."""

    def __init__(self, announcements: list[Announcement]) -> None:
        self._announcements = announcements
        self.modified: list[tuple[str, dict]] = []
        self.raise_on_announcements = False

    async def positions(self) -> list[Position]:
        return [Position(symbol="MNST", quantity=8.0, avg_price=91.1838)]

    async def resting_stops(self) -> dict[str, float]:
        return {"MNST": 72.68}

    async def resting_stop_orders(self) -> dict[str, RestingStopOrder]:
        return {
            "MNST": RestingStopOrder(
                symbol="MNST",
                order_id="34ffd4cd",
                stop_price=72.68,
                quantity=8.0,
            )
        }

    async def announcements(self, symbol, since, until):
        if self.raise_on_announcements:
            raise ConnectionError("broker unreachable")
        return [a for a in self._announcements if a.symbol == symbol]

    async def recent_fills(self, since, symbols=None):
        return []

    async def modify_order(self, order_id, **changes):
        self.modified.append((order_id, changes))
        return None

    async def get_market_data(self, symbol):
        return {"last": 46.30, "bid": 46.29, "ask": 46.31}


def _monitor(tmp_path, mode: str = "shadow", announcements=None, next_session=None):
    settings = Settings(_env_file=None, data_dir=str(tmp_path), corporate_action_mode=mode)
    bus = EventBus()
    switch = KillSwitch()
    broker = _Broker(announcements if announcements is not None else [_split()])
    oms = OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    monitor = CorporateActionMonitor(
        oms=oms,
        settings=settings,
        entries_source=lambda: {"MNST": datetime(2026, 8, 10, tzinfo=UTC)},
        # Pinned rather than read from the clock, so this test does not pass or
        # fail by the date the suite happens to run.
        next_session=lambda: next_session or date(2026, 8, 11),
    )
    return broker, monitor, oms


@pytest.mark.asyncio
async def test_shadow_mode_detects_and_places_nothing(tmp_path):
    broker, monitor, _oms = _monitor(tmp_path, "shadow")

    found = await monitor.refresh()

    assert [p.symbol for p in found] == ["MNST"]
    assert found[0].adjusted_stop == 36.34
    assert found[0].state == "shadowed"
    assert broker.modified == [], "shadow mode placed an order"


@pytest.mark.asyncio
async def test_the_pending_action_is_queryable_by_symbol(tmp_path):
    """R1 and R2 both rest on this being the single source of truth."""
    _broker, monitor, _oms = _monitor(tmp_path)
    await monitor.refresh()

    assert monitor.pending_action("MNST") is not None
    assert monitor.pending_action("AMD") is None
    assert [p.symbol for p in monitor.pending_actions()] == ["MNST"]


@pytest.mark.asyncio
async def test_a_failed_query_falls_back_to_what_was_persisted(tmp_path):
    """The morning the query fails is the morning it matters."""
    broker, monitor, _oms = _monitor(tmp_path)
    await monitor.refresh()

    broker.raise_on_announcements = True
    found = await monitor.refresh()

    assert [p.symbol for p in found] == ["MNST"]


@pytest.mark.asyncio
async def test_a_failed_query_on_a_cold_store_finds_nothing_and_says_so(tmp_path, caplog):
    broker, monitor, _oms = _monitor(tmp_path)
    broker.raise_on_announcements = True

    with caplog.at_level("WARNING"):
        found = await monitor.refresh()

    assert found == []
    assert "MNST" in caplog.text


@pytest.mark.asyncio
async def test_the_announcement_is_remembered_across_monitors(tmp_path):
    """Persistence is the point: a restart between sessions is the normal path."""
    _broker, monitor, _oms = _monitor(tmp_path)
    await monitor.refresh()

    _broker2, second, _oms2 = _monitor(tmp_path)

    assert second.store.for_symbol("MNST") != []


@pytest.mark.asyncio
async def test_act_mode_repricing_the_stop(tmp_path):
    broker, monitor, _oms = _monitor(tmp_path, "act")

    found = await monitor.refresh()

    assert found[0].state == "applied"
    assert broker.modified, "act mode placed nothing"
    assert broker.modified[0][1]["stop_price"] == 36.34


@pytest.mark.asyncio
async def test_a_refused_adjustment_quarantines_the_position(tmp_path):
    """Refusing leaves a stop that is itself dangerous, so the position must not
    keep trading as though nothing happened."""
    _broker, monitor, oms = _monitor(tmp_path, "act", announcements=[_split(ratio=0.5)])

    found = await monitor.refresh()

    assert found[0].state == "refused"
    assert oms.anomalies.is_quarantined("MNST")


@pytest.mark.asyncio
async def test_a_refused_adjustment_places_nothing(tmp_path):
    broker, monitor, _oms = _monitor(tmp_path, "act", announcements=[_split(ratio=0.5)])

    await monitor.refresh()

    assert broker.modified == []


@pytest.mark.asyncio
async def test_crwd_is_not_flagged_end_to_end(tmp_path):
    """The false positive that is in the live book, through the whole path."""
    _broker, monitor, _oms = _monitor(
        tmp_path,
        announcements=[_split(symbol="MNST", ex_date=date(2026, 7, 2), ratio=4.0)],
    )

    assert await monitor.refresh() == []


@pytest.mark.asyncio
async def test_an_unknown_next_session_refuses_rather_than_guessing(tmp_path):
    """next_open returns None when no trading day turns up in its search window.
    Guessing a session date would move a stop on the wrong day."""
    _broker, monitor, _oms = _monitor(tmp_path)
    monitor.next_session = lambda: None

    assert await monitor.refresh() == []


@pytest.mark.asyncio
async def test_a_new_announcement_is_announced_once_not_every_sweep(tmp_path, caplog):
    """A warning that fires every five minutes stops being read."""
    _broker, monitor, _oms = _monitor(tmp_path)

    with caplog.at_level("WARNING"):
        await monitor.refresh()
        first = caplog.text.count("first seen")
        await monitor.refresh()
        second = caplog.text.count("first seen")

    assert first == 1
    assert second == 1
