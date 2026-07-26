"""Broker reconciliation, adopted and actually running (spec M15).

Two failures this guards against, both real:

* `check_reconciliation` existed since M6 and was called from nowhere in
  `src/` - a reconciliation capability, not a reconciliation check.
* Once it *is* called, an OMS that has filled nothing compared against an
  account already holding positions reports a mismatch on the first poll and
  trips the kill-switch at startup, every time. A rail that cries wolf on
  every launch trains an operator to ignore the one signal that means "my view
  of this account cannot be trusted".
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position
from qat.domain.bus import EventBus
from qat.domain.events import KillSwitchEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.reconciliation import ReconciliationMonitor
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _Broker:
    def __init__(self, positions: dict[str, float] | None = None) -> None:
        self._positions = dict(positions or {})
        self.fail_positions = False

    async def positions(self) -> list[Position]:
        if self.fail_positions:
            raise ConnectionError("broker unreachable")
        return [
            Position(symbol=sym, quantity=qty, avg_price=100.0)
            for sym, qty in self._positions.items()
        ]

    async def account(self) -> AccountSummary:
        return AccountSummary(net_liquidation=100_000.0, cash=50_000.0, buying_power=50_000.0)

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        raise NotImplementedError

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        raise NotImplementedError

    async def place_order(self, order: Order) -> Order:
        raise NotImplementedError

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> Order:
        raise NotImplementedError


def _build(positions: dict[str, float] | None = None):
    settings = Settings(_env_file=None)
    bus = EventBus()
    switch = KillSwitch()
    broker = _Broker(positions)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch)
    monitor = ReconciliationMonitor(oms, settings=settings, bus=bus, poll_seconds=3600.0)
    return broker, oms, switch, bus, monitor


# --- Adoption -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_existing_positions_are_adopted_not_flagged():
    """The Alpaca-paper-account case: holdings from a previous session, or from
    the original ShareTrader app, are a normal starting state."""
    broker, oms, switch, _, monitor = _build({"AAPL": 50.0, "MSFT": 20.0})

    await monitor.start()
    await monitor.stop()

    assert oms.adopted_baseline == {"AAPL": 50.0, "MSFT": 20.0}
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_reconciliation_is_clean_immediately_after_adoption():
    broker, oms, switch, _, monitor = _build({"AAPL": 50.0})
    await monitor.start()

    assert await monitor.poll() is False
    assert switch.tripped is False

    await monitor.stop()


@pytest.mark.asyncio
async def test_an_empty_account_adopts_nothing_and_stays_clean():
    broker, oms, switch, _, monitor = _build({})
    await monitor.start()

    assert oms.adopted_baseline == {}
    assert await monitor.poll() is False

    await monitor.stop()


@pytest.mark.asyncio
async def test_adopted_positions_carry_no_stop():
    """This app did not open them and has no idea what protects them. The
    governor therefore counts their whole value as at risk, which is the
    conservative reading rather than an oversight."""
    broker, oms, _, _, monitor = _build({"AAPL": 50.0})
    await monitor.start()
    await monitor.stop()

    assert oms.position_stops() == {}


# --- Detection ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_divergence_after_adoption_is_detected():
    """The signal that still has to work: something moved the account that this
    app did not do."""
    broker, oms, switch, _, monitor = _build({"AAPL": 50.0})
    await monitor.start()

    broker._positions["AAPL"] = 80.0  # filled elsewhere
    mismatch = await monitor.poll()

    assert mismatch is True
    assert switch.tripped is True
    assert "reconciliation" in (switch.reason or "").lower()

    await monitor.stop()


@pytest.mark.asyncio
async def test_a_position_vanishing_is_detected():
    broker, oms, switch, _, monitor = _build({"AAPL": 50.0})
    await monitor.start()

    broker._positions.clear()  # liquidated outside this app

    assert await monitor.poll() is True
    assert switch.tripped is True

    await monitor.stop()


@pytest.mark.asyncio
async def test_a_mismatch_publishes_an_event_so_the_ui_learns_about_it():
    """KillSwitch.trip() publishes nothing on its own, so without this the halt
    would be real but invisible - the same gap the equity rails had."""
    broker, oms, _, bus, monitor = _build({"AAPL": 50.0})
    seen: list[KillSwitchEvent] = []

    async def _capture(event: KillSwitchEvent) -> None:
        seen.append(event)

    bus.subscribe(KillSwitchEvent, _capture)
    await monitor.start()

    broker._positions["AAPL"] = 80.0
    await monitor.poll()

    assert len(seen) == 1
    assert seen[0].triggered_by == monitor.name

    # Still tripped on the next poll: it must not re-announce every interval.
    await monitor.poll()
    assert len(seen) == 1

    await monitor.stop()


# --- Failure behaviour --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_broker_failure_at_startup_does_not_block_the_app():
    broker, oms, switch, _, monitor = _build({"AAPL": 50.0})
    broker.fail_positions = True

    await monitor.start()

    assert monitor.adopted == {}
    assert switch.tripped is False

    await monitor.stop()


@pytest.mark.asyncio
async def test_adoption_is_recorded_in_the_log(caplog):
    """Silently absorbing an unexpected position is exactly the event
    reconciliation exists to catch, so adoption has to be on the record."""
    broker, oms, _, _, monitor = _build({"AAPL": 50.0})

    with caplog.at_level("INFO"):
        await monitor.start()
        await monitor.stop()

    assert "Adopted 1 pre-existing broker position" in caplog.text
    assert "AAPL" in caplog.text
