"""`PositionCloser`, tested against IBKR's semantics rather than MockBroker's.

⚠️ THE FAKES IN THIS FILE MODEL THE REAL COMPONENTS, NOT `MockBroker`. That
distinction is the reason twenty-seven green tests sat over an unsafe branch:

* `MockBroker` FILLS SYNCHRONOUSLY, so a sell signed off there comes straight
  back `filled`. IBKR does not. `ib_translate._IB_STATUS_MAP` maps `Submitted`,
  `PreSubmitted`, `PendingSubmit`, `ApiPending` and `PendingCancel` all to
  `"transmitted"`; only `Filled` maps to `"filled"`. A normal market sell at
  IBKR therefore returns `"transmitted"`, and `_FakeOms.sign_off` below returns
  that, as the real path does.
* `OMS._sign_off_locked` (`oms.py:723`) sets `status = "rejected"`
  UNCONDITIONALLY while the kill switch is tripped. The original fake ignored
  the switch entirely, which is why `test_proceeds_past_the_halt_when_
  acknowledged` was satisfied by a disaster. `_FakeOms` now holds the same
  kill switch the closer does and rejects on it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace

import pytest

from qat.data.broker.adapter import Order, Position, RestingOrder
from qat.domain.oms.position_closer import CloseOutcome, PositionCloser

# ⚠️ WHAT A CANCEL ACTUALLY DOES AT IBKR - AND A FAKE MUST BE ABLE TO DO EACH.
#
# THREE rounds of Critical defects on this branch came from fakes that popped
# the leg out of the book the instant `cancel_order` was called: an
# instantaneous, always-honoured, fully-visible cancel. Real IBKR offers no
# such guarantee, and this repo already said so TWICE - `adapter.py:151` and
# `ib_adapter.py:638` both record that after a cancel `reqAllOpenOrders()`
# STILL SHOWS the order reporting `PendingCancel`, and that VISIBLE IS NOT
# GONE.
#
#   "terminal"  Honoured and settled: the leg stays visible reporting
#               `Cancelled`. This one IS gone.
#   "pending"   Honoured but not yet settled: the leg stays visible reporting
#               `PendingCancel`. ⚠️ THE HAPPY-PATH TRANSIENT - it needs
#               nothing more than ordinary cancel latency.
#   "rejected"  Refused outright (19 August, error 10147: an order belongs to
#               the clientId that placed it). `cancelOrder` does NOT raise -
#               the refusal arrives on the error channel - and the leg is
#               untouched, still `Submitted`, still able to fill.
#   "gone"      The leg disappears from the book entirely. Possible, and the
#               only behaviour every fake in this branch used to model.
_CANCEL_EFFECTS = ("terminal", "pending", "rejected", "gone")


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


def _working_order(symbol, order_id, *, side="buy", order_type="MKT"):
    """A working order for the symbol that is NOT a protective leg."""
    return RestingOrder(
        symbol=symbol,
        order_id=order_id,
        side=side,
        order_type=order_type,
        quantity=100.0,
        status="Submitted",
    )


@dataclass
class _Entry:
    price: float = 100.0


class _FakeBroker:
    def __init__(
        self,
        positions,
        legs,
        legs_after_cancel,
        positions_after_cancel,
        cancel_raises,
        legs_at_recovery=None,
        cancel_raises_for=(),
        cancel_effect="terminal",
    ):
        self._positions = positions
        self._positions_after = positions_after_cancel
        self._legs = legs
        # ⚠️ `None` means "let the cancel decide", which is the realistic
        # default: the book after the cancel is whatever `_apply_cancel` made
        # of it. An explicit list is still accepted, for the tests that need a
        # specific after-state (a blind read, another symbol's leg surviving).
        self._legs_after = legs_after_cancel
        self._legs_at_recovery = legs_at_recovery
        self._cancel_raises = cancel_raises
        assert cancel_effect in _CANCEL_EFFECTS
        self._cancel_effect = cancel_effect
        # The book this broker actually keeps, mutated BY the cancel.
        self._book = list(legs)
        # Per-leg, so the SECOND leg's cancel can raise after the first has
        # already gone through - the branch that leaves the position half
        # stripped and is the whole point of the "refusal after cancels" tests.
        self._cancel_raises_for = set(cancel_raises_for)
        self.open_orders_calls = 0
        self.cancelled_ids = []
        self._cancelled = False

    async def positions(self):
        use_after = self._cancelled and self._positions_after
        source = self._positions_after if use_after else self._positions
        return [Position(symbol=s, quantity=q, avg_price=100.0) for s, q in source.items()]

    async def open_orders(self):
        # Reads 1 and 2 are the capture and the verification re-read. Anything
        # after those is the recovery path asking again, which is a different
        # moment in time - by then this app's own sell may be working.
        #
        # ⚠️ NOTHING IS FILTERED HERE. `open_orders()` is `reqAllOpenOrders`,
        # and IBKR answers it with every order it is still showing, whatever
        # status it carries - `PendingCancel` and `Cancelled` included. A fake
        # that filtered would hide exactly the leg this branch kept selling
        # over. Deciding what counts as gone is the caller's job.
        self.open_orders_calls += 1
        if self.open_orders_calls > 2 and self._legs_at_recovery is not None:
            return list(self._legs_at_recovery)
        if not self._cancelled:
            return list(self._legs)
        if self._legs_after is not None:
            return list(self._legs_after)
        return list(self._book)

    def _apply_cancel(self, order_id):
        """What the BROKER does to its book when a cancel arrives. See
        `_CANCEL_EFFECTS` - three of the four leave the leg visible."""
        if self._cancel_effect == "gone":
            self._book = [o for o in self._book if o.order_id != order_id]
            return
        if self._cancel_effect == "rejected":
            return  # untouched, still Submitted, still able to fill
        status = "PendingCancel" if self._cancel_effect == "pending" else "Cancelled"
        self._book = [
            replace(o, status=status) if o.order_id == order_id else o for o in self._book
        ]

    async def cancel_order(self, order_id):
        if self._cancel_raises is not None:
            raise self._cancel_raises
        if order_id in self._cancel_raises_for:
            self._cancelled = True  # the earlier legs DID go through
            raise RuntimeError(f"broker refused the cancel of {order_id}")
        self.cancelled_ids.append(order_id)
        self._cancelled = True
        self._apply_cancel(order_id)
        # ⚠️ The cancel's OWN response is not evidence, so this says "cancelled"
        # whatever `_apply_cancel` just did to the book - including nothing.
        # That is the 19 August shape exactly.
        return Order(symbol="X", side="sell", quantity=0.0, order_id=order_id, status="cancelled")


class _FakeOms:
    def __init__(
        self,
        exit_rejected,
        reprotect_raises,
        believed_orders=None,
        kill_switch=None,
        sign_off_status="transmitted",
    ):
        self.exit_orders = []
        self.signed_off = []
        self.protective_orders = []
        self._exit_rejected = exit_rejected
        self._reprotect_raises = reprotect_raises
        self._believed_orders = believed_orders or []
        self._kill_switch = kill_switch
        self._sign_off_status = sign_off_status

    def orders(self):
        return list(self._believed_orders)

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
        # ⚠️ The real `OMS._sign_off_locked` rejects UNCONDITIONALLY while the
        # kill switch is tripped (oms.py:723). A fake that ignores the switch
        # is how a green test came to describe a disaster.
        if self._kill_switch is not None and self._kill_switch.tripped:
            return Order(
                symbol="X", side="sell", quantity=0.0, order_id=order_id, status="rejected"
            )
        # ⚠️ "transmitted", not "filled". IBKR answers a market sell with
        # Submitted/PreSubmitted, which `_IB_STATUS_MAP` maps to
        # "transmitted"; only MockBroker fills synchronously.
        status = "transmitted" if order_id.startswith("protect") else self._sign_off_status
        return Order(symbol="X", side="sell", quantity=0.0, order_id=order_id, status=status)


class _FakeKillSwitch:
    def __init__(self, reason):
        self.reason = reason
        self.tripped = reason is not None


class _VanishingEntries(Mapping):
    """`_LiveEntries` after the bridge has popped the entry.

    `runtime._LiveEntries` reads THROUGH to `SignalToOrderBridge.position_
    entries()` on every access, and the bridge pops a symbol's entry the
    moment it observes the position close. So a second lookup, after the legs
    are cancelled, can `KeyError` where the first succeeded. This mapping
    answers exactly once and is empty from then on.
    """

    def __init__(self, entry):
        self._entry = entry
        self.lookups = 0

    def __getitem__(self, symbol):
        self.lookups += 1
        if self.lookups > 1:
            raise KeyError(symbol)
        return self._entry

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0


@pytest.fixture
def closer_factory():
    def make(
        positions=None,
        entries=None,
        legs=None,
        legs_after_cancel=None,
        legs_at_recovery=None,
        positions_after_cancel=None,
        halt=None,
        cancel_raises=None,
        cancel_raises_for=(),
        cancel_effect="terminal",
        exit_rejected=False,
        sign_off_status="transmitted",
        reprotect_raises=None,
        believed_orders=None,
    ):
        positions = positions or {}
        entries = {s: _Entry() for s in positions} if entries is None else entries
        broker = _FakeBroker(
            positions,
            legs or [],
            legs_after_cancel,
            positions_after_cancel,
            cancel_raises,
            legs_at_recovery,
            cancel_raises_for,
            cancel_effect,
        )
        kill_switch = _FakeKillSwitch(halt)
        oms = _FakeOms(
            exit_rejected, reprotect_raises, believed_orders, kill_switch, sign_off_status
        )
        closer = PositionCloser(oms, broker, kill_switch, entries)
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
    assert "reset" in result.detail.lower(), "and what to do about it"


@pytest.mark.asyncio
async def test_a_tripped_switch_cancels_nothing_and_sells_nothing(closer_factory):
    """⚠️ REPLACES `test_proceeds_past_the_halt_when_acknowledged`, which was
    satisfied by a disaster (spec, 1 September, reversal).

    The halt cannot be honoured half-way. `_cancel_legs` calls
    `broker.cancel_order()` DIRECTLY and never passes sign-off, so it succeeds
    during a halt; the sell goes through `sign_off`, which
    `OMS._sign_off_locked` rejects unconditionally while the switch is
    tripped; and re-protecting needs sign-off too, so recovery is rejected for
    the same reason. Acknowledging the halt therefore deleted the stop, sold
    nothing, and could not put the bracket back.

    The refusal must come BEFORE the broker is touched at all - not merely
    before the sell.
    """
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT"), _leg("CBA.AX", "2", "STP")],
        halt="broker gone",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert closer.broker.cancelled_ids == [], "NOTHING may be cancelled while tripped"
    assert closer.broker.open_orders_calls == 0, "the refusal precedes any broker read"
    assert closer.oms.exit_orders == [], "NOTHING may be sold while tripped"
    assert closer.oms.protective_orders == []


@pytest.mark.asyncio
async def test_there_is_no_halt_override_parameter(closer_factory):
    """`acknowledge_halt` is REMOVED, not merely defaulted off - the spec's
    reversal says there is no acknowledged override. A caller still passing it
    must fail loudly rather than be silently ignored."""
    closer = closer_factory(positions={"CBA.AX": 100.0}, halt="broker gone")
    with pytest.raises(TypeError):
        await closer.close_position("CBA.AX", operator="tester", acknowledge_halt=True)


@pytest.mark.asyncio
async def test_stops_dead_when_a_leg_survives_the_cancel(closer_factory):
    """⚠️ THE MOST IMPORTANT TEST IN THIS FILE.

    On 19 August a cancel reported PendingCancel while being rejected outright
    (error 10147). If a leg is still resting, selling puts the account short.

    ⚠️ The survivor is modelled `PendingCancel`, and it used to be modelled
    `Submitted`. That is not a cosmetic difference. This test cited 19 August
    and PendingCancel BY NAME while constructing the one status the branch it
    guards did NOT catch: `_working_orders()` filtered the post-cancel read on
    `WORKING_STATUSES`, which does not contain `PendingCancel`, so a leg in it
    was read as GONE and the sell went out over both legs still resting. A
    `Submitted` survivor passed through that filter and made the test green
    over the defect it was named for.
    """
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT"), _leg("CBA.AX", "2", "STP")],
        # One survives - VISIBLE, in PendingCancel, exactly as IBKR shows it.
        legs_after_cancel=[_leg("CBA.AX", "2", "STP", status="PendingCancel")],
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "still resting" in result.detail
    assert closer.oms.exit_orders == [], "NOTHING may be sold while a leg rests"


# --- ⚠️ PENDINGCANCEL: VISIBLE IS NOT GONE ------------------------------
#
# `_working_orders()` filtered BOTH the capture read and the post-cancel
# verification read on `resting_orders.WORKING_STATUSES` -
# {Submitted, PreSubmitted, PendingSubmit, ApiPending, ApiUpdate}. These are
# RAW IBKR statuses (`from_ib_open_order` passes `str(trade.orderStatus.
# status)` straight through), and `PendingCancel` is NOT among them.
#
# So the verification read DROPPED any leg sitting in PendingCancel,
# `survivors` came back empty, the "stop dead if a leg survives" step passed,
# and the market SELL went out with both OCA legs STILL RESTING at the broker.
# A short position, reported to the operator as a clean close.
#
# ⚠️ AND PendingCancel FIRES ON THE HAPPY PATH. It is both the 19 August
# rejected-cancel state (error 10147) and the ordinary transient of a cancel
# that IS being honoured. It needs nothing more than normal IBKR latency.
#
# The predicates therefore differ by design: CAPTURE asks "what is working,
# so what must I cancel and what would I re-place" (WORKING_STATUSES); VERIFY
# asks "is it GONE", and a leg is gone only if it is absent from open_orders()
# entirely or reports a TERMINAL status. Anything else still visible for the
# symbol is a SURVIVOR.


@pytest.mark.asyncio
async def test_a_leg_left_in_pending_cancel_blocks_the_sell(closer_factory):
    """⚠️ THE ROUND-3 CRITICAL, ON THE HAPPY PATH.

    Both cancels are honoured; both legs sit in `PendingCancel` for the
    moment the verification read happens. They are STILL RESTING and can
    still fill. Nothing may be sold.
    """
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT"), _leg("CBA.AX", "2", "STP")],
        cancel_effect="pending",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is not CloseOutcome.CLOSED, result.detail
    assert closer.oms.exit_orders == [], (
        "a leg in PendingCancel is VISIBLE AT THE BROKER and can still fill - "
        "selling over it puts the account SHORT"
    )
    assert "1" in result.detail and "2" in result.detail


@pytest.mark.asyncio
async def test_a_cancel_rejected_outright_blocks_the_sell(closer_factory):
    """19 August, error 10147: `cancelOrder` does not raise, the refusal
    arrives on the error channel, and the leg is untouched and still
    `Submitted`. The cancel's own response said success."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT"), _leg("CBA.AX", "2", "STP")],
        cancel_effect="rejected",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED, result.detail
    assert closer.oms.exit_orders == []
    assert "still resting" in result.detail


@pytest.mark.asyncio
async def test_a_leg_that_reaches_a_terminal_status_IS_gone_and_the_sell_proceeds(
    closer_factory,
):
    """The other side, so the fix cannot be "never sell". A cancel that
    settles leaves the leg visible reporting `Cancelled` - a TERMINAL status.
    It cannot fill, so it is gone and the close must go through."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT"), _leg("CBA.AX", "2", "STP")],
        cancel_effect="terminal",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.CLOSED, result.detail
    assert closer.oms.exit_orders == [("CBA.AX", 100.0, "manual_close")]


@pytest.mark.asyncio
async def test_a_leg_that_vanishes_from_the_book_IS_gone(closer_factory):
    """The behaviour every fake in this branch used to model, kept as ONE of
    four rather than as the only one."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT"), _leg("CBA.AX", "2", "STP")],
        cancel_effect="gone",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.CLOSED, result.detail


@pytest.mark.asyncio
async def test_recovery_will_not_re_arm_over_a_leg_in_pending_cancel(closer_factory, caplog):
    """The same widening in `_recover`, so the file does not hold two
    different notions of "still live".

    `_recover`'s in-flight-sell guard read `_working_orders()` too, so a
    protective leg still visible in `PendingCancel` was invisible to it and a
    fresh full-size bracket went on top of one that can still fill - the short
    trap from the other side.
    """
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT", limit=110.0), _leg("CBA.AX", "2", "STP", stop=90.0)],
        legs_after_cancel=[],  # the verification read is clean, so the sell is attempted
        legs_at_recovery=[_leg("CBA.AX", "2", "STP", stop=90.0, status="PendingCancel")],
        sign_off_status="rejected",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.UNPROTECTED, result.detail
    assert closer.oms.protective_orders == [], "no bracket over a leg that can still fill"
    assert any(r.levelname == "CRITICAL" for r in caplog.records)


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


# --- believed_legs_for --------------------------------------------------
#
# Not broker truth. `_cancel_legs` never consults this method - it reads
# `_working_orders()` from the broker, unfiltered on side/type/status. These
# tests pin the filter this preview applies to the app's OWN record, and that
# the rename covers every call site (a plain `legs_for` here would mean the
# rename regressed silently).


def test_believed_legs_for_filters_to_transmitted_sell_stops(closer_factory):
    """Only side=sell, order_type=stop, status=transmitted counts as a
    believed-resting protective leg - anything else on the app's own record
    is not what this preview is for."""
    matching = Order(
        symbol="CBA.AX",
        side="sell",
        order_type="stop",
        status="transmitted",
        quantity=100.0,
        order_id="1",
    )
    wrong_symbol = Order(
        symbol="BHP.AX",
        side="sell",
        order_type="stop",
        status="transmitted",
        quantity=100.0,
        order_id="2",
    )
    wrong_side = Order(
        symbol="CBA.AX",
        side="buy",
        order_type="stop",
        status="transmitted",
        quantity=100.0,
        order_id="3",
    )
    wrong_type = Order(
        symbol="CBA.AX",
        side="sell",
        order_type="market",
        status="transmitted",
        quantity=100.0,
        order_id="4",
    )
    wrong_status = Order(
        symbol="CBA.AX",
        side="sell",
        order_type="stop",
        status="pending_signoff",
        quantity=100.0,
        order_id="5",
    )
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        believed_orders=[matching, wrong_symbol, wrong_side, wrong_type, wrong_status],
    )
    assert closer.believed_legs_for("CBA.AX") == (matching,)


def test_believed_legs_for_reads_the_app_not_the_broker(closer_factory):
    """The whole point of the rename: this is the OMS's local record, and it
    does not change when the broker's book does. `legs` (the broker's resting
    orders) and `believed_orders` (the app's local `Order` record) are wired
    to two different fakes here on purpose, to prove `believed_legs_for`
    reads only the second."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "broker-1", "STP")],  # the broker's book: one leg
        believed_orders=[],  # the app's own record: none
    )
    assert closer.believed_legs_for("CBA.AX") == ()


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
    assert closer.oms.signed_off == [("protect-1", "auto-reprotect")]


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


# --- IBKR's semantics, not MockBroker's ---------------------------------


@pytest.mark.asyncio
async def test_a_transmitted_sell_is_a_success_not_a_failure(closer_factory):
    """⚠️ THE DEFECT THAT MADE EVERY GREEN TEST WORTHLESS.

    `ib_translate._IB_STATUS_MAP` maps `Submitted`, `PreSubmitted`,
    `PendingSubmit`, `ApiPending` and `PendingCancel` ALL to `"transmitted"`;
    only `Filled` maps to `"filled"`. So a perfectly normal IBKR market sell
    comes back `"transmitted"`, and `if signed.status != "filled"` sent it
    into recovery: `_held_quantity` still read the FULL unfilled position, so
    a new full-size OCA bracket was placed on a position that was in the
    middle of being sold. The sell then filled, the account went flat, and the
    fresh bracket rested orphaned against nothing - it fires and the account
    goes SHORT. The operator was told "the position is protected and still
    held", which was false in both halves.

    MockBroker fills synchronously, which is the only reason this looked fine.
    """
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0)],
        sign_off_status="transmitted",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.CLOSED
    assert result.quantity == 100.0
    assert closer.oms.protective_orders == [], "NO bracket may be re-armed over a working sell"


@pytest.mark.asyncio
async def test_a_transmitted_sell_is_not_described_as_confirmed_filled(closer_factory):
    """CLOSED, but the wording must not claim a fill the broker has not
    reported - a market order that is working is not yet an execution."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0)],
        sign_off_status="transmitted",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert "working" in result.detail.lower()
    assert "not reported a fill" in result.detail


@pytest.mark.asyncio
async def test_a_filled_sell_is_also_a_success(closer_factory):
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0)],
        sign_off_status="filled",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.CLOSED
    assert closer.oms.protective_orders == []


@pytest.mark.asyncio
async def test_a_rejected_sign_off_still_re_places_the_bracket(closer_factory):
    """The genuine failure: sign-off rejected, nothing working, protection
    must go back."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT", limit=110.0), _leg("CBA.AX", "2", "STP", stop=90.0)],
        sign_off_status="rejected",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.RECOVERED
    assert closer.oms.protective_orders == [("CBA.AX", 100.0, 90.0, 110.0)]


@pytest.mark.asyncio
async def test_never_re_arms_a_bracket_while_a_sell_is_working(closer_factory, caplog):
    """The second half of the C1 fix, and defence in depth for the first.

    Whatever the sell's reported status, if the broker's book still shows a
    working SELL for the symbol then a bracket placed now is a second full-
    size sell stacked on top of one already in flight. When the working sell
    fills, that bracket is orphaned against a flat position and puts the
    account SHORT - the exact trap the whole cancel-first sequence exists to
    avoid. Refuse to re-protect and say so LOUDLY instead.
    """
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0)],
        legs_after_cancel=[],
        legs_at_recovery=[_working_order("CBA.AX", "exit-1", side="sell", order_type="MKT")],
        sign_off_status="rejected",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.UNPROTECTED
    assert closer.oms.protective_orders == [], "no bracket over an in-flight sell"
    assert "working sell" in result.detail
    assert any(r.levelname == "CRITICAL" for r in caplog.records)


# --- the blind read -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_held_symbol_reading_zero_legs_refuses(closer_factory):
    """⚠️ `IBAdapter.open_orders()` returns `[]` for BOTH "the book is clean"
    and "the client could not answer" - its own docstring says so. If the
    FIRST read (the capture) comes back empty, `before` and `captured` are
    both empty, so the account-wide collapse guard cannot fire, no leg
    survives, and the sell went out with both legs still resting.

    Every position this app holds carries protection. For a symbol the BROKER
    says is held, zero legs means the read failed - not that the position is
    bare. Refuse.
    """
    closer = closer_factory(positions={"CBA.AX": 100.0}, legs=[])
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert closer.oms.exit_orders == [], "NOTHING may be sold on a read that answered nothing"
    assert closer.broker.cancelled_ids == []


@pytest.mark.asyncio
async def test_the_zero_leg_refusal_cites_what_the_app_believes(closer_factory):
    """The cross-check the spec asks for: the OMS's own belief is what makes
    "zero" recognisable as a failed read rather than a clean book."""
    believed = Order(
        symbol="CBA.AX",
        side="sell",
        order_type="stop",
        status="transmitted",
        quantity=100.0,
        order_id="believed-1",
    )
    closer = closer_factory(positions={"CBA.AX": 100.0}, legs=[], believed_orders=[believed])
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "1" in result.detail
    assert "believe" in result.detail.lower()


# --- M139: never send while another order works -------------------------


@pytest.mark.asyncio
async def test_refuses_when_a_non_protective_order_is_working(closer_factory):
    """The spec's precondition "no working order for the symbol beyond its
    protective legs" (M139: a re-transmitted working order left the account
    holding 4x the intended position). `_cancel_legs` cancelled EVERY working
    order for the symbol, unfiltered by side or type, so a working BUY was
    silently cancelled and the close proceeded regardless."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0), _working_order("CBA.AX", "9")],
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "9" in result.detail
    assert closer.broker.cancelled_ids == [], "the refusal precedes every cancel"
    assert closer.oms.exit_orders == []


@pytest.mark.asyncio
async def test_a_working_order_on_another_symbol_does_not_block(closer_factory):
    """The precondition is per-symbol. Another position's working order is
    none of this close's business."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0), _working_order("BHP.AX", "9")],
        legs_after_cancel=[_working_order("BHP.AX", "9")],
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.CLOSED
    assert closer.broker.cancelled_ids == ["1"], "only this symbol's legs"


# --- a short position is not a held position ----------------------------


@pytest.mark.asyncio
async def test_refuses_a_short_position(closer_factory):
    """`_held_quantity` took `abs(position.quantity)`, so a SHORT read as
    held and "closing" it would send another SELL - doubling the short rather
    than covering it."""
    closer = closer_factory(
        positions={"CBA.AX": -100.0},
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0)],
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "short" in result.detail.lower()
    assert closer.oms.exit_orders == [], "a sell would DOUBLE the short"
    assert closer.broker.cancelled_ids == []


# --- wording that does not overclaim ------------------------------------


@pytest.mark.asyncio
async def test_already_flat_admits_a_leg_may_have_filled(closer_factory):
    """ "already flat after the legs were cancelled" implied the cancels did
    it. One of them may equally have FILLED during the race, which is a very
    different event for the operator to read - it means the position closed at
    the stop or the target, not at market."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0)],
        positions_after_cancel={"CBA.AX": 0.0},
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.CLOSED
    assert result.quantity == 0.0
    assert "filled" in result.detail.lower(), "a leg filling is one of the two possibilities"
    assert "cancel" in result.detail.lower()


# --- the entry record is bound ONCE, before anything is cancelled -------


@pytest.mark.asyncio
async def test_the_entry_is_bound_before_the_legs_are_cancelled(closer_factory):
    """`runtime._LiveEntries` reads THROUGH to the bridge on every access, and
    the bridge pops a symbol's entry when it sees the position close. A second
    lookup after the cancel could therefore `KeyError` - AFTER the protection
    was already deleted, leaving the position bare with an exception on the
    way out."""
    entries = _VanishingEntries(_Entry())
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        entries=entries,
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0)],
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.CLOSED
    assert entries.lookups == 1, "one lookup, taken before anything is cancelled"


# --- a refusal AFTER the cancels have been issued -----------------------
#
# ⚠️ THE FINDING: three branches in `_cancel_legs` return a failure once
# `cancel_order` has ALREADY run, and `close_position` funnelled all three
# through `_refuse`, which reports `cancelled_legs=()` and attempts no
# recovery. So the operator was told "NOTHING was sold" - true - while the
# protection had been half or wholly stripped, and never told WHICH legs were
# gone. In the survivors case in particular the text listed the legs still
# resting and never mentioned that the OTHER one was already cancelled: a bare
# downside reading as reassuring, in a non-blocking information dialog.


@pytest.mark.asyncio
async def test_a_survivor_refusal_names_the_leg_it_already_cancelled(closer_factory):
    """One leg gone, one still resting. Saying only "1 leg still resting" reads
    as "the position is still protected, nothing happened" - and the operator
    walks away from a position carrying HALF its bracket."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT", limit=110.0), _leg("CBA.AX", "2", "STP", stop=90.0)],
        legs_after_cancel=[_leg("CBA.AX", "2", "STP", stop=90.0)],  # the STP survives
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert result.cancelled_legs == ("1",), "the leg that IS gone must be reported"
    assert "1" in result.detail and "2" in result.detail
    assert "still resting" in result.detail
    assert "cancelled" in result.detail.lower()
    assert closer.oms.exit_orders == [], "still no sell"


@pytest.mark.asyncio
async def test_an_unverifiable_refusal_reports_the_cancels_it_issued(closer_factory):
    """The collapse guard fires AFTER both cancels went out. Their outcome is
    unknown, which is not the same as "nothing happened" - and it is the
    reading the operator was left with."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[
            _leg("CBA.AX", "1", "LMT", limit=110.0),
            _leg("CBA.AX", "2", "STP", stop=90.0),
            _leg("BHP.AX", "9", "STP"),
        ],
        legs_after_cancel=[],
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert sorted(result.cancelled_legs) == ["1", "2"]
    assert "VERIFIED" in result.detail
    assert "leg(s) still resting after the cancel" not in result.detail
    assert "1" in result.detail and "2" in result.detail
    # No bracket may be re-placed on a read that cannot be trusted: the legs
    # may still be resting, and a fresh full-size bracket over them is the
    # short trap from the other side.
    assert closer.oms.protective_orders == []
    assert closer.oms.exit_orders == []


@pytest.mark.asyncio
async def test_a_second_leg_cancel_that_raises_re_protects_the_bare_position(closer_factory):
    """Leg 1 cancelled, leg 2's cancel RAISED, and the re-read shows nothing
    working for the symbol - the position is BARE. `_refuse` returned
    `cancelled_legs=()` and attempted no recovery at all, so the operator was
    told nothing had been cancelled over a position with no stop."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT", limit=110.0), _leg("CBA.AX", "2", "STP", stop=90.0)],
        legs_after_cancel=[],
        cancel_raises_for=("2",),
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.RECOVERED, result.detail
    assert result.cancelled_legs == ("1",)
    assert closer.oms.protective_orders == [("CBA.AX", 100.0, 90.0, 110.0)]
    assert "1" in result.detail
    assert closer.oms.exit_orders == [], "a refusal is still a refusal - nothing is sold"


@pytest.mark.asyncio
async def test_a_refusal_before_any_cancel_still_reports_nothing_cancelled(closer_factory):
    """The other half of the same rail: a refusal that precedes every cancel
    must NOT start claiming legs were touched, and must not run recovery."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0), _working_order("CBA.AX", "9")],
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert result.cancelled_legs == ()
    assert closer.oms.protective_orders == []
    assert closer.broker.cancelled_ids == []


# --- N4: _recover's in-flight-sell guard must fail CLOSED ---------------


@pytest.mark.asyncio
async def test_recovery_refuses_to_re_arm_on_a_blind_book_read(closer_factory, caplog):
    """⚠️ `_recover`'s "never re-arm over an in-flight sell" guard reads
    `_working_orders()`, and `IBAdapter.open_orders()` returns `[]` for an
    unanswerable client exactly as it does for a clean book. So the guard
    failed OPEN on the blind read - it placed the bracket - while
    `_cancel_legs` REFUSES on the identical read. Two layers, one broker
    method, opposite verdicts.

    Same discriminator as `_cancel_legs`: other symbols' orders were working
    before the cancel, so an entirely empty account-wide book afterwards is
    not credible.
    """
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "STP", stop=90.0), _working_order("BHP.AX", "9")],
        legs_after_cancel=[_working_order("BHP.AX", "9")],  # credible: BHP still there
        legs_at_recovery=[],  # the recovery read goes blind
        sign_off_status="rejected",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.UNPROTECTED
    assert closer.oms.protective_orders == [], "no bracket on a read that answered nothing"
    assert any(r.levelname == "CRITICAL" for r in caplog.records)


@pytest.mark.asyncio
async def test_recovery_still_re_arms_when_the_empty_read_is_credible(closer_factory):
    """The other side of N4, so the fix cannot be "never re-arm". Nothing else
    was working account-wide before the cancel, so an empty book afterwards is
    exactly what a clean broker looks like and recovery must proceed."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT", limit=110.0), _leg("CBA.AX", "2", "STP", stop=90.0)],
        legs_after_cancel=[],
        legs_at_recovery=[],
        sign_off_status="rejected",
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.RECOVERED, result.detail
    assert closer.oms.protective_orders == [("CBA.AX", 100.0, 90.0, 110.0)]


# --- N5: the zero-leg refusal names the escape hatch --------------------


@pytest.mark.asyncio
async def test_the_zero_leg_refusal_names_the_script(closer_factory):
    """Every other refusal that ends the road names `flatten_positions.py`.
    This one did not, and it is the one with NO way forward: a genuinely bare
    held position can never be closed by this button, so the operator is left
    with a refusal and no next step."""
    closer = closer_factory(positions={"CBA.AX": 100.0}, legs=[])
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "flatten_positions.py" in result.detail
