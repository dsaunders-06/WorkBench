from dataclasses import dataclass

import pytest

from qat.data.broker.adapter import Order, Position, RestingOrder
from qat.domain.oms.position_closer import CloseOutcome, PositionCloser


def _leg(symbol, order_id, order_type, *, stop=None, limit=None, status="Submitted"):
    return RestingOrder(
        symbol=symbol,
        order_id=order_id,
        side="sell",
        order_type=order_type,
        quantity=100.0,
        status=status,
        oca_group="oca-1",
        stop_price=stop,
        limit_price=limit,
    )


@dataclass
class _Entry:
    price: float = 100.0


class _FakeBroker:
    def __init__(self, positions, legs, legs_after_cancel, positions_after_cancel, cancel_raises):
        self._positions = positions
        self._positions_after = positions_after_cancel
        self._legs = legs
        self._legs_after = legs_after_cancel
        self._cancel_raises = cancel_raises
        self.open_orders_calls = 0
        self._cancelled = False

    async def positions(self):
        use_after = self._cancelled and self._positions_after
        source = self._positions_after if use_after else self._positions
        return [Position(symbol=s, quantity=q, avg_price=100.0) for s, q in source.items()]

    async def open_orders(self):
        self.open_orders_calls += 1
        return list(self._legs_after) if self._cancelled else list(self._legs)

    async def cancel_order(self, order_id):
        if self._cancel_raises is not None:
            raise self._cancel_raises
        self._cancelled = True
        return Order(symbol="X", side="sell", quantity=0.0, order_id=order_id, status="cancelled")


class _FakeOms:
    def __init__(self, exit_rejected, reprotect_raises):
        self.exit_orders = []
        self.signed_off = []
        self.protective_orders = []
        self._exit_rejected = exit_rejected
        self._reprotect_raises = reprotect_raises

    async def submit_exit_order(self, symbol, quantity, price, reason="signal"):
        self.exit_orders.append((symbol, quantity, reason))
        status = "rejected" if self._exit_rejected else "pending_signoff"
        return Order(
            symbol=symbol,
            side="sell",
            quantity=quantity,
            order_id=f"order-{len(self.exit_orders)}",
            status=status,
        )

    async def submit_protective_stop(self, symbol, quantity, stop_price, take_profit_price=None):
        if self._reprotect_raises is not None:
            raise self._reprotect_raises
        self.protective_orders.append((symbol, quantity, stop_price, take_profit_price))
        return Order(
            symbol=symbol,
            side="sell",
            quantity=quantity,
            order_id="protect-1",
            status="pending_signoff",
        )

    async def sign_off(self, order_id, operator):
        self.signed_off.append((order_id, operator))
        status = "transmitted" if order_id.startswith("protect") else "filled"
        return Order(symbol="X", side="sell", quantity=0.0, order_id=order_id, status=status)


class _FakeKillSwitch:
    def __init__(self, reason):
        self.reason = reason
        self.tripped = reason is not None


@pytest.fixture
def closer_factory():
    def make(
        positions=None,
        entries=None,
        legs=None,
        legs_after_cancel=None,
        positions_after_cancel=None,
        halt=None,
        cancel_raises=None,
        exit_rejected=False,
        reprotect_raises=None,
    ):
        positions = positions or {}
        entries = {s: _Entry() for s in positions} if entries is None else entries
        broker = _FakeBroker(
            positions, legs or [], legs_after_cancel or [], positions_after_cancel, cancel_raises
        )
        oms = _FakeOms(exit_rejected, reprotect_raises)
        closer = PositionCloser(oms, broker, _FakeKillSwitch(halt), entries)
        closer.oms, closer.broker = oms, broker
        return closer

    return make


@pytest.mark.asyncio
async def test_refuses_a_symbol_the_broker_does_not_hold(closer_factory):
    closer = closer_factory(positions={})
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "not held" in result.detail


@pytest.mark.asyncio
async def test_refuses_when_there_is_no_entry_record(closer_factory):
    """Without an entry basis the exit records no closed trade and no
    R-multiple. v1 names the script rather than half-recording."""
    closer = closer_factory(positions={"CBA.AX": 100.0}, entries={})
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "flatten_positions.py" in result.detail


@pytest.mark.asyncio
async def test_refuses_a_partial_quantity_in_v1(closer_factory):
    closer = closer_factory(positions={"CBA.AX": 100.0})
    result = await closer.close_position("CBA.AX", operator="tester", quantity=50.0)
    assert result.outcome is CloseOutcome.REFUSED
    assert "full close" in result.detail


@pytest.mark.asyncio
async def test_refuses_while_the_kill_switch_is_tripped(closer_factory):
    closer = closer_factory(positions={"CBA.AX": 100.0}, halt="broker gone")
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "broker gone" in result.detail, "the halt REASON must reach the operator"


@pytest.mark.asyncio
async def test_proceeds_past_the_halt_when_acknowledged(closer_factory):
    closer = closer_factory(positions={"CBA.AX": 100.0}, halt="broker gone")
    result = await closer.close_position("CBA.AX", operator="tester", acknowledge_halt=True)
    assert result.outcome is not CloseOutcome.REFUSED or "tripped" not in result.detail


@pytest.mark.asyncio
async def test_stops_dead_when_a_leg_survives_the_cancel(closer_factory):
    """⚠️ THE MOST IMPORTANT TEST IN THIS FILE.

    On 19 August a cancel reported PendingCancel while being rejected outright
    (error 10147). If a leg is still resting, selling puts the account short.
    """
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT"), _leg("CBA.AX", "2", "STP")],
        legs_after_cancel=[_leg("CBA.AX", "2", "STP")],  # one survives
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "still resting" in result.detail
    assert closer.oms.exit_orders == [], "NOTHING may be sold while a leg rests"


@pytest.mark.asyncio
async def test_reads_legs_with_open_orders_not_open_trades(closer_factory):
    """open_orders() uses reqAllOpenOrders. openTrades() is clientId-scoped and
    reported zero legs against sixteen resting on 24 August."""
    closer = closer_factory(positions={"CBA.AX": 100.0}, legs=[_leg("CBA.AX", "1", "LMT")])
    await closer.close_position("CBA.AX", operator="tester")
    assert closer.broker.open_orders_calls >= 2, "read once to capture, again to verify"


@pytest.mark.asyncio
async def test_refuses_when_the_verification_read_cannot_be_trusted(closer_factory):
    """`IBAdapter.open_orders()` returns `[]` for two different situations: a
    genuinely clean broker, and a client that could not answer (not yet
    connected, too old to carry `reqAllOpenOrdersAsync`) - its own docstring
    says so. A connection blip between the cancel and the verification re-read
    hits the second case, and `[]` looks identical to success.

    If the account-wide book held orders belonging to OTHER symbols before the
    cancel, and the post-cancel read comes back with the WHOLE book empty,
    those other orders cannot have vanished too - the read is not credible.
    This must be reported as UNVERIFIED, never as a clean cancel.
    """
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[
            _leg("CBA.AX", "1", "LMT"),
            _leg("CBA.AX", "2", "STP"),
            _leg("BHP.AX", "9", "STP"),  # another position's leg, untouched
        ],
        legs_after_cancel=[],  # the WHOLE book reads empty - the failure mode
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "VERIFIED" in result.detail
    assert (
        "leg(s) still resting after the cancel" not in result.detail
    ), "this is a read failure, not a survivor"
    assert closer.oms.exit_orders == [], "NOTHING may be sold when the cancel cannot be verified"


@pytest.mark.asyncio
async def test_a_cancel_that_cannot_be_resolved_refuses(closer_factory):
    from qat.data.broker.ib_adapter import CancelNotResolvedError

    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT")],
        cancel_raises=CancelNotResolvedError("no live order"),
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert closer.oms.exit_orders == []


@pytest.mark.asyncio
async def test_sells_the_reread_broker_quantity_not_the_stale_one(closer_factory):
    """A leg may fill during the cancel. The broker is the authority."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT")],
        positions_after_cancel={"CBA.AX": 60.0},
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.CLOSED
    assert result.quantity == 60.0


@pytest.mark.asyncio
async def test_the_sell_goes_through_the_oms_and_is_signed_off_as_the_operator(
    closer_factory,
):
    """Placing on the adapter directly would fill at the broker while the
    ledger never saw it - the position would vanish with no closed trade."""
    closer = closer_factory(positions={"CBA.AX": 100.0}, legs=[_leg("CBA.AX", "1", "LMT")])
    await closer.close_position("CBA.AX", operator="darren")
    assert closer.oms.exit_orders == [("CBA.AX", 100.0, "manual_close")]
    assert closer.oms.signed_off == [("order-1", "darren")]


@pytest.mark.asyncio
async def test_sends_exactly_one_order_and_never_retries(closer_factory):
    """M139 re-transmitted a working order every 60s into 4x the position."""
    closer = closer_factory(positions={"CBA.AX": 100.0}, legs=[_leg("CBA.AX", "1", "LMT")])
    await closer.close_position("CBA.AX", operator="tester")
    assert len(closer.oms.exit_orders) == 1


@pytest.mark.asyncio
async def test_abort_blocks_the_sell_when_a_leg_survives_the_cancel(closer_factory):
    """Now that a sell path exists at all, the abort's real job - stopping
    THAT sell from reaching the OMS - must be proven, not just implied by
    the cancel-legs return value. If this regresses, the account goes short."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT"), _leg("CBA.AX", "2", "STP")],
        legs_after_cancel=[_leg("CBA.AX", "2", "STP")],  # one survives
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert closer.oms.exit_orders == [], "a surviving leg must never let the sell through"


@pytest.mark.asyncio
async def test_abort_blocks_the_sell_when_the_verification_read_is_unverifiable(closer_factory):
    """Same defect, other trigger: an unverifiable post-cancel read must also
    stop the sell from reaching the OMS, not merely REFUSE with the right
    wording while quietly selling anyway."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[
            _leg("CBA.AX", "1", "LMT"),
            _leg("CBA.AX", "2", "STP"),
            _leg("BHP.AX", "9", "STP"),
        ],
        legs_after_cancel=[],
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert closer.oms.exit_orders == [], "an unverifiable read must never let the sell through"


@pytest.mark.asyncio
async def test_a_rejected_sell_re_places_the_bracket(closer_factory):
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT", limit=110.0), _leg("CBA.AX", "2", "STP", stop=90.0)],
        exit_rejected=True,
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.RECOVERED
    assert closer.oms.protective_orders == [("CBA.AX", 100.0, 90.0, 110.0)]


@pytest.mark.asyncio
async def test_a_failed_re_place_reports_unprotected(closer_factory, caplog):
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT", limit=110.0), _leg("CBA.AX", "2", "STP", stop=90.0)],
        exit_rejected=True,
        reprotect_raises=RuntimeError("broker said no"),
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.UNPROTECTED
    assert any(r.levelname == "CRITICAL" for r in caplog.records)
