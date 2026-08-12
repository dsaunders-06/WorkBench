"""When the shares actually arrive (M39, Phase 2).

**Never exercised against a real event.** MNST's stop closed the position before
the share side landed - quantity went 8 to 0, never 8 to 16 - so every
expectation here is built from the announcement's arithmetic rather than from an
observation. That is exactly why the ledger correction is logged and not applied.

What this DOES do is protect the whole holding. Eight shares of protection
against sixteen held leaves half the position naked, and that is a certainty
rather than a guess.
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


class _DeliveredBroker:
    """The broker now reports MORE shares than the app tracks."""

    def __init__(self, broker_quantity: float, ratio: float) -> None:
        self.broker_quantity = broker_quantity
        self.ratio = ratio
        self.modified: list[tuple[str, dict]] = []

    async def positions(self) -> list[Position]:
        return [Position(symbol="MNST", quantity=self.broker_quantity, avg_price=45.59)]

    async def resting_stops(self) -> dict[str, float]:
        return {"MNST": 36.34}

    async def resting_stop_orders(self) -> dict[str, RestingStopOrder]:
        return {
            "MNST": RestingStopOrder(
                symbol="MNST", order_id="34ffd4cd", stop_price=36.34, quantity=8.0
            )
        }

    async def announcements(self, symbol, since, until):
        return [
            Announcement(
                symbol="MNST",
                ex_date=date(2026, 8, 11),
                ratio=self.ratio,
                action_id="ca-1",
                payable_date=None,
                fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
            )
        ]

    async def recent_fills(self, since, symbols=None):
        return []

    async def modify_order(self, order_id, **changes):
        self.modified.append((order_id, changes))
        return None

    async def get_market_data(self, symbol):
        return {"last": 46.30}


async def _with_delivered_shares(tmp_path, broker: float, ratio: float, mode: str = "act"):
    settings = Settings(_env_file=None, data_dir=str(tmp_path), corporate_action_mode=mode)
    bus = EventBus()
    switch = KillSwitch()
    adapter = _DeliveredBroker(broker, ratio)
    oms = OMS(
        adapter,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    monitor = CorporateActionMonitor(
        oms=oms,
        settings=settings,
        entries_source=lambda: {"MNST": datetime(2026, 8, 10, tzinfo=UTC)},
        next_session=lambda: date(2026, 8, 11),
    )
    # The announcement has to be known before the delivery can be explained by
    # it, which is the real sequence: the announcement arrives days earlier.
    await monitor.refresh()
    # That priming pass is SETUP, and in act mode it re-prices the stop. Cleared
    # so every assertion below is about reconcile_observed rather than about
    # what Phase 1 already did.
    adapter.modified.clear()
    return monitor, oms, adapter


@pytest.mark.asyncio
async def test_a_doubling_that_matches_the_ratio_is_declared_explained(tmp_path):
    monitor, oms, _adapter = await _with_delivered_shares(tmp_path, broker=16.0, ratio=2.0)

    acted = await monitor.reconcile_observed({"MNST": 8.0})

    assert acted == ["MNST"]
    assert oms.anomalies.is_quarantined("MNST")
    assert oms.anomalies.explains("MNST", 16.0)


@pytest.mark.asyncio
async def test_a_change_that_does_not_match_the_ratio_is_left_to_the_kill_switch(tmp_path):
    """8 to 17 is not a 2-for-1. Declaring it explained would grant immunity to
    a genuine divergence, which is the failure M60's binding exists to stop."""
    monitor, oms, _adapter = await _with_delivered_shares(tmp_path, broker=17.0, ratio=2.0)

    acted = await monitor.reconcile_observed({"MNST": 8.0})

    assert acted == []
    assert not oms.anomalies.is_quarantined("MNST")


@pytest.mark.asyncio
async def test_the_stop_quantity_is_raised_to_cover_the_whole_holding(tmp_path):
    """Eight shares of protection against sixteen held leaves half the position
    naked. This is the one part of Phase 2 that is a certainty, not a guess."""
    monitor, _oms, adapter = await _with_delivered_shares(tmp_path, broker=16.0, ratio=2.0)

    await monitor.reconcile_observed({"MNST": 8.0})

    assert adapter.modified, "the resting stop's quantity was never raised"
    assert adapter.modified[-1][1]["quantity"] == 16.0


@pytest.mark.asyncio
async def test_the_ledger_basis_correction_is_logged_and_not_applied(tmp_path, caplog):
    """The deliberate boundary. Zero observations of this path, so the record
    rewrite stays manual as the CVS and MNST corrections were."""
    monitor, _oms, _adapter = await _with_delivered_shares(tmp_path, broker=16.0, ratio=2.0)

    with caplog.at_level("WARNING"):
        await monitor.reconcile_observed({"MNST": 8.0})

    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "NOT been applied" in messages
    assert "45.59" in messages, "the correction it would make is not stated"


@pytest.mark.asyncio
async def test_no_quantity_change_does_nothing_at_all(tmp_path):
    """The ordinary case, every sweep, on every held position."""
    monitor, oms, adapter = await _with_delivered_shares(tmp_path, broker=8.0, ratio=2.0)

    acted = await monitor.reconcile_observed({"MNST": 8.0})

    assert acted == []
    assert adapter.modified == []
    assert not oms.anomalies.is_quarantined("MNST")


@pytest.mark.asyncio
async def test_shadow_mode_declares_but_places_nothing(tmp_path):
    """Shadow still records the anomaly - containment is not an order - but it
    modifies no protective order."""
    monitor, oms, adapter = await _with_delivered_shares(
        tmp_path, broker=16.0, ratio=2.0, mode="shadow"
    )

    acted = await monitor.reconcile_observed({"MNST": 8.0})

    assert acted == ["MNST"]
    assert oms.anomalies.is_quarantined("MNST")
    assert adapter.modified == []


@pytest.mark.asyncio
async def test_a_reverse_split_halving_the_count_is_explained_too(tmp_path):
    """1-for-2: 8 becomes 4. The same arithmetic in the other direction."""
    monitor, oms, _adapter = await _with_delivered_shares(tmp_path, broker=4.0, ratio=0.5)

    acted = await monitor.reconcile_observed({"MNST": 8.0})

    assert acted == ["MNST"]
    assert oms.anomalies.explains("MNST", 4.0)


@pytest.mark.asyncio
async def test_a_symbol_with_no_announcement_is_not_explained(tmp_path):
    """A quantity change nothing accounts for must reach reconciliation and the
    kill-switch, which is the whole point of not explaining it."""
    monitor, oms, _adapter = await _with_delivered_shares(tmp_path, broker=16.0, ratio=2.0)

    acted = await monitor.reconcile_observed({"AMD": 7.0})

    assert acted == []
    assert not oms.anomalies.is_quarantined("AMD")
