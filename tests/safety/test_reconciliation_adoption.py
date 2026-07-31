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


# --- Stops are learned from the broker at adoption (M31d) ---------------------


class _StopBroker(_Broker):
    """A broker that can answer what is actually resting."""

    def __init__(
        self,
        positions: dict[str, float] | None = None,
        resting: dict[str, float] | None = None,
    ) -> None:
        super().__init__(positions)
        self._resting = dict(resting or {})
        self.fail_resting = False
        self.resting_calls = 0

    async def resting_stops(self) -> dict[str, float]:
        self.resting_calls += 1
        if self.fail_resting:
            raise ConnectionError("broker unreachable")
        return dict(self._resting)


def _build_with_stops(positions: dict[str, float], resting: dict[str, float]):
    settings = Settings(_env_file=None)
    bus = EventBus()
    switch = KillSwitch()
    broker = _StopBroker(positions, resting)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch)
    return broker, oms


@pytest.mark.asyncio
async def test_adoption_learns_the_stops_actually_resting_at_the_broker():
    """The restart trap. _position_stops is in-memory, so before this every
    launch re-adopted its own positions as unprotected and the governor counted
    each at full value - which rejects every new buy before sizing runs."""
    _, oms = _build_with_stops({"AAPL": 50.0, "MSFT": 20.0}, {"AAPL": 95.0, "MSFT": 380.0})

    await oms.adopt_broker_positions()

    assert oms.position_stops() == {"AAPL": 95.0, "MSFT": 380.0}


@pytest.mark.asyncio
async def test_a_position_with_no_resting_stop_stays_off_the_record():
    """The conservative rule is unchanged - unknown protection is treated as no
    protection. What changed is that it is now reached by evidence."""
    _, oms = _build_with_stops({"AAPL": 50.0, "MSFT": 20.0}, {"AAPL": 95.0})

    await oms.adopt_broker_positions()

    assert oms.position_stops() == {"AAPL": 95.0}


@pytest.mark.asyncio
async def test_a_stop_resting_for_something_not_held_is_ignored():
    _, oms = _build_with_stops({"AAPL": 50.0}, {"AAPL": 95.0, "TSLA": 200.0})

    await oms.adopt_broker_positions()

    assert oms.position_stops() == {"AAPL": 95.0}


@pytest.mark.asyncio
async def test_a_broker_that_cannot_answer_is_not_read_as_an_unprotected_book():
    """_Broker has no resting_stops at all. Absence of the capability must not
    be acted on as if it were a naked account."""
    _, oms, _, _, _ = _build({"AAPL": 50.0})

    await oms.adopt_broker_positions()

    assert oms.position_stops() == {}


@pytest.mark.asyncio
async def test_a_failed_stop_query_does_not_stop_the_session_starting():
    broker, oms = _build_with_stops({"AAPL": 50.0}, {"AAPL": 95.0})
    broker.fail_resting = True

    adopted = await oms.adopt_broker_positions()

    assert adopted == {"AAPL": 50.0}
    assert oms.position_stops() == {}


@pytest.mark.asyncio
async def test_an_empty_account_never_asks_about_stops():
    broker, oms = _build_with_stops({}, {})

    await oms.adopt_broker_positions()

    assert broker.resting_calls == 0


@pytest.mark.asyncio
async def test_adopted_stops_make_the_verify_rail_able_to_see_a_lost_one():
    """verify_position_stops iterates _position_stops, so an empty record after
    a restart left it with nothing to check - exactly when an overnight bracket
    expiry is most likely to have happened."""
    broker, oms = _build_with_stops({"AAPL": 50.0}, {"AAPL": 95.0})
    await oms.adopt_broker_positions()

    broker._resting = {}
    lost = await oms.verify_position_stops()

    assert lost == ["AAPL"]
    assert oms.position_stops() == {}
