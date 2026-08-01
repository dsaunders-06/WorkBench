"""Re-arming a position whose protective stop is gone (M31d).

Every stop this system placed before M31d rode in as a bracket leg on an
entry, so there was no way to put one back on a position already held. On
1 August all six holdings were in exactly that state: the entries filled with
brackets attached, the take-profit legs expired at Friday's close, and Alpaca
cancelled the paired stops with them as OCO does.

The two failures guarded here are both ways a "protective" order could make
things worse than the exposure it was sent to fix:

* Submitted as a market sell, it liquidates the position it was meant to
  protect.
* Counted as a fill, it halves the tracked quantity against a broker that
  still holds the whole position - and reconciliation reads that as a
  discrepancy and trips the kill-switch.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _Broker(MockBroker):
    """A broker holding positions with nothing resting against them."""

    def __init__(self, held: dict[str, float], resting: dict[str, float] | None = None) -> None:
        super().__init__(seed=1)
        self._held = dict(held)
        self._resting_stops = dict(resting or {})
        self.submitted: list[Order] = []

    async def positions(self) -> list[Position]:
        return [
            Position(symbol=sym, quantity=qty, avg_price=100.0) for sym, qty in self._held.items()
        ]

    async def place_order(self, order: Order) -> Order:
        self.submitted.append(order)
        return await super().place_order(order)


def _oms(held: dict[str, float], resting: dict[str, float] | None = None):
    settings = Settings(_env_file=None)
    switch = KillSwitch()
    broker = _Broker(held, resting)
    return broker, OMS(broker, RiskEngine(EventBus(), switch, settings=settings), switch)


@pytest.mark.asyncio
async def test_naked_positions_are_found_from_the_account_not_from_memory():
    _, oms = _oms({"AAPL": 50.0, "MSFT": 20.0}, {"MSFT": 380.0})

    assert await oms.naked_positions() == [("AAPL", 50.0)]


@pytest.mark.asyncio
async def test_a_protective_stop_is_proposed_not_transmitted():
    """The gate holds even for an order that only reduces risk."""
    broker, oms = _oms({"AAPL": 50.0})

    order = await oms.submit_protective_stop("AAPL", 50.0, 95.0)

    assert order.status == "pending_signoff"
    assert broker.submitted == []


@pytest.mark.asyncio
async def test_a_signed_off_stop_rests_rather_than_selling():
    broker, oms = _oms({"AAPL": 50.0})
    order = await oms.submit_protective_stop("AAPL", 50.0, 95.0)

    signed = await oms.sign_off(order.order_id, "operator")

    assert signed.status == "transmitted"
    assert signed.filled_price is None
    assert await broker.resting_stops() == {"AAPL": 95.0}


@pytest.mark.asyncio
async def test_a_resting_stop_does_not_move_the_tracked_quantity():
    """Counted as a sell, this halves the tracked position against a broker
    that still holds all of it - and reconciliation trips the kill-switch on
    the very order sent to make the book safer."""
    _, oms = _oms({"AAPL": 50.0})
    await oms.adopt_broker_positions()
    order = await oms.submit_protective_stop("AAPL", 50.0, 95.0)

    await oms.sign_off(order.order_id, "operator")

    assert await oms.check_reconciliation() is False
    assert oms.kill_switch.tripped is False


@pytest.mark.asyncio
async def test_signing_off_records_the_protection():
    _, oms = _oms({"AAPL": 50.0})
    order = await oms.submit_protective_stop("AAPL", 50.0, 95.0)

    await oms.sign_off(order.order_id, "operator")

    assert oms.position_stops() == {"AAPL": 95.0}


@pytest.mark.asyncio
async def test_a_stop_order_is_never_treated_as_a_bracket():
    """is_bracket drives the bracket branch at the broker, and Alpaca rejects
    a bracket that has no entry to attach to."""
    order = Order(
        symbol="AAPL",
        side="sell",
        quantity=50.0,
        order_id="x",
        stop_price=95.0,
        order_type="stop",
    )

    assert order.is_bracket is False
    assert order.is_protective_stop is True


@pytest.mark.asyncio
async def test_a_nonsense_stop_is_refused():
    _, oms = _oms({"AAPL": 50.0})

    assert (await oms.submit_protective_stop("AAPL", 0.0, 95.0)).status == "rejected"
    assert (await oms.submit_protective_stop("AAPL", 50.0, 0.0)).status == "rejected"


# --- The startup trigger ------------------------------------------------------


import json  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import replace  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from qat.domain.oms.signal_bridge import SignalToOrderBridge  # noqa: E402


def _bridge_holding(held: dict[str, float], entries: dict[str, dict]):
    """A bridge whose entry file already knows the stops, as it does after a
    restart - which is the only situation this runs in."""
    data_dir = tempfile.mkdtemp()
    (Path(data_dir) / "open_position_entries.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )
    settings = Settings(_env_file=None, data_dir=data_dir)
    bus = EventBus()
    switch = KillSwitch()
    broker = _Broker(held)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    return broker, oms, SignalToOrderBridge(bus, oms, settings=settings)


def _entry(stop: float, price: float = 100.0) -> dict:
    return {
        "opened_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        "price": price,
        "stop_price": stop,
    }


@pytest.mark.asyncio
async def test_startup_proposes_a_stop_for_every_unprotected_position():
    """The 1 August state: six held, none protected, every entry stop known."""
    _, oms, bridge = _bridge_holding(
        {"CRWD": 16.0, "CSCO": 44.0}, {"CRWD": _entry(163.32), "CSCO": _entry(105.56)}
    )

    proposed = await bridge.rearm_protective_stops()

    assert sorted(proposed) == ["CRWD", "CSCO"]
    pending = {o.symbol: o for o in oms.pending_orders()}
    assert pending["CRWD"].stop_price == pytest.approx(163.32)
    assert pending["CSCO"].stop_price == pytest.approx(105.56)
    assert all(o.order_type == "stop" for o in pending.values())


@pytest.mark.asyncio
async def test_a_position_already_protected_is_left_alone():
    broker, _, bridge = _bridge_holding({"CRWD": 16.0}, {"CRWD": _entry(163.32)})
    broker._resting_stops = {"CRWD": 163.32}

    assert await bridge.rearm_protective_stops() == []


@pytest.mark.asyncio
async def test_re_arming_uses_the_stop_the_position_was_sized_against():
    """Not a level recomputed now. The risk budget was spent on the entry stop,
    so protecting at any other distance protects an amount nobody approved."""
    _, oms, bridge = _bridge_holding({"CRWD": 16.0}, {"CRWD": _entry(163.32, price=187.28)})

    await bridge.rearm_protective_stops()

    assert oms.pending_orders()[0].stop_price == pytest.approx(163.32)


@pytest.mark.asyncio
async def test_no_stop_is_invented_when_the_entry_is_unknown():
    """An invented level would look identical to a real one on every screen."""
    _, oms, bridge = _bridge_holding({"CRWD": 16.0}, {})

    assert await bridge.rearm_protective_stops() == []
    assert oms.pending_orders() == []


@pytest.mark.asyncio
async def test_a_broker_that_cannot_be_reached_does_not_stop_the_session():
    _, oms, bridge = _bridge_holding({"CRWD": 16.0}, {"CRWD": _entry(163.32)})

    async def _fail() -> list[tuple[str, float]]:
        raise ConnectionError("broker unreachable")

    oms.naked_positions = _fail  # type: ignore[method-assign]

    assert await bridge.rearm_protective_stops() == []


# --- The target comes back too (M33) -----------------------------------------


@pytest.mark.asyncio
async def test_a_re_armed_position_gets_its_target_back_as_one_oco():
    """The first re-arm restored only the stop, because the entry record was
    the one place the target was never written down. Six positions came back
    with downside protection and no way to bank a gain: the only exits left
    were a stop-out or the 30-day time stop."""
    broker, oms = _oms({"AAPL": 50.0})

    order = await oms.submit_protective_stop("AAPL", 50.0, 95.0, 130.0)
    signed = await oms.sign_off(order.order_id, "operator")

    assert signed.stop_price == pytest.approx(95.0)
    assert signed.take_profit_price == pytest.approx(130.0)
    assert await broker.resting_stops() == {"AAPL": 95.0}
    assert broker.resting_target("AAPL") == pytest.approx(130.0)


@pytest.mark.asyncio
async def test_a_stop_and_a_target_are_one_order_not_two():
    """Two independent resting orders for the same shares can BOTH fill - the
    price runs to the target, later gaps back through the stop - and the
    account sells twice what it holds, turning a protected long into an
    accidental short. OCO is what makes them mutually exclusive."""
    broker, oms = _oms({"AAPL": 50.0})

    order = await oms.submit_protective_stop("AAPL", 50.0, 95.0, 130.0)
    await oms.sign_off(order.order_id, "operator")

    assert len(broker.submitted) == 1
    assert broker.submitted[0].quantity == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_a_position_with_no_recorded_target_still_gets_its_stop():
    """Every position opened before M33 has a stop on record and no target.
    Half the protection is worth having."""
    broker, oms = _oms({"AAPL": 50.0})

    order = await oms.submit_protective_stop("AAPL", 50.0, 95.0)
    await oms.sign_off(order.order_id, "operator")

    assert await broker.resting_stops() == {"AAPL": 95.0}
    assert broker.resting_target("AAPL") is None


@pytest.mark.asyncio
async def test_startup_re_arms_both_levels_when_both_are_known():
    _, oms, bridge = _bridge_holding({"CRWD": 16.0}, {"CRWD": _entry(163.32)})
    bridge._entries["CRWD"] = replace(bridge._entries["CRWD"], target_price=235.20)

    await bridge.rearm_protective_stops()

    proposed = oms.pending_orders()[0]
    assert proposed.stop_price == pytest.approx(163.32)
    assert proposed.take_profit_price == pytest.approx(235.20)


# --- Never two protective orders for one symbol (M33d) ------------------------


@pytest.mark.asyncio
async def test_a_second_protective_order_is_not_proposed_while_one_is_pending():
    """Belt and braces against the detection query being wrong, which it was.
    An OCO's stop leg rests at `held` and nested under its parent, so a CRWD
    position carrying a good OCO read as unprotected and a second was
    proposed - 32 shares of resting sell orders against 16 held."""
    _, oms = _oms({"CRWD": 16.0})

    first = await oms.submit_protective_stop("CRWD", 16.0, 163.32, 235.20)
    second = await oms.submit_protective_stop("CRWD", 16.0, 163.32, 235.20)

    assert second.order_id == first.order_id
    assert len([o for o in oms.pending_orders() if o.is_protective_stop]) == 1


@pytest.mark.asyncio
async def test_a_different_symbol_is_still_proposed():
    _, oms = _oms({"CRWD": 16.0, "CSCO": 44.0})

    await oms.submit_protective_stop("CRWD", 16.0, 163.32)
    await oms.submit_protective_stop("CSCO", 44.0, 105.56)

    assert len([o for o in oms.pending_orders() if o.is_protective_stop]) == 2


@pytest.mark.asyncio
async def test_a_new_protective_order_is_allowed_once_the_pending_one_is_gone():
    """The guard is about DUPLICATES, not a one-shot latch. Once the pending
    order has been signed off or rejected, a genuinely unprotected position
    must be able to get another."""
    _, oms = _oms({"CRWD": 16.0})
    first = await oms.submit_protective_stop("CRWD", 16.0, 163.32)
    await oms.sign_off(first.order_id, "operator")

    second = await oms.submit_protective_stop("CRWD", 16.0, 163.32)

    assert second.order_id != first.order_id
    assert second.status == "pending_signoff"


# --- Repair on a timer, not only at startup (M33e) ----------------------------


@pytest.mark.asyncio
async def test_the_sweep_re_arms_without_a_restart():
    """Every repair watched on 1 August needed a human to close and reopen the
    app. A stop that vanishes at 14:00 is not less urgent than one found at
    launch - it is more so, because nobody is about to restart anything."""
    broker, oms, bridge = _bridge_holding({"CRWD": 16.0}, {"CRWD": _entry(163.32)})
    broker._resting_stops = {"CRWD": 163.32}

    # Nothing to do while the stop is there.
    assert await bridge.rearm_protective_stops() == []

    # It vanishes mid-session, exactly as the brackets did at Friday's close.
    broker._resting_stops = {}

    assert await bridge.rearm_protective_stops() == ["CRWD"]
    assert oms.pending_orders()[0].symbol == "CRWD"


@pytest.mark.asyncio
async def test_a_repeated_sweep_does_not_stack_up_orders():
    """The sweep runs every few minutes forever, so it must be idempotent while
    a proposal is still awaiting sign-off. The M33d duplicate guard is what
    makes that true."""
    _, oms, bridge = _bridge_holding({"CRWD": 16.0}, {"CRWD": _entry(163.32)})

    for _ in range(5):
        await bridge.rearm_protective_stops()

    assert len([o for o in oms.pending_orders() if o.is_protective_stop]) == 1


@pytest.mark.asyncio
async def test_the_sweep_starts_and_stops_with_the_bridge():
    _, _, bridge = _bridge_holding({}, {})

    await bridge.start()
    assert bridge._sweep_task is not None and not bridge._sweep_task.done()

    await bridge.stop()
    assert bridge._sweep_task is None
