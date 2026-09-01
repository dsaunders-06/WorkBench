"""Close one app-managed position in full, from the operator's hand.

⚠️ THE ORDER OF OPERATIONS IS THE WHOLE SAFETY OF THIS. Every position carries
two OCA-linked resting SELL orders for its full quantity. Selling without
cancelling them first leaves them resting against a position no longer held -
they execute and put the account SHORT.

Separate from `oms.py` deliberately: that file carries the reconciliation rail,
the resting-order scan and fill absorption. This choreographs one irreversible
operation with its own recovery branch, which is a different job.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from qat.data.broker.adapter import BrokerAdapter, Order, RestingOrder
from qat.domain.oms.oms import OMS
from qat.domain.oms.resting_orders import WORKING_STATUSES
from qat.domain.oms.signal_bridge import PositionEntry
from qat.domain.risk_engine.kill_switch import KillSwitch

logger = logging.getLogger(__name__)

_SCRIPT_HINT = "scripts/flatten_positions.py"

# ⚠️ A SELL THAT IS WORKING AT THE BROKER IS A SUCCESS, NOT A FAILURE.
#
# `ib_translate._IB_STATUS_MAP` maps `Submitted`, `PreSubmitted`,
# `PendingSubmit`, `ApiPending` and `PendingCancel` ALL to `"transmitted"`;
# only `Filled` maps to `"filled"`. A normal IBKR market sell therefore comes
# back `"transmitted"`, and a `!= "filled"` test called that a failed sell: it
# ran recovery, re-read the still-unfilled full position, and placed a NEW
# full-size OCA bracket over a sell already in flight. The sell filled, the
# account went flat, and the fresh bracket rested orphaned - it fires and the
# account goes SHORT.
#
# `MockBroker` fills synchronously, which is the only reason the original read
# as correct in the tests. IBKR does not.
_SELL_IS_WORKING_OR_DONE = frozenset({"transmitted", "filled"})

# IBKR order types (`order.orderType`, carried RAW through
# `from_ib_open_order`) that a protective bracket leg can be. A held position's
# bracket is a STP and a LMT, OCA-linked.
#
# ⚠️ Residual, recorded rather than hidden: a manual resting limit SELL placed
# by hand in TWS is indistinguishable from a take-profit leg by this test, and
# would be cancelled as one. That is strictly safer than the alternative
# (treating it as an intruder and refusing every close on a symbol whose
# target leg is a plain LMT), and the spec's "known interaction" section
# already records that hand-placed orders on a managed symbol are outside what
# this button reasons about.
_PROTECTIVE_ORDER_TYPES = frozenset({"STP", "STP LMT", "LMT", "TRAIL", "TRAIL LIMIT"})


def _is_protective_leg(order: RestingOrder) -> bool:
    """A working SELL of a bracket type, i.e. something this close is entitled
    to cancel. Everything else working on the symbol is an intruder - M139."""
    return order.side.lower() == "sell" and order.order_type.upper() in _PROTECTIVE_ORDER_TYPES


class CloseOutcome(Enum):
    CLOSED = "closed"
    REFUSED = "refused"
    RECOVERED = "recovered"
    UNPROTECTED = "unprotected"


@dataclass(frozen=True, slots=True)
class CloseResult:
    outcome: CloseOutcome
    symbol: str
    quantity: float
    cancelled_legs: tuple[str, ...]
    detail: str


class PositionCloser:
    def __init__(
        self,
        oms: OMS,
        broker: BrokerAdapter,
        kill_switch: KillSwitch,
        entries: Mapping[str, PositionEntry],
    ) -> None:
        self.oms = oms
        self.broker = broker
        self.kill_switch = kill_switch
        self.entries = entries

    def _refuse(self, symbol: str, detail: str) -> CloseResult:
        logger.warning("Manual close of %s REFUSED: %s", symbol, detail)
        return CloseResult(CloseOutcome.REFUSED, symbol, 0.0, (), detail)

    def believed_legs_for(self, symbol: str) -> tuple[Order, ...]:
        """The protective leg(s) this app currently BELIEVES are resting for
        symbol - synchronous, from the OMS's own local record, for a
        confirmation dialog to itemise before the operator commits.

        ⚠️ NOT broker truth, and the name says so on its own - unlike
        `_held_quantity` (also a preview of the broker's own fact), this reads
        `self.oms.orders()`, the app's LOCAL record, filtered on side/type/
        status. `_cancel_legs` cancels whatever `_working_orders()` returns
        from the BROKER instead, with no such filter, so this preview can
        differ from what actually gets cancelled two ways: it can be STALE,
        and a working order of a different side or type is cancelled there
        without ever appearing here. Public rather than a leading underscore
        despite that gap, because the dashboard (a different module) is a
        legitimate caller of exactly this preview, for exactly this dialog -
        an underscore would misrepresent a supported cross-module API as
        internal-only. The name carries the warning a leading underscore
        would otherwise have to stand in for.

        Deliberately NOT `_working_orders()`: that reads the broker and is
        async, and a Qt slot cannot await before opening its confirm dialog.
        `close_position` itself re-reads and re-verifies the broker before
        cancelling or selling anything, exactly as `_cancel_legs` requires -
        this method is never consulted on that path, only by the dialog that
        precedes it.

        A bracket is ONE `Order` record per entry (`submit_protective_stop`
        carries both `stop_price` and `take_profit_price` on it), not two -
        so this normally returns zero or one order, not two.
        """
        return tuple(
            order
            for order in self.oms.orders()
            if order.symbol == symbol
            and order.side == "sell"
            and order.order_type == "stop"
            and order.status == "transmitted"
        )

    async def _held_quantity(self, symbol: str) -> float:
        """The BROKER's quantity, SIGNED. App records are a claim; this is the
        fact.

        ⚠️ NOT `abs()`. It was, and that made a SHORT position read as held:
        `close_position` would then send another SELL, DOUBLING the short
        rather than covering it. A negative here is refused by the caller.
        """
        for position in await self.broker.positions():
            if position.symbol == symbol:
                return position.quantity
        return 0.0

    async def _working_orders(self) -> list[RestingOrder]:
        """Every working order, account-wide, read with `open_orders()`.

        NOT `openTrades()`: that read is clientId-scoped and on 24 August
        reported zero protective stops while sixteen were resting.
        """
        orders = await self.broker.open_orders()
        return [o for o in orders if o.status in WORKING_STATUSES]

    async def _cancel_legs(self, symbol: str) -> tuple[list[RestingOrder], str | None]:
        """Cancel every working leg, then RE-READ to prove they are gone.

        ⚠️ The cancel's own response is not evidence. On 19 August one reported
        PendingCancel while being rejected outright (error 10147).

        ⚠️ Nor is an empty re-read, on its own. `IBAdapter.open_orders()`
        returns `[]` for two different situations - a genuinely clean broker,
        and a client that could not answer (not yet connected, or too old to
        carry `reqAllOpenOrdersAsync`) - and its own docstring says so. A
        connection blip landing between the cancel and this re-read produces
        the SAME `[]` a clean book would, and `open_orders()` gives this layer
        no way to tell the two apart.

        The discriminator: read the WHOLE book, not just `symbol`, before and
        after cancelling. If OTHER symbols' orders were working beforehand and
        the account-wide total has collapsed to zero afterward, that emptiness
        is not credible - those orders cannot all have vanished along with the
        ones just cancelled. Treat that as UNVERIFIED and refuse, distinctly
        from "a leg is still resting": one means the read could not be
        trusted, the other means the broker was asked and answered.
        """
        before = await self._working_orders()
        mine = [o for o in before if o.symbol == symbol]

        # ⚠️ M139's precondition, and it comes BEFORE any cancel. "No working
        # order for the symbol beyond its protective legs." This loop used to
        # cancel EVERY working order on the symbol, unfiltered by side or by
        # order type - so a working BUY would have been silently cancelled and
        # the close proceeded on top of it. On 24 August a working order
        # re-transmitted every 60s left the account holding 4x the intended
        # position - never send while another one works.
        intruders = [o for o in mine if not _is_protective_leg(o)]
        if intruders:
            described = ", ".join(f"{o.order_id} ({o.side} {o.order_type})" for o in intruders)
            return [], (
                f"{len(intruders)} working order(s) for {symbol} are not protective "
                f"legs: {described}. NOTHING was cancelled and NOTHING was sold - "
                f"this close cancels a bracket, and it will not act while another "
                f"order for the same symbol is working. Deal with that order first."
            )

        captured = mine

        # ⚠️ ZERO LEGS ON A HELD POSITION IS A FAILED READ, NOT A CLEAN BOOK.
        #
        # `IBAdapter.open_orders()` returns `[]` for BOTH "the book is clean"
        # and "the client could not answer" - its own docstring says so, and
        # this layer cannot tell them apart. If that happens on the FIRST
        # read, `before` and `captured` are both empty: the account-wide
        # collapse guard below cannot fire (it needs orders to have collapsed
        # FROM something), no leg can survive a cancel that never ran, and the
        # sell would have gone out with both legs still resting - the exact
        # short-position trap this whole sequence exists to prevent. A
        # read-only probe of TWS did exactly this on 1 September, reporting
        # "0 open orders" against a book carrying twenty.
        #
        # Every position this app holds carries protection, so for a symbol
        # the BROKER says is held, zero is not a credible answer. Cross-check
        # against the app's own belief and refuse.
        if not captured:
            believed = len(self.believed_legs_for(symbol))
            return [], (
                f"the broker holds {symbol} but reports NO working orders for it, and "
                f"this app believes {believed} protective leg(s) are resting. A held "
                f"position in this system always carries protection, so an empty read "
                f"means the read FAILED, not that the position is bare - open_orders() "
                f"returns the same empty list when the client cannot answer as when the "
                f"book is clean. NOTHING was cancelled and NOTHING was sold; selling on "
                f"this read could leave both legs resting and put the account short."
            )

        for leg in captured:
            try:
                await self.broker.cancel_order(leg.order_id)
            except Exception as exc:  # noqa: BLE001 - report it, never proceed
                return captured, f"cancel of leg {leg.order_id} failed: {exc}"

        after = await self._working_orders()

        if not after and len(before) > len(captured):
            return captured, (
                f"cancel of {symbol} could NOT BE VERIFIED: {len(before)} order(s) were "
                f"working account-wide before the cancel but only {len(captured)} belonged "
                f"to {symbol}, yet the post-cancel read reports the ENTIRE book empty. "
                f"Other positions' orders cannot have vanished too, so this read is not "
                f"credible - most likely a connection blip, not a clean broker. NOTHING "
                f"was sold. This is a READ FAILURE, distinct from a leg still resting: it "
                f"means the cancel's outcome is unknown, not that it succeeded."
            )

        survivors = [o for o in after if o.symbol == symbol]
        if survivors:
            ids = ", ".join(o.order_id for o in survivors)
            return captured, (
                f"{len(survivors)} leg(s) still resting after the cancel ({ids}). "
                f"NOTHING was sold - selling now would leave them resting against a "
                f"position no longer held and put the account short."
            )
        return captured, None

    async def _sign_off_or_reread(self, order: Order, operator: str) -> Order | None:
        """Sign `order` off - and treat an order ALREADY signed off as what it
        is, which is a SUCCESS.

        ⚠️ THIS CLOSER DOES NOT OWN SIGN-OFF, AND ASSUMING IT DID WAS A
        CRITICAL DEFECT.

        `OMS._announce_pending` publishes `OrderPendingSignoffEvent`, and
        `EventBus.publish` AWAITS its handlers (`asyncio.gather` over the
        handler coroutines) - so a subscriber runs to completion INSIDE
        `submit_exit_order` and `submit_protective_stop`, before either
        returns. `AutonomousExecutor._on_pending` is subscribed from
        `start()`, and `AutonomyGate.evaluate` allows EVERY sell
        unconditionally ("risk-reducing orders are not gated on appetite
        limits") and every protective stop unconditionally as well
        (`is_protective_stop`, which outranks even the closed-session check).

        In `execution_mode="auto"` the executor has therefore already signed
        the order off and handed it to the broker by the time this method is
        called. `OMS._sign_off_locked` then raises `ValueError` - from the
        "not pending sign-off" check, or from the `_transmitted` duplicate
        guard behind it - and the ORIGINAL code let that escape:

        * out of `close_position`, into the dashboard's `except`, which told
          the operator "The close FAILED ... held with NO STOP" over a sell
          that was in flight with the legs correctly gone;
        * out of `_recover`'s `submit_protective_stop` block, into the broad
          `except Exception`, which reported UNPROTECTED and "re-place it by
          hand now" over a bracket that IS live. An operator obeying that
          hand-places a SECOND full-size protective sell - the SHORT trap this
          whole feature exists to prevent, walked into from the other side.

        So: re-read the order and judge it by its ACTUAL status. Returns None
        only when the order cannot be re-read at all, which the callers treat
        as the failure it is.

        ⚠️ The `except` is NOT defensive padding around an impossible case.
        `tests/safety/test_manual_close_end_to_end.py::
        test_autonomy_signs_the_exit_off_inside_submit_exit_order` pins the
        mechanism; if that ever stops holding, this branch becomes dead code
        and should be revisited rather than left.
        """
        try:
            return await self.oms.sign_off(order.order_id, operator)
        except ValueError as exc:
            try:
                actual = self.oms.get_order(order.order_id)
            except KeyError:
                logger.critical(
                    "MANUAL CLOSE of %s: sign-off of %s was refused (%s) AND the order "
                    "could not be re-read, so its true state is unknown. Requested by %s.",
                    order.symbol,
                    order.order_id,
                    exc,
                    operator,
                )
                return None
            logger.warning(
                "MANUAL CLOSE of %s: sign-off of %s by %s was refused (%s) because the "
                "order had ALREADY been signed off - in auto mode the autonomous "
                "executor signs every sell off inside the submit call, on the event "
                "bus, before it returns. Judging it by its ACTUAL status instead: %s. "
                "The close was still requested by %s and is recorded as manual.",
                order.symbol,
                order.order_id,
                operator,
                exc,
                actual.status,
                operator,
            )
            return actual

    async def close_position(
        self,
        symbol: str,
        *,
        operator: str,
        quantity: float | None = None,
    ) -> CloseResult:
        """⚠️ There is NO `acknowledge_halt`, and its absence is the fix.

        The first version let an operator override the kill switch behind a
        second confirmation. That could not work, because the halt cannot be
        honoured half-way: `_cancel_legs` calls `broker.cancel_order()`
        DIRECTLY and never passes sign-off, so the cancel succeeded during a
        halt; the sell goes through `sign_off`, which `OMS._sign_off_locked`
        rejects unconditionally while the switch is tripped; and re-protecting
        needs sign-off too, so recovery was rejected for the same reason. The
        sequence was: legs cancelled, nothing sold, bracket unrestorable - the
        operator left holding the full position with the STOP DELETED, at the
        exact moment the system had already decided something was wrong.
        """
        if quantity is not None:
            return self._refuse(
                symbol,
                "v1 supports full close only - pass quantity=None. A partial close "
                "would leave the remainder needing a re-placed bracket.",
            )

        # ⚠️ FIRST, and before the broker is touched at all. Every refusal
        # below this line is cheap; a refusal AFTER `_cancel_legs` is not.
        if self.kill_switch.tripped:
            return self._refuse(
                symbol,
                f"the kill switch is TRIPPED: {self.kill_switch.reason}. A manual "
                f"close is refused while it is tripped - the cancel would succeed "
                f"(it bypasses sign-off) while the sell and the re-protect would "
                f"both be rejected by it, leaving {symbol} held with its stop "
                f"deleted. Reset the kill switch first, then close. NOTHING was "
                f"cancelled and NOTHING was sold.",
            )

        held = await self._held_quantity(symbol)
        if held < 0:
            return self._refuse(
                symbol,
                f"{symbol} is SHORT {abs(held):g} at the broker, not long. Closing "
                f"sends a SELL, which would DOUBLE the short rather than cover it. "
                f"Use {_SCRIPT_HINT} or cover it at the broker.",
            )
        if held == 0:
            return self._refuse(symbol, f"{symbol} is not held at the broker")

        # ⚠️ BOUND ONCE, HERE, BEFORE ANYTHING IS CANCELLED. This is not a
        # style preference. `runtime._LiveEntries` reads THROUGH to
        # `SignalToOrderBridge.position_entries()` on every access, and the
        # bridge POPS a symbol's entry the moment it observes the position
        # close - so a second lookup, taken after `_cancel_legs`, can raise
        # `KeyError` with the protection already deleted and nothing on
        # screen. One lookup, taken while refusing is still free.
        entry = self.entries.get(symbol)
        if entry is None:
            return self._refuse(
                symbol,
                f"no entry record for {symbol}, so the exit would record no closed "
                f"trade and no R-multiple. Use {_SCRIPT_HINT} instead.",
            )

        captured, failure = await self._cancel_legs(symbol)
        if failure is not None:
            return self._refuse(symbol, failure)
        cancelled = tuple(leg.order_id for leg in captured)

        quantity = await self._held_quantity(symbol)
        if quantity < 0:
            # Cannot happen from a long that was verified long moments ago,
            # which is exactly why it is CRITICAL rather than a quiet refusal:
            # the protection has already been cancelled and the account is on
            # the wrong side.
            logger.critical(
                "MANUAL CLOSE of %s: the broker now reports a SHORT %g after the "
                "legs were cancelled. Nothing was sold. Intervene by hand.",
                symbol,
                abs(quantity),
            )
            return CloseResult(
                CloseOutcome.UNPROTECTED,
                symbol,
                0.0,
                cancelled,
                f"{len(cancelled)} leg(s) were cancelled and the broker then reported "
                f"{symbol} SHORT {abs(quantity):g}. NOTHING was sold - a sell would "
                f"deepen the short. Intervene by hand now.",
            )
        if quantity == 0:
            # Nothing to sell, and that is a success rather than an error -
            # but WHICH of the two things happened is not knowable from here,
            # and the wording must not pick one. "Already flat after the legs
            # were cancelled" implied the cancels did it; a leg may equally
            # have FILLED during the race, which means the position closed at
            # the stop or the target rather than at market and lands in the
            # ledger by a different path.
            return CloseResult(
                CloseOutcome.CLOSED,
                symbol,
                0.0,
                cancelled,
                f"{symbol} was already flat when the broker was re-read: either a "
                f"protective leg FILLED during the cancel, or the position was "
                f"already gone before it. Nothing was sold. Check which - the two "
                f"close at different prices.",
            )

        order = await self.oms.submit_exit_order(
            symbol, quantity, entry.price, reason="manual_close"
        )
        if order.status == "rejected":
            return await self._recover(symbol, captured, cancelled, "the exit order was rejected")

        # ⚠️ Signed off as the OPERATOR, bypassing the AutonomyGate. The gate
        # decides whether the SYSTEM may act unattended; a human has already
        # approved this specific order in the dialog. It must never queue in the
        # blotter for a second sign-off.
        #
        # ⚠️ ...and it does NOT own sign-off. In auto mode the autonomous
        # executor has already signed this exit off, synchronously, inside
        # `submit_exit_order` above. See `_sign_off_or_reread`.
        signed = await self._sign_off_or_reread(order, operator)
        if signed is None:
            return await self._recover(
                symbol,
                captured,
                cancelled,
                "the exit order could not be signed off and could not be re-read",
            )
        if signed.status not in _SELL_IS_WORKING_OR_DONE:
            # Genuinely failed: rejected, or cancelled. Nothing is working, so
            # the position is BARE and the bracket must go back.
            return await self._recover(
                symbol, captured, cancelled, f"the exit order ended {signed.status}"
            )

        logger.warning(
            "MANUAL CLOSE: %s %g sold by %s (%s), %d protective leg(s) cancelled first",
            symbol,
            quantity,
            operator,
            signed.status,
            len(cancelled),
        )
        if signed.status == "filled":
            detail = (
                f"closed {quantity:g} {symbol} at market - the broker reports it "
                f"FILLED; {len(cancelled)} leg(s) cancelled first"
            )
        else:
            # ⚠️ Do not claim a fill the broker has not reported. IBKR answers
            # a market sell with Submitted/PreSubmitted, which maps to
            # "transmitted" - the order is live, not yet executed.
            detail = (
                f"the market sell of {quantity:g} {symbol} is WORKING at the broker "
                f"({len(cancelled)} leg(s) cancelled first). The broker has not "
                f"reported a fill yet; a market order does not rest for long, and "
                f"the ledger records the exit when the fill lands."
            )
        return CloseResult(CloseOutcome.CLOSED, symbol, quantity, cancelled, detail)

    async def _recover(
        self, symbol: str, captured: list[RestingOrder], cancelled: tuple[str, ...], why: str
    ) -> CloseResult:
        """Put the protection back. The position is BARE until this succeeds.

        ⚠️ EXCEPT when a sell is still working, in which case putting a
        bracket back is the dangerous move, not the safe one - see below.
        """
        stop = next((leg.stop_price for leg in captured if leg.stop_price), None)
        target = next((leg.limit_price for leg in captured if leg.limit_price), None)

        # ⚠️ NEVER RE-ARM OVER AN IN-FLIGHT SELL.
        #
        # A bracket is a full-size resting SELL. Place one while another sell
        # for the same symbol is still working and there are two full-size
        # sells against one position: the working one fills, the account goes
        # flat, and the bracket is left orphaned against nothing - it fires
        # and the account goes SHORT. That is the trap the entire
        # cancel-then-verify sequence exists to prevent, and recovery must not
        # walk into it from the other side.
        #
        # The status check at the call site should already have caught this
        # (a working sell reports "transmitted", which is a SUCCESS). This is
        # the belt to that pair of braces, asked of the BROKER rather than of
        # a status field, because a status field is exactly what was wrong.
        still_working = await self._working_orders()
        working_sells = [
            o for o in still_working if o.symbol == symbol and o.side.lower() == "sell"
        ]
        if working_sells:
            ids = ", ".join(o.order_id for o in working_sells)
            logger.critical(
                "MANUAL CLOSE of %s: %s, and a working sell (%s) is STILL LIVE at the "
                "broker, so NO bracket was re-placed - stacking one over an in-flight "
                "sell puts the account SHORT when that sell fills. Watch this symbol.",
                symbol,
                why,
                ids,
            )
            return CloseResult(
                CloseOutcome.UNPROTECTED,
                symbol,
                0.0,
                cancelled,
                f"{why}, but a working sell for {symbol} is still live at the broker "
                f"({ids}), so the bracket was NOT re-placed - a second full-size sell "
                f"stacked on an in-flight one puts the account SHORT when the first "
                f"fills. {symbol} currently has no protective bracket. Watch it and "
                f"act by hand.",
            )

        quantity = await self._held_quantity(symbol)
        try:
            if stop is None:
                # `submit_protective_stop` requires a float stop. Without one
                # captured there is nothing to restore, and pretending otherwise
                # would report RECOVERED over a bare position.
                raise ValueError("no stop price was captured from the original legs")
            # ⚠️ SIGN IT OFF. `submit_protective_stop` only ever creates a
            # pending_signoff order - "nothing reaches the broker without
            # sign-off". Without this the bracket is proposed and never placed,
            # and the position stays bare while the result claims RECOVERED.
            protective = await self.oms.submit_protective_stop(
                symbol, quantity, stop, take_profit_price=target
            )
            if protective.status == "rejected":
                raise RuntimeError(f"protective stop rejected for {symbol}")
            #
            # ⚠️ ...and the executor may have signed it off first, on the bus,
            # inside `submit_protective_stop`. A ValueError here used to fall
            # into the `except` below and report UNPROTECTED over a LIVE
            # bracket - see `_sign_off_or_reread`.
            placed = await self._sign_off_or_reread(protective, "auto-reprotect")
            if placed is None:
                raise RuntimeError(
                    f"the protective stop for {symbol} could not be signed off "
                    f"and could not be re-read"
                )
            if placed.status not in ("transmitted", "filled"):
                raise RuntimeError(f"protective stop ended {placed.status}")
        except Exception:  # noqa: BLE001 - the loudest branch in the file
            logger.critical(
                "MANUAL CLOSE LEFT %s UNPROTECTED: %s, and re-placing the bracket "
                "FAILED. %g shares are held with no resting stop. Re-place by hand.",
                symbol,
                why,
                quantity,
            )
            return CloseResult(
                CloseOutcome.UNPROTECTED,
                symbol,
                0.0,
                cancelled,
                f"{why}, AND the bracket could not be re-placed. {symbol} is held "
                f"with NO STOP. Re-place it by hand now.",
            )
        logger.error(
            "Manual close of %s failed (%s) - original bracket re-placed at stop=%s target=%s",
            symbol,
            why,
            stop,
            target,
        )
        return CloseResult(
            CloseOutcome.RECOVERED,
            symbol,
            0.0,
            cancelled,
            f"{why}. The original bracket was re-placed (stop {stop}, target "
            f"{target}); the position is protected and still held.",
        )
