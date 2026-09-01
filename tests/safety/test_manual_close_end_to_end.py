"""Manual close, END TO END, against a REAL EventBus / AutonomousExecutor /
AutonomyGate / OMS in `execution_mode="auto"`.

⚠️ THIS IS THE TEST WHOSE ABSENCE COST TWO WHOLE-BRANCH REVIEWS.

Every other `PositionCloser` test hands the closer a hand-written `_FakeOms`.
That fake has no event bus, so an entire layer of the real system is invisible
to it:

* `OMS._announce_pending` publishes `OrderPendingSignoffEvent`, and
  `EventBus.publish` AWAITS its handlers - `asyncio.gather` on the handler
  coroutines - so a subscriber runs to completion INSIDE `submit_exit_order`.
* `AutonomousExecutor._on_pending` is subscribed from `start()`, and
  `AutonomyGate.evaluate` allows EVERY sell unconditionally ("risk-reducing
  orders are not gated on appetite limits"), and every protective stop
  unconditionally too (`order.is_protective_stop`, which outranks even the
  closed-session check).

So in auto mode the executor signs the exit off BEFORE `submit_exit_order`
returns. `PositionCloser`'s own `oms.sign_off(...)` then hits
`_sign_off_locked`'s "not pending sign-off" / already-`_transmitted` guards and
RAISES - over a sell that is in flight with the legs correctly gone. Nothing
with a `_FakeOms` in it can see that.

Nothing here is stubbed except the broker itself, which stands in for IBKR and
answers with IBKR's semantics: `place_order` returns a WORKING order
("transmitted"), never a synchronous fill.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position, RestingOrder
from qat.domain.autonomy.executor import AutonomousExecutor
from qat.domain.autonomy.gate import AutonomyGate
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal
from qat.domain.oms.oms import OMS
from qat.domain.oms.position_closer import CloseOutcome, PositionCloser
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_NY = ZoneInfo("America/New_York")
# Inside a regular US session, so the gate's `session.is_open` check passes for
# the market sell. A protective stop does not need it (M33c).
OPEN_US = datetime(2026, 7, 23, 10, 30, tzinfo=_NY)

SYMBOL = "AAPL"


class _Entry:
    """What `runtime._LiveEntries` hands the closer: an entry basis."""

    def __init__(self, price: float = 100.0) -> None:
        self.price = price


class _IbkrLikeBroker:
    """IBKR's semantics, not MockBroker's.

    ⚠️ `place_order` returns "transmitted", NOT "filled". `MockBroker` fills
    synchronously and that is the only reason a `!= "filled"` test ever looked
    correct. `ib_translate._IB_STATUS_MAP` maps Submitted/PreSubmitted/
    PendingSubmit/ApiPending/PendingCancel ALL to "transmitted".
    """

    def __init__(
        self,
        *,
        quantity: float = 100.0,
        reject_market_sell: bool = False,
        reject_protective: bool = False,
        extra_resting: tuple[RestingOrder, ...] = (),
    ) -> None:
        self.quantity = quantity
        self.reject_market_sell = reject_market_sell
        self.reject_protective = reject_protective
        self.resting: dict[str, RestingOrder] = {
            "leg-stp": RestingOrder(
                symbol=SYMBOL,
                order_id="leg-stp",
                side="sell",
                order_type="STP",
                quantity=quantity,
                status="Submitted",
                oca_group="oca-1",
                stop_price=90.0,
            ),
            "leg-lmt": RestingOrder(
                symbol=SYMBOL,
                order_id="leg-lmt",
                side="sell",
                order_type="LMT",
                quantity=quantity,
                status="Submitted",
                oca_group="oca-1",
                limit_price=110.0,
            ),
        }
        for order in extra_resting:
            self.resting[order.order_id] = order
        self.placed: list[Order] = []
        self.cancelled: list[str] = []

    async def open_orders(self) -> list[RestingOrder]:
        return list(self.resting.values())

    async def cancel_order(self, order_id: str) -> Order:
        self.cancelled.append(order_id)
        self.resting.pop(order_id, None)
        return Order(symbol=SYMBOL, side="sell", quantity=0.0, order_id=order_id)

    async def place_order(self, order: Order) -> Order:
        is_protective = order.order_type == "stop"
        if is_protective and self.reject_protective:
            raise RuntimeError("broker refused the protective stop")
        if not is_protective and self.reject_market_sell:
            raise RuntimeError("broker refused the market sell")
        self.placed.append(order)
        # The broker's own answer, mapped by the adapter. A working order, not
        # an execution.
        order.status = "transmitted"
        self.resting[order.order_id] = RestingOrder(
            symbol=order.symbol,
            order_id=order.order_id,
            side=order.side,
            order_type="STP" if is_protective else "MKT",
            quantity=order.quantity,
            status="Submitted",
            stop_price=order.stop_price,
            limit_price=order.take_profit_price,
        )
        return order

    async def positions(self) -> list[Position]:
        if self.quantity == 0:
            return []
        return [Position(symbol=SYMBOL, quantity=self.quantity, avg_price=100.0)]

    async def account(self) -> AccountSummary:
        return AccountSummary(net_liquidation=100_000.0, cash=100_000.0, buying_power=100_000.0)

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        return {"last": 100.0, "ask": 100.0}

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        raise NotImplementedError

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        raise NotImplementedError


class _Wiring:
    def __init__(self, broker, oms, gate, executor, journal, kill_switch, closer) -> None:
        self.broker = broker
        self.oms = oms
        self.gate = gate
        self.executor = executor
        self.journal = journal
        self.kill_switch = kill_switch
        self.closer = closer


def _wire(tmp_path, broker: _IbkrLikeBroker, *, execution_mode: str = "auto") -> _Wiring:
    """Every component real except the broker. No `_FakeOms` anywhere."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        execution_mode=execution_mode,
        autonomous_strategies="swing",
        data_dir=str(tmp_path),
    )
    bus = EventBus()
    kill_switch = KillSwitch()
    risk_engine = RiskEngine(bus, kill_switch, settings=settings)
    oms = OMS(broker, risk_engine, kill_switch, max_order_pct_of_cash=1.0, bus=bus)
    gate = AutonomyGate(settings, kill_switch, clock=lambda: OPEN_US)
    journal = DecisionJournal(tmp_path)
    executor = AutonomousExecutor(bus, oms, gate, journal, settings=settings)
    closer = PositionCloser(oms, broker, kill_switch, {SYMBOL: _Entry()})
    return _Wiring(broker, oms, gate, executor, journal, kill_switch, closer)


@pytest.fixture
async def auto_mode(tmp_path):
    """Auto mode with the executor genuinely subscribed to the bus."""

    async def build(broker: _IbkrLikeBroker, execution_mode: str = "auto") -> _Wiring:
        wiring = _wire(tmp_path, broker, execution_mode=execution_mode)
        await wiring.executor.start()
        built.append(wiring)
        return wiring

    built: list[_Wiring] = []
    try:
        yield build
    finally:
        for wiring in built:
            await wiring.executor.stop()


# --- the sell ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_close_in_auto_mode_reaches_CLOSED(auto_mode):
    """⚠️ THE ONE THAT MATTERS.

    Auto mode, real bus, real executor, real gate. The executor signs the exit
    off inside `submit_exit_order`, so the closer's own `sign_off` raises. An
    order ALREADY signed off is a SUCCESS - the legs are gone and the sell is
    in flight - and reporting it as a failure told the operator the position
    was "held with NO STOP" over a sell that was working perfectly.
    """
    broker = _IbkrLikeBroker()
    wiring = await auto_mode(broker)

    result = await wiring.closer.close_position(SYMBOL, operator="operator (dashboard)")

    assert result.outcome is CloseOutcome.CLOSED, result.detail
    assert result.quantity == 100.0
    assert sorted(result.cancelled_legs) == ["leg-lmt", "leg-stp"]
    assert sorted(broker.cancelled) == ["leg-lmt", "leg-stp"]


@pytest.mark.asyncio
async def test_autonomy_signs_the_exit_off_inside_submit_exit_order(auto_mode):
    """The mechanism itself, pinned so the fix cannot be mistaken for a
    workaround for something else. If this ever stops being true the
    ValueError branch below becomes dead code and should be revisited - it is
    NOT a defensive `except` around an impossible case."""
    broker = _IbkrLikeBroker()
    wiring = await auto_mode(broker)

    order = await wiring.oms.submit_exit_order(SYMBOL, 100.0, 100.0, reason="manual_close")

    assert order.status == "transmitted", "the executor signed it off before this returned"
    assert order.order_id in wiring.oms._transmitted


@pytest.mark.asyncio
async def test_exactly_one_sell_reaches_the_broker(auto_mode):
    """M139: the account held 4x the intended position because one order was
    sent more than once. Autonomy signing off and the closer signing off must
    not become two transmissions of the same sell - nor two sells."""
    broker = _IbkrLikeBroker()
    wiring = await auto_mode(broker)

    await wiring.closer.close_position(SYMBOL, operator="operator (dashboard)")

    market_sells = [o for o in broker.placed if o.side == "sell" and o.order_type != "stop"]
    assert len(market_sells) == 1, f"one sell, not {len(market_sells)}"


@pytest.mark.asyncio
async def test_no_bracket_is_re_armed_over_the_in_flight_sell(auto_mode):
    """The SHORT trap from the other side. A full-size protective sell placed
    on top of a working full-size market sell is orphaned the moment the sell
    fills."""
    broker = _IbkrLikeBroker()
    wiring = await auto_mode(broker)

    await wiring.closer.close_position(SYMBOL, operator="operator (dashboard)")

    assert [o for o in broker.placed if o.order_type == "stop"] == []


@pytest.mark.asyncio
async def test_the_detail_never_says_the_close_failed_over_a_working_sell(auto_mode):
    """The operator-facing half of the defect. `_recover` reported UNPROTECTED
    and "re-place it by hand now" over a live bracket; an operator obeying
    that hand-places a SECOND full-size protective sell."""
    broker = _IbkrLikeBroker()
    wiring = await auto_mode(broker)

    result = await wiring.closer.close_position(SYMBOL, operator="operator (dashboard)")

    lowered = result.detail.lower()
    assert "no stop" not in lowered
    assert "by hand" not in lowered
    assert "failed" not in lowered


@pytest.mark.asyncio
async def test_recommend_mode_still_closes_the_position(auto_mode):
    """The same path with autonomy OFF - the closer signs off itself, exactly
    as it always did. The fix must not depend on autonomy being on."""
    broker = _IbkrLikeBroker()
    wiring = await auto_mode(broker, execution_mode="recommend")

    result = await wiring.closer.close_position(SYMBOL, operator="operator (dashboard)")

    assert result.outcome is CloseOutcome.CLOSED, result.detail
    assert result.quantity == 100.0


# --- the recovery path, under the same wiring ---------------------------


@pytest.mark.asyncio
async def test_recovery_re_places_the_bracket_in_auto_mode(auto_mode):
    """Same defect, second site. `submit_protective_stop` also announces on
    the bus, and the gate allows EVERY protective stop (`is_protective_stop`
    outranks even the closed-session check), so the executor places the
    bracket before `_recover` gets to sign it off. `_recover`'s own
    `sign_off` then raised into the broad `except Exception` and reported
    UNPROTECTED - "re-place it by hand now" - over a bracket that IS live.
    """
    broker = _IbkrLikeBroker(reject_market_sell=True)
    wiring = await auto_mode(broker)

    result = await wiring.closer.close_position(SYMBOL, operator="operator (dashboard)")

    assert result.outcome is CloseOutcome.RECOVERED, result.detail
    protective = [o for o in broker.placed if o.order_type == "stop"]
    assert len(protective) == 1, "the bracket goes back exactly once"
    assert protective[0].stop_price == 90.0
    assert protective[0].take_profit_price == 110.0
    assert "by hand" not in result.detail.lower()


@pytest.mark.asyncio
async def test_a_genuinely_failed_re_place_is_still_UNPROTECTED(auto_mode, caplog):
    """The fix must not turn every sign-off ValueError into a success. When
    the broker refuses the bracket as well, the position really is bare and
    the loudest branch in the file must still fire."""
    broker = _IbkrLikeBroker(reject_market_sell=True, reject_protective=True)
    wiring = await auto_mode(broker)

    result = await wiring.closer.close_position(SYMBOL, operator="operator (dashboard)")

    assert result.outcome is CloseOutcome.UNPROTECTED, result.detail
    assert "NO STOP" in result.detail
    assert any(r.levelname == "CRITICAL" for r in caplog.records)
