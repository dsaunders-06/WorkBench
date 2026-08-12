"""Order Management System (spec §I): order lifecycle enforcement and the
mandatory human sign-off gate. Order/OrderStatus/BrokerAdapter/MockBroker
all exist since M1 - this builds the state machine that actually enforces
new -> pending_signoff -> transmitted -> filled/cancelled/rejected.

The safety-critical invariant: submit_order() runs the risk pipeline and,
if approved, creates an Order with status="pending_signoff" - it NEVER
calls broker.place_order(). Only sign_off(order_id, operator) (an explicit
call representing the human action) transitions to "transmitted" and calls
the broker. See tests/safety/test_no_order_without_signoff.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

from qat.config import Settings
from qat.data.broker.adapter import BrokerAdapter, BrokerFill, Order
from qat.data.broker.mock_broker import new_order_id
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal, JournalEntry
from qat.domain.events import (
    EntryPriceCorrectedEvent,
    OrderFilledEvent,
    OrderPendingSignoffEvent,
)
from qat.domain.oms.anomaly import PositionAnomalyStore
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _AbsorbedFill:
    """How much of one broker order this app has already counted (M53).

    Quantity, not just a timestamp: a partially filling order reports the same
    id repeatedly with a growing `filled_qty`, so "have I seen this id" is the
    wrong question and answering it cost a session on 5 August.
    """

    filled_at: datetime
    quantity: float
    price: float
    # False only for a record written before M53, which stored a timestamp and
    # no quantity. See _absorbed_from_json for why that must read as "finished".
    quantity_known: bool = True


def _absorbed_from_json(entry: object) -> _AbsorbedFill:
    """One `absorbed` entry, in either the M50 or the M53 shape.

    M50 wrote a bare timestamp per order id and no quantity. Such a record is
    loaded as ALREADY FINISHED, and the direction matters more than it looks.

    The alternative - treating the unknown quantity as zero absorbed - makes the
    whole of that order eligible to be counted a second time. On the file
    written on 5 August that is a 47-share CVS stop of which 30 were already
    recorded: re-absorbing it would drive the tracked quantity to -47, record a
    duplicate closed trade, and trip the kill-switch. That is M46 again, arriving
    through the migration of the fix for M50.

    So the worst this costs is one legacy fill under-recorded, in a file that is
    at most a few days old and holds only orders the previous build already
    absorbed. Under-recording is correctable by hand; double-subtracting halts a
    session.
    """
    if isinstance(entry, str):
        return _AbsorbedFill(
            filled_at=datetime.fromisoformat(entry),
            quantity=0.0,
            price=0.0,
            quantity_known=False,
        )
    if isinstance(entry, dict):
        quantity = float(entry.get("quantity") or 0.0)
        return _AbsorbedFill(
            filled_at=datetime.fromisoformat(str(entry["filled_at"])),
            quantity=quantity,
            price=float(entry.get("price") or 0.0),
            # A dict with no flag was written by the build that persisted a
            # migrated record without one. Zero absorbed is exactly that case,
            # and it has to keep reading as "finished" rather than as "none of
            # it counted yet".
            quantity_known=bool(entry.get("quantity_known", quantity > 0.0)),
        )
    raise ValueError("unrecognised absorbed-fill record")


_FILL_STATE_FILENAME = "absorbed_fills.json"
# How long an absorbed fill's id is remembered. Only needs to outlast the gap
# between the watermark and now - days, not weeks - but the file is tiny and a
# generous window costs nothing against the risk of recording a trade twice.
_ABSORBED_ID_RETENTION = timedelta(days=30)
# A resting stop is "the same level" within a RELATIVE tolerance. An absolute
# epsilon cannot serve a book holding both WFC at 87 and GS at 1,040 - one
# loose enough to absorb rounding on the latter is blind to a real move on the
# former. At 1e-4 this absorbs cent-level rounding on every price in the book.
_STOP_LEVEL_TOLERANCE = 1e-4
# The same relative test, for the same reason, applied to what an entry paid
# against what its announcement claimed (M70). Matches the tolerance
# `reconcile_entry_prices` heals to at startup, so the live correction and the
# startup one cannot disagree about whether a price needs correcting.
_ANNOUNCED_PRICE_TOLERANCE = 1e-4


class OMS:
    def __init__(
        self,
        broker: BrokerAdapter,
        risk_engine: RiskEngine,
        kill_switch: KillSwitch,
        max_order_notional: float = 50_000.0,
        symbol_allow_list: set[str] | None = None,
        entry_allow_list: set[str] | None = None,
        bus: EventBus | None = None,
        journal: DecisionJournal | None = None,
        settings: Settings | None = None,
        corporate_actions: object | None = None,
    ) -> None:
        self.broker = broker
        # Every order decision is journalled, in every execution mode (M20).
        # Until then only the autonomous executor wrote here, so a
        # recommend-mode session - the default - left no record of why an
        # order was proposed or refused. Optional so an OMS built without one
        # (every existing test) behaves exactly as before.
        self.journal = journal
        self.risk_engine = risk_engine
        self.kill_switch = kill_switch
        self.max_order_notional = max_order_notional
        self.symbol_allow_list = symbol_allow_list
        # Entries only (M61). `symbol_allow_list` above gates exits too, so it
        # cannot be used to narrow what may be OPENED without also making
        # everything else unsellable - see Settings.entry_allow_list.
        self.entry_allow_list = entry_allow_list
        self.bus = bus
        self._orders: dict[str, Order] = {}
        self._filled_quantities: dict[str, float] = {}
        self._adopted_baseline: dict[str, float] = {}
        # Stops this session attached to its own entries, kept so the portfolio
        # governor can measure aggregate risk-at-stop without re-querying open
        # orders from the broker on every candidate.
        self._position_stops: dict[str, float] = {}
        # Watermark for absorbing broker-side executions (M34), now surviving a
        # restart (M50).
        #
        # It started at construction, which reads as "a fill before this process
        # existed is already in the adopted baseline" - true of the QUANTITY and
        # false of the RECORD. Adoption re-baselines what is held; it says
        # nothing about what closed. So a stop firing while the app was down
        # left no closed trade at all, and the app restarted three times during
        # the 4 August session alone.
        #
        # `_absorbed_fills` is what makes replaying safe: the watermark alone
        # cannot say whether a fill on the boundary was already recorded, and
        # guessing either way loses a trade or records it twice.
        self.settings = settings
        self._fill_state_path = (
            Path(settings.data_dir) / _FILL_STATE_FILENAME if settings is not None else None
        )
        self._absorbed_fills: dict[str, _AbsorbedFill] = {}
        # When an order THIS app sent was first seen partially filled (M70).
        # In memory only, and deliberately: it exists to widen one query window
        # while a fill is outstanding, and an order still filling across a
        # restart is re-read from the broker by adoption anyway.
        self._own_partial_fill_stamps: dict[str, datetime] = {}
        self._fill_watch_hint: set[str] = set()
        self._last_fill_scan = self._load_fill_state()
        # Why a position ended, keyed by symbol until the fill arrives. After
        # the fact the price alone cannot separate a time stop from a signal.
        self._exit_reasons: dict[str, str] = {}
        # Broker-assigned ids for orders THIS app transmitted (M46).
        #
        # `_orders` is keyed by the app's own id, but the adapter overwrites
        # order.order_id with the broker's on transmit. So a fill arriving from
        # the broker carries an id that is never a key of `_orders`, and the
        # "did this app send it" test in absorb_broker_fills matched nothing:
        # every entry fill was absorbed as if it were a resting protective
        # order firing, counted a second time, and reconciliation answered the
        # doubled quantity with the kill-switch. That is what halted the
        # session on 4 August.
        self._broker_order_ids: set[str] = set()
        # Serialises sign-off so the "re-check cash against the CURRENT
        # balance" step below is actually a check. Concurrently signed orders
        # each fetch the balance before either has spent it, so both see the
        # same cash and both pass - the documented failure mode where several
        # individually-affordable orders collectively overdraw the account.
        # Bulk human sign-off and unattended execution both hit this path.
        self._signoff_lock = asyncio.Lock()
        # Positions in a state the ordinary path must not treat as ordinary
        # (M39/M43). Persisted, because adoption reseeds tracked quantities
        # from the broker at every launch and would otherwise launder the very
        # divergence this records.
        self.anomalies = PositionAnomalyStore(settings.data_dir if settings is not None else None)
        # The corporate-action monitor, when one is running (M39). Optional,
        # so an OMS built without it refuses exactly what it refused before.
        self.corporate_actions = corporate_actions
        # Explained divergences are logged once per session, not once per poll.
        self._explained_logged: set[str] = set()

    async def submit_order(
        self,
        candidate: OrderCandidate,
        equity: float,
        existing_weights: dict[str, float],
        existing_returns: dict[str, pd.Series],
        sector_by_symbol: dict[str, str] | None = None,
    ) -> Order:
        if self.symbol_allow_list is not None and candidate.symbol not in self.symbol_allow_list:
            return self._new_rejected_order(candidate, 0.0, "symbol not on the allow list")

        if self.entry_allow_list is not None and candidate.symbol not in self.entry_allow_list:
            return self._new_rejected_order(
                candidate, 0.0, "symbol not on the entry allow list (machinery test in progress)"
            )

        # Ahead of the kill-switch check so the refusal names the anomaly
        # rather than a generic halt, and ahead of the risk pipeline because
        # sizing against a quantity known to be wrong is wrong however
        # carefully it is done.
        anomaly = self.anomalies.get(candidate.symbol)
        if anomaly is not None:
            return self._new_rejected_order(candidate, 0.0, f"position anomaly - {anomaly.reason}")

        # Beside the anomaly check for the same reason (M39): a pending split
        # means the share count and the per-share price are both about to
        # change, so an entry sized now is sized against a number with a known
        # expiry. Refusing MORE than before is what keeps this inside the
        # freeze - the argument M60 was accepted under. Entries only; the exit
        # path below says nothing about pending actions, because a rail whose
        # effect is "the account may not de-risk" is a broken rail.
        pending = self._pending_action(candidate.symbol)
        if pending is not None:
            return self._new_rejected_order(
                candidate,
                0.0,
                f"corporate action pending - {pending} changes the size basis, so an entry "
                f"now would be sized against a price and share count about to move",
            )

        if self.kill_switch.tripped:
            return self._new_rejected_order(candidate, 0.0, "kill-switch tripped")

        # OMS owns the broker reference, so it fetches cash itself rather than
        # trusting every caller to pass it - a no-leverage rule that a caller
        # can bypass by omission is not a rule (spec M12).
        account = await self.broker.account()
        # Portfolio state is fetched here, by the component that owns the broker
        # reference, for the same reason cash is (spec M12/M15): a cap a caller
        # can bypass by not passing an argument is not a cap. Pending orders are
        # included because an order awaiting sign-off is committed exposure.
        # An unexpected failure here becomes a REJECTED ORDER, not an
        # exception (M38).
        #
        # On 3 August every one of 1,438 signals raised inside the portfolio
        # check and the exception propagated out through the event bus. The
        # bus logged "EventBus handler failed" and moved on, so the session
        # produced no orders, no refusals, no journal entries and nothing on
        # any screen. A full trading day looked from the Dashboard exactly
        # like a day with no setups.
        #
        # A rail that refuses is visible and auditable. A rail that throws is
        # neither, and this is the boundary where that distinction has to be
        # enforced: submit_order already answers every other failure with a
        # rejected order carrying a reason.
        try:
            decision = self.risk_engine.evaluate_order(
                candidate,
                equity,
                existing_weights,
                existing_returns,
                sector_by_symbol,
                available_cash=account.cash,
                positions=await self.broker.positions(),
                position_stops=self.position_stops(),
                pending_orders=self.pending_orders(),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a refusal, never swallowed
            logger.exception(
                "Risk evaluation FAILED for %s - refusing the order rather than "
                "letting the signal disappear",
                candidate.symbol,
            )
            return self._new_rejected_order(
                candidate, 0.0, f"risk evaluation failed: {type(exc).__name__}: {exc}"
            )
        if not decision.approved or decision.final_shares <= 0:
            return self._new_rejected_order(
                candidate, 0.0, decision.reason or "risk engine rejected"
            )

        # Whole shares only (M31a). Every buy leaves here with a protective
        # bracket, and Alpaca refuses a fractional quantity that carries one:
        #   {"code":42210000,"message":"fractional orders must be simple orders"}
        # The sizer works in continuous shares - 1% of equity over a stop
        # distance almost never lands on an integer - so before this, every
        # auto-signed order was refused by the broker and nothing could fill.
        #
        # Floored rather than rounded: rounding up would take slightly more
        # risk than the sizer approved, and the whole point of the sizing chain
        # is that the number it produces is a ceiling.
        shares = float(int(decision.final_shares))
        if shares < 1:
            return self._new_rejected_order(
                candidate,
                0.0,
                f"sized at {decision.final_shares:.4g} shares, below one whole share - "
                "a fractional quantity cannot carry a protective bracket",
            )

        notional = shares * candidate.price
        if notional > self.max_order_notional:
            return self._new_rejected_order(candidate, shares, "notional above the per-order cap")

        order = self._new_pending_order(
            candidate.symbol,
            candidate.side,
            shares,
            candidate.price,
            candidate.strategy,
            # The strategy's stop when it proposed one, otherwise the ATR stop
            # the sizer used. Either way the position reaches the broker with a
            # bracket rather than naked.
            stop_price=candidate.stop_price or decision.stop_price,
            take_profit_price=candidate.take_profit_price,
            earnings_date=candidate.earnings_date,
        )
        await self._announce_pending(order)
        return order

    async def submit_exit_order(
        self, symbol: str, quantity: float, price: float, reason: str = "signal"
    ) -> Order:
        """Closes an existing position at exactly `quantity` shares (spec §I).

        Separate from submit_order() rather than a flag on it, because the two
        size orders completely differently - an entry is sized by the risk
        engine, an exit is sized by what is actually held. Like submit_order(),
        this only ever creates a pending_signoff order and NEVER calls
        broker.place_order(): sign_off() remains the sole path to the broker.
        """
        if self.symbol_allow_list is not None and symbol not in self.symbol_allow_list:
            return self._new_rejected_order_for(symbol, "sell", 0.0)

        anomaly = self.anomalies.get(symbol)
        if anomaly is not None:
            if reason == "delever":
                # A trim sized against a quantity known to be wrong is the trim
                # doing the damage. Exits are allowed below; trims are not.
                return self._new_rejected_order_for(
                    symbol,
                    "sell",
                    0.0,
                    f"position anomaly - de-lever trim refused ({anomaly.reason})",
                )
            held = await self._broker_quantity(symbol)
            if held is None:
                # Refusing an exit is normally the M56c defect. Here the
                # alternative is selling a quantity this app has already
                # recorded as untrustworthy, and the refusal is a rejected
                # order carrying a reason rather than a silent gate.
                return self._new_rejected_order_for(
                    symbol,
                    "sell",
                    0.0,
                    f"position anomaly - could not read the broker to size the exit "
                    f"({anomaly.reason})",
                )
            logger.warning(
                "Exit on quarantined %s sized from the broker at %g, not the tracked %g",
                symbol,
                held,
                quantity,
            )
            quantity = held

        self._exit_reasons[symbol] = reason
        decision = self.risk_engine.evaluate_exit(symbol, quantity, price)
        if not decision.approved or decision.final_shares <= 0:
            return self._new_rejected_order_for(symbol, "sell", 0.0)

        notional = decision.final_shares * price
        if notional > self.max_order_notional:
            return self._new_rejected_order_for(symbol, "sell", decision.final_shares)

        order = self._new_pending_order(symbol, "sell", decision.final_shares, price)
        await self._announce_pending(order)
        return order

    async def _announce_pending(self, order: Order) -> None:
        """Publishes OrderPendingSignoffEvent when a bus is wired. Optional so
        an OMS built without one (every test predating M13) still works."""
        if self.bus is None or order.status != "pending_signoff":
            return
        await self.bus.publish(
            OrderPendingSignoffEvent(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                strategy=order.strategy,
            )
        )

    def pending_orders(self) -> list[Order]:
        """Orders awaiting a decision - committed exposure that has not filled."""
        return [order for order in self._orders.values() if order.status == "pending_signoff"]

    def pending_signoff_symbols(self) -> set[str]:
        """Symbols that already have an order awaiting the operator's decision -
        used by SignalToOrderBridge to avoid queueing duplicates while a
        strategy keeps re-emitting the same signal every tick."""
        return {
            order.symbol for order in self._orders.values() if order.status == "pending_signoff"
        }

    def _new_pending_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: float,
        reference_price: float | None = None,
        strategy: str | None = None,
        stop_price: float | None = None,
        take_profit_price: float | None = None,
        earnings_date: date | None = None,
    ) -> Order:
        order = Order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_id=new_order_id(),
            status="pending_signoff",
            reference_price=reference_price,
            strategy=strategy,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            earnings_date=earnings_date,
        )
        self._orders[order.order_id] = order
        self._record(order, "proposed", "awaiting sign-off")
        return order

    async def sign_off(self, order_id: str, operator: str) -> Order:
        """The only path that can move an order past pending sign-off - an
        explicit, operator-attributed action (spec §I).

        `operator` is a human in "recommend" mode and the autonomous executor's
        own identifier in "auto" mode. The distinction is recorded, never
        elided: the audit trail must show which orders a person approved.
        """
        async with self._signoff_lock:
            return await self._sign_off_locked(order_id, operator)

    async def _sign_off_locked(self, order_id: str, operator: str) -> Order:
        order = self._orders[order_id]
        if order.status != "pending_signoff":
            raise ValueError(f"Order {order_id} is not pending sign-off (status={order.status})")

        if self.kill_switch.tripped:
            order.status = "rejected"
            logger.info("Sign-off blocked by kill-switch: order=%s operator=%s", order_id, operator)
            return order

        # Re-check cash against the CURRENT balance, not the balance at
        # submission (spec M12). This is load-bearing rather than belt-and-
        # braces: with bulk sign-off, ten orders each individually affordable
        # when submitted can collectively overdraw the account when approved
        # together. Reject rather than resize - silently changing a quantity a
        # human just approved would defeat the point of the approval.
        if order.side == "buy":
            account = await self.broker.account()
            price = await self._costing_price(order)
            if price is None:
                # Fails CLOSED. An unknown price used to fall back to 0.0, which
                # made cost 0 and let this check pass unconditionally - and
                # AlpacaAdapter raises on get_market_data by design, so with a
                # real Alpaca account that was every buy, not a rare outage.
                # A no-leverage guarantee that evaporates when a quote is
                # missing is not a guarantee.
                order.status = "rejected"
                logger.warning(
                    "Sign-off blocked - no price available to cost the order: "
                    "order=%s operator=%s symbol=%s",
                    order_id,
                    operator,
                    order.symbol,
                )
                self._record(order, "rejected", "no price available to cost the order", operator)
                return order
            cost = order.quantity * price
            spendable = account.cash - self.risk_engine.settings.min_cash_reserve
            if cost > spendable:
                order.status = "rejected"
                logger.info(
                    "Sign-off blocked - insufficient cash: order=%s operator=%s "
                    "cost=%.2f spendable=%.2f",
                    order_id,
                    operator,
                    cost,
                    spendable,
                )
                self._record(
                    order,
                    "rejected",
                    f"insufficient cash: cost {cost:.2f} > spendable {spendable:.2f}",
                    operator,
                )
                return order

        # The broker decides whether this is transmitted, not us (M31a).
        #
        # `order.status = "transmitted"` used to run BEFORE the call, so when
        # place_order raised, the order kept a status saying it was live at the
        # broker. Three orders showed as transmitted in the blotter on 31 July
        # while Alpaca held nothing at all, and reconciliation could not catch
        # it: that compares FILLED quantities, and an order that never reached
        # the broker has filled nothing on either side, so both agree.
        try:
            filled = await self.broker.place_order(order)
        except Exception as exc:  # noqa: BLE001 - the broker's refusal is the answer
            order.status = "rejected"
            self._orders[order_id] = order
            logger.exception(
                "Broker refused order %s (%s %s x%s)",
                order_id,
                order.side,
                order.symbol,
                order.quantity,
            )
            self._record(order, "rejected", f"broker refused: {exc}", operator)
            return order

        # No status assignment here at all: the returned order carries the
        # broker's own, mapped by the adapter (Alpaca's accepted/new/pending
        # become "transmitted", a same-second fill becomes "filled"). Setting
        # it ourselves would overwrite the one authoritative answer with a
        # guess - which is what the pre-call assignment was.
        self._orders[order_id] = filled
        # Recorded BEFORE anything else, so an absorb running concurrently can
        # never see this fill as foreign.
        if filled.order_id:
            self._broker_order_ids.add(str(filled.order_id))

        # A protective stop is RESTING, not filled (M31d). Counting it as a
        # sell would halve the tracked quantity against a broker that still
        # holds the whole position, and reconciliation would read that as a
        # discrepancy and trip the kill-switch on the very order sent to make
        # the book safer. It records protection, and nothing else.
        if filled.is_protective_stop:
            if filled.stop_price:
                self._position_stops[filled.symbol] = float(filled.stop_price)
            self._record(filled, "signed_off", "protective stop resting at the broker", operator)
            # The target goes in the line too (M33c). This is the audit trail
            # for "is the position actually protected", and printing only the
            # stop could not distinguish an OCO whose target leg rested from
            # one where the broker accepted the order and dropped it.
            logger.info(
                "Protective %s resting: order=%s operator=%s symbol=%s qty=%s stop=%.2f%s",
                "OCO" if filled.take_profit_price else "stop",
                order_id,
                operator,
                filled.symbol,
                filled.quantity,
                filled.stop_price or 0.0,
                f" target={filled.take_profit_price:.2f}" if filled.take_profit_price else "",
            )
            return filled

        signed_qty = filled.quantity if filled.side == "buy" else -filled.quantity
        self._filled_quantities[filled.symbol] = (
            self._filled_quantities.get(filled.symbol, 0.0) + signed_qty
        )

        if filled.side == "buy" and filled.stop_price:
            self._position_stops[filled.symbol] = float(filled.stop_price)
        elif filled.side == "sell" and abs(self._filled_quantities[filled.symbol]) < 1e-6:
            # Position closed - its stop went with it at the broker, so keeping
            # it here would overstate protection on a symbol no longer held.
            self._position_stops.pop(filled.symbol, None)
        self._record(filled, "signed_off", "transmitted to the broker", operator)
        logger.info(
            "Order signed off and transmitted: order=%s operator=%s symbol=%s qty=%s",
            order_id,
            operator,
            filled.symbol,
            filled.quantity,
        )
        await self._announce_fill(filled, operator)
        return filled

    async def _announce_fill(self, order: Order, operator: str) -> None:
        """Publishes OrderFilledEvent so performance measurement has a source
        of realised outcomes. Optional bus, same as _announce_pending."""
        if self.bus is None or order.status not in ("filled", "transmitted"):
            return
        price = order.filled_price or order.reference_price
        if not price:
            return
        await self.bus.publish(
            OrderFilledEvent(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=float(price),
                strategy=order.strategy,
                stop_price=order.stop_price,
                take_profit_price=order.take_profit_price,
                operator=operator,
                reference_price=order.reference_price,
                earnings_at_entry=order.earnings_date,
                exit_reason=(
                    self._exit_reasons.pop(order.symbol, "signal") if order.side == "sell" else None
                ),
            )
        )

    async def _costing_price(self, order: Order) -> float | None:
        """Best available price for costing an order, or None if there is none.

        Preference order, most to least current: the order's own price, a live
        broker quote, then the price the order was sized against at submission.
        The last of these is what makes this workable for an execution-only
        adapter (Alpaca) that never serves quotes - it is slightly stale, but a
        slightly stale price is a real constraint, whereas no price at all is
        not a constraint of any kind.
        """
        if order.limit_price:
            return float(order.limit_price)
        if order.filled_price:
            return float(order.filled_price)

        try:
            quote = await self.broker.get_market_data(order.symbol)
        except Exception:  # noqa: BLE001 - an adapter without quotes is expected
            logger.debug("Broker cannot quote %s; using the submission price", order.symbol)
        else:
            live = float(quote.get("ask") or quote.get("last") or 0.0)
            if live > 0:
                return live

        if order.reference_price and order.reference_price > 0:
            return float(order.reference_price)
        return None

    async def reject_order(self, order_id: str, operator: str, reason: str) -> Order:
        order = self._orders[order_id]
        if order.status not in ("new", "pending_signoff"):
            raise ValueError(f"Order {order_id} cannot be rejected from status={order.status}")
        order.status = "rejected"
        logger.info("Order rejected: order=%s operator=%s reason=%s", order_id, operator, reason)
        self._record(order, "rejected_by_operator", reason, operator)
        return order

    async def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        if order.status == "transmitted":
            cancelled = await self.broker.cancel_order(order_id)
            self._orders[order_id] = cancelled
            return cancelled
        if order.status in ("filled", "cancelled", "rejected"):
            return order
        order.status = "cancelled"
        return order

    def get_order(self, order_id: str) -> Order:
        return self._orders[order_id]

    def orders(self) -> list[Order]:
        return list(self._orders.values())

    async def adopt_broker_positions(self) -> dict[str, float]:
        """Seeds the position baseline from whatever the account already holds.

        Without this, reconciliation compares an OMS that has filled nothing
        against an account that already holds positions - from an earlier
        session, another application, or a manual trade - and reads a perfectly
        healthy account as a discrepancy. That would trip the kill-switch on
        startup every time, which trains an operator to ignore the one signal
        that means "my view of the account cannot be trusted".

        Adoption is deliberately explicit and logged rather than implicit in
        the first reconciliation call: silently absorbing an unexpected
        position is exactly the event reconciliation exists to catch, so it
        must happen once, at a known point, on the record.

        **Stops are learned from the broker here, not assumed away (M31d).**
        `_position_stops` is in-memory and starts empty, so before this every
        restart re-adopted its own positions as unprotected and the governor
        counted each at full value: six holdings worth $27.8k read as ~28%
        risk-at-stop against a 5% cap, which rejects every new buy before
        sizing runs. The account is the only thing that actually knows what is
        resting, and it was already being asked - `resting_stops` existed and
        was used solely to verify.

        It also un-blinds `verify_position_stops`, which iterates
        `_position_stops` and therefore had nothing to check after a restart -
        precisely when a bracket expired overnight is most likely to have gone
        missing.

        A position with no resting stop is still absent from the record, so
        the conservative rule is unchanged. The difference is that it is now
        reached by evidence rather than by assumption.
        """
        adopted = {pos.symbol: pos.quantity for pos in await self.broker.positions()}
        self._report_anomalies_that_moved_again(adopted)
        self._filled_quantities = dict(adopted)
        self._adopted_baseline = dict(adopted)
        if not adopted:
            logger.info("No pre-existing broker positions to adopt")
            return adopted

        resting = await self._resting_stops()
        self._position_stops = {
            symbol: stop for symbol, stop in resting.items() if symbol in adopted
        }
        naked = sorted(set(adopted) - set(self._position_stops))

        # WARNING, not INFO, and the consequence is stated. Adoption is
        # routine; adoption silently consuming the entire risk-at-stop budget
        # is not, and the INFO line said only that it had happened.
        logger.warning(
            # "%d carries a stop" read as "11 carries a stop" on 10 August, and
            # left the reader to subtract for the number that actually matters -
            # how many are NAKED, which is what consumes the risk budget at full
            # value. Both figures are stated now (M82).
            "Adopted %d pre-existing broker position(s) as the reconciliation baseline: %s. "
            "%d of %d carry a stop resting at the broker, which is what their risk is measured "
            "to; %d carry none and count their full value against the aggregate cap.",
            len(adopted),
            ", ".join(f"{sym} {qty:g}" for sym, qty in sorted(adopted.items())),
            len(self._position_stops),
            len(adopted),
            len(naked),
        )
        quarantined = [a.symbol for a in self.anomalies.active() if a.symbol in adopted]
        if quarantined:
            logger.warning(
                "%d adopted position(s) are QUARANTINED: %s. New entries, de-lever trims and "
                "protection re-arming are refused for these, and their records are still "
                "uncorrected - a declaration explains a difference, it does not repair it.",
                len(quarantined),
                ", ".join(sorted(quarantined)),
            )
        if naked:
            # Its own line, at ERROR, and worded as the position being exposed
            # rather than as bookkeeping. This is the state that both loses
            # real money on a gap and silently exhausts the risk budget.
            logger.error(
                "POSITION UNPROTECTED: %s held with no stop resting at the broker. Each counts "
                "its full value against the aggregate risk-at-stop cap, so new entries may be "
                "refused until they are stopped or closed.",
                ", ".join(naked),
            )
        return adopted

    def _report_anomalies_that_moved_again(self, adopted: dict[str, float]) -> None:
        """A quarantined position whose quantity has changed AGAIN since it was
        declared (M39).

        Checked here, before `_filled_quantities` is overwritten, because
        adoption is precisely what destroys the evidence: it reseeds tracked
        quantities wholesale from the broker, so a second change would
        otherwise be absorbed into the new baseline and never seen. The
        declaration no longer explains what is held, so reconciliation will
        halt on it - which is correct, and the operator should know why before
        it happens rather than afterwards.
        """
        moved_again = [
            anomaly
            for anomaly in self.anomalies.active()
            if abs(adopted.get(anomaly.symbol, 0.0) - anomaly.broker_quantity) > 1e-6
        ]
        if not moved_again:
            return
        logger.error(
            "QUARANTINED POSITION MOVED AGAIN since it was declared: %s. The declaration no "
            "longer explains what the broker holds, so reconciliation will halt on these "
            "until they are re-declared or cleared.",
            ", ".join(
                f"{anomaly.symbol} declared={anomaly.broker_quantity:g} "
                f"now={adopted.get(anomaly.symbol, 0.0):g}"
                for anomaly in sorted(moved_again, key=lambda a: a.symbol)
            ),
        )

    async def _resting_stops(self) -> dict[str, float]:
        """What the broker says is actually working, or nothing it can vouch for.

        An adapter without the capability must not be read as "no stops rest
        anywhere" - that is indistinguishable from a genuinely naked book and
        would be acted on as if it were one.
        """
        source = getattr(self.broker, "resting_stops", None)
        if source is None:
            return {}
        try:
            resting: dict[str, float] = await source()
        except Exception:
            # A failed query is not evidence of an unprotected book. Startup
            # continues; the positions keep the conservative full-value
            # treatment they would have had anyway.
            logger.exception("Could not read resting stops from the broker during adoption")
            return {}
        return resting

    @property
    def adopted_baseline(self) -> dict[str, float]:
        """Positions that were already held when this session started. Not
        opened by this application, so nothing here carries a stop it placed."""
        return dict(self._adopted_baseline)

    def filled_quantities(self) -> dict[str, float]:
        """What this app believes is held, per symbol.

        A copy, and public, so a screen can show the app's own view alongside
        the broker's without reaching into `_filled_quantities` - the number a
        reconciliation difference is one half of.
        """
        return dict(self._filled_quantities)

    def position_stops(self) -> dict[str, float]:
        """Protective stops this session attached to its own entries.

        Adopted positions are absent by construction: this app did not open
        them and has no idea what, if anything, protects them. PortfolioGovernor
        treats a missing stop as full-value-at-risk rather than assuming a
        stop exists, which is the conservative reading.
        """
        return dict(self._position_stops)

    async def verify_position_stops(self) -> list[str]:
        """Checks that the stops this app believes in are actually resting (M31b).

        `_position_stops` is a belief, and the portfolio governor sizes new
        positions against it: a position with a known stop risks only the
        distance to that stop, one without risks its entire value. So a stop
        that has quietly stopped existing makes the whole book look safer than
        it is.

        On 31 July that happened to six positions at once. The brackets were
        submitted DAY, their take-profit legs expired at the close, and Alpaca
        cancelled the paired stops with them. Reconciliation saw nothing,
        because it compares FILLED QUANTITIES and an expired protective leg
        changes none of them.

        Unprotected positions are dropped from the record rather than kept,
        so the governor falls back to treating them as fully at risk - the
        existing "unknown protection is no protection" rule, now reached by
        evidence instead of assumption. A position whose stop MOVED is a
        different case: it is still protected, so the recorded level is
        replaced by what the broker actually says rather than dropped.

        Both are returned. The caller's question is "which symbols is my
        protection record no longer trustworthy for", and both answer yes.

        The level check exists because the presence check was not one. Until
        M39 this compared `symbol not in resting`, so a stop resting at a
        DIFFERENT price passed - and `_position_stops` is the denominator of
        every risk-at-stop figure the governor gates new entries on, so a
        belief wrong by a factor mis-states the aggregate for the whole book.

        A broker that cannot answer returns nothing, and nothing is changed:
        an adapter without the capability must not be read as "no stops rest
        anywhere", which would drop every stop the app holds.
        """
        resting_source = getattr(self.broker, "resting_stops", None)
        if resting_source is None:
            return []
        resting = await resting_source()
        if not resting and not self._position_stops:
            return []

        held = {pos.symbol for pos in await self.broker.positions() if abs(pos.quantity) > 0}
        lost: list[str] = []
        drifted: list[tuple[str, float, float]] = []
        for symbol, believed in list(self._position_stops.items()):
            if symbol not in held:
                continue
            actual = resting.get(symbol)
            if actual is None:
                lost.append(symbol)
                continue
            if abs(actual - believed) > _STOP_LEVEL_TOLERANCE * abs(believed):
                drifted.append((symbol, believed, actual))

        for symbol in lost:
            self._position_stops.pop(symbol, None)
        for symbol, _believed, actual in drifted:
            # Replaced, not dropped. The position IS protected - just not where
            # this app thought - and the broker is the authority on what rests.
            # Dropping it would count a protected position at full value and
            # overstate the aggregate the governor gates new entries on.
            self._position_stops[symbol] = actual

        if lost:
            logger.error(
                "POSITION UNPROTECTED: %s held with no stop resting at the broker. The stop "
                "this app recorded is gone, so these now count their full value as at risk",
                ", ".join(sorted(lost)),
            )
        if drifted:
            # ERROR, and named with both levels. A protective level moving
            # without this app moving it is exactly as significant as one
            # disappearing, and until M39 nothing looked for it at all.
            logger.error(
                "PROTECTION LEVEL CHANGED at the broker: %s. This app did not move these, so "
                "risk-at-stop was being measured against the wrong distance",
                ", ".join(
                    f"{symbol} believed={believed:g} resting={actual:g}"
                    for symbol, believed, actual in sorted(drifted)
                ),
            )
        return sorted(lost + [symbol for symbol, _, _ in drifted])

    def has_live_buy(self, symbol: str) -> bool:
        """Whether a buy for this symbol is already awaiting sign-off or in
        flight at the broker (M46).

        The anti-pyramiding guard asked the broker for POSITIONS, and a
        transmitted order that has not filled yet is not a position. On
        4 August two seconds separated MS being transmitted and a fresh signal
        arriving; the second signal saw no holding and opened the same trade
        again, for 82 shares against an intended 41.

        The same reasoning the governor already applies to exposure: an order
        that has been committed is committed, whether or not it has filled.
        """
        return any(
            order.symbol == symbol
            and order.side == "buy"
            and order.status in {"pending_signoff", "transmitted"}
            for order in self._orders.values()
        )

    async def naked_positions(self) -> list[tuple[str, float]]:
        """Held positions with no stop resting at the broker (M31d).

        Asked of the account rather than of `_position_stops`, so the answer
        does not depend on what this process happens to remember - which after
        a restart is nothing.
        """
        resting = await self._resting_stops()
        return [
            (pos.symbol, pos.quantity)
            for pos in await self.broker.positions()
            if abs(pos.quantity) > 0 and pos.symbol not in resting
        ]

    async def _broker_quantity(self, symbol: str) -> float | None:
        """What the broker says is held, or None if it cannot be asked.

        None and zero are different answers and must not collapse: zero means
        the position is gone, None means this app does not know - and sizing an
        exit on a guess is what the quarantine exists to prevent.
        """
        try:
            positions = await self.broker.positions()
        except Exception:
            logger.exception("Could not read the broker to size an exit on %s", symbol)
            return None
        return next(
            (abs(pos.quantity) for pos in positions if pos.symbol == symbol),
            0.0,
        )

    async def submit_protective_stop(
        self,
        symbol: str,
        quantity: float,
        stop_price: float,
        take_profit_price: float | None = None,
    ) -> Order:
        """Proposes a resting protective stop on a position already held (M31d).

        Every stop before this rode in as a bracket leg on an entry, so a
        position whose legs died had no way to get another one - the state all
        six holdings were in on 1 August, after the take-profit legs expired at
        Friday's close and Alpaca cancelled the paired stops with them.

        Pending sign-off like everything else. This creates protection rather
        than exposure, which is an argument for letting it through unattended
        and not an argument for bypassing the gate: it still sells shares if
        the price reaches it, and the one rule with no exceptions is that
        nothing reaches the broker without sign-off.
        """
        if quantity <= 0:
            return self._new_rejected_order_for(symbol, "sell", 0.0)
        if stop_price <= 0:
            return self._new_rejected_order_for(symbol, "sell", 0.0)

        # Never two protective orders for one symbol (M33d).
        #
        # Belt and braces against the detection query being wrong, which it
        # was: an OCO's stop leg rests at status `held` and nested under its
        # parent, so a CRWD position carrying a good OCO read as unprotected
        # and a second one was proposed. Signed, that is 32 shares of resting
        # sell orders against a 16-share position.
        #
        # The deeper lesson is that "the broker says nothing is resting" was
        # never safe to act on unilaterally, so the count is enforced here as
        # well as measured there.
        already_pending = next(
            (
                existing
                for existing in self.pending_orders()
                if existing.symbol == symbol and existing.is_protective_stop
            ),
            None,
        )
        if already_pending is not None:
            logger.warning(
                "Protective order for %s already pending (%s) - not proposing another",
                symbol,
                already_pending.order_id,
            )
            return already_pending

        order = Order(
            symbol=symbol,
            side="sell",
            quantity=quantity,
            order_id=new_order_id(),
            status="pending_signoff",
            stop_price=stop_price,
            # Sent as one OCO when a target is known, so the two levels cancel
            # each other at the broker instead of both being able to fill.
            take_profit_price=take_profit_price,
            order_type="stop",
        )
        self._orders[order.order_id] = order
        logger.warning(
            "Protective %s proposed for unprotected position %s x%g at %.2f%s - awaiting sign-off",
            "OCO" if take_profit_price else "stop",
            symbol,
            quantity,
            stop_price,
            f", target {take_profit_price:.2f}" if take_profit_price else "",
        )
        self._record(order, "pending_signoff", "protective stop for an unprotected position", None)
        await self._announce_pending(order)
        return order

    def _load_fill_state(self) -> datetime:
        """The watermark the previous run reached, and what it had recorded.

        No file, no settings, or an unreadable file all mean "start from now",
        which is exactly the pre-M50 behaviour: nothing is replayed, and nothing
        can be double-recorded either. Degrading to the old behaviour is the
        right failure here, because the old behaviour was merely incomplete
        rather than wrong.
        """
        if self._fill_state_path is None:
            return datetime.now(UTC)
        try:
            raw = json.loads(self._fill_state_path.read_text(encoding="utf-8"))
            watermark = datetime.fromisoformat(raw["watermark"])
            absorbed = {
                str(order_id): _absorbed_from_json(entry)
                for order_id, entry in (raw.get("absorbed") or {}).items()
            }
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return datetime.now(UTC)
        self._absorbed_fills = absorbed
        logger.info(
            "Broker-fill watermark restored to %s - executions since then are replayed for "
            "the record, with %d already-recorded fill(s) remembered",
            watermark.isoformat(timespec="seconds"),
            len(absorbed),
        )
        return watermark

    def _save_fill_state(self) -> None:
        """Written after each absorb pass, not at shutdown: the restart this
        exists for is the one nobody planned."""
        if self._fill_state_path is None:
            return
        cutoff = datetime.now(UTC) - _ABSORBED_ID_RETENTION
        self._absorbed_fills = {
            order_id: seen
            for order_id, seen in self._absorbed_fills.items()
            if seen.filled_at >= cutoff
        }
        payload = {
            "watermark": self._last_fill_scan.isoformat(),
            "absorbed": {
                order_id: {
                    "filled_at": seen.filled_at.isoformat(),
                    "quantity": seen.quantity,
                    "price": seen.price,
                    # Written, or a migrated record round-trips back to
                    # "0 absorbed, quantity known" and the whole order becomes
                    # eligible again on the NEXT restart - the same hazard
                    # _absorbed_from_json exists to close, reintroduced through
                    # the save path because only the load path was fixed.
                    "quantity_known": seen.quantity_known,
                }
                for order_id, seen in self._absorbed_fills.items()
            },
        }
        try:
            self._fill_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._fill_state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("Could not persist the broker-fill watermark")

    async def missed_fills(self) -> list[BrokerFill]:
        """Executions since the watermark that this app has not recorded (M50).

        Read-only on purpose. The caller needs to see what is about to be
        absorbed BEFORE it is, because a position that closed while the app was
        down is gone from the broker - so nothing at startup would otherwise
        rebuild the entry lot its exit has to close against, and the replayed
        trade would record nothing. See SignalToOrderBridge.replay_missed_exits.
        """
        source = getattr(self.broker, "recent_fills", None)
        if source is None:
            return []
        try:
            fills = await source(self._last_fill_scan, self._symbols_to_watch_for_fills())
        except Exception:
            logger.exception("Could not read broker fills missed while the app was not running")
            return []
        return [fill for fill in fills if self._is_foreign_unrecorded(fill)]

    def _is_foreign_unrecorded(self, fill: BrokerFill) -> bool:
        """Whether this fill is one this app neither sent nor has fully
        recorded."""
        if fill.order_id in self._broker_order_ids or fill.order_id in self._orders:
            # This app sent it and sign_off already counted it. Both sets are
            # checked because an order carries the app's id until it is
            # transmitted and the broker's afterwards.
            return False
        prior = self._absorbed_fills.get(fill.order_id)
        if prior is not None:
            if not prior.quantity_known:
                # Written before M53, so how much was counted is unrecoverable.
                # Treated as finished - see _absorbed_from_json.
                return False
            # Seen before - but seen is not the same as finished. An order that
            # is still filling reports the SAME id with a larger filled_qty, so
            # the question is whether anything NEW has executed, not whether the
            # id is familiar. `_unabsorbed_part` answers that.
            return fill.quantity > prior.quantity + 1e-9
        return fill.filled_at > self._last_fill_scan

    def _fill_query_floor(self) -> datetime:
        """How far back to ask, which is NOT simply the watermark (M53).

        An order still filling keeps the `filled_at` of its first execution, and
        that stamp is already behind the watermark by the time the rest of it
        completes. Asking from the watermark therefore excludes the very order
        whose remainder is outstanding - the adapter drops it before the OMS
        ever sees it, so the delta arithmetic below never gets the chance to
        run. That is what let 17 CVS shares vanish on 5 August.

        So the floor reaches back past every fill still remembered. Re-reading a
        completed one costs nothing: its cumulative quantity is unchanged, the
        delta is zero, and it is skipped. `_absorbed_fills` is pruned to 30
        days, and the query is bounded by symbol, so the window cannot grow
        without limit.

        **The app's OWN partials need the same reach, and were not getting it
        (M70).** `_absorbed_fills` holds foreign executions only - an order this
        app sent is never absorbed - so an entry still filling was covered by
        neither term. Its price would be corrected to the average of the first
        piece and then never again, because the row carrying the final average
        still has the first piece's stamp and falls outside the window. The
        stamp is dropped as soon as the order is complete, so this reaches back
        only while something genuinely is outstanding.
        """
        floor = self._last_fill_scan
        stamps = [seen.filled_at for seen in self._absorbed_fills.values()]
        stamps.extend(self._own_partial_fill_stamps.values())
        if stamps:
            # A second before, because the brokers' filters are exclusive and an
            # order's remainder carries the same stamp as its first piece.
            floor = min(floor, min(stamps) - timedelta(seconds=1))
        return floor

    def _unabsorbed_part(self, fill: BrokerFill) -> BrokerFill | None:
        """The part of this execution not already counted, or None (M53).

        A protective order does not always fill in one go. On 5 August a CVS
        stop gapped through at the open and filled 47 shares in pieces; this
        method's absence meant the app read it mid-fill, absorbed 30, recorded
        the id as done, and never counted the remaining 17. Tracked 17 against a
        broker holding 0 is a discrepancy, and reconciliation answered it with
        the kill-switch - eight minutes into the first session that had ever
        recorded a closed trade.

        `BrokerFill.quantity` is CUMULATIVE (`filled_qty`), and so is `price`
        (`filled_avg_price`). The increment's own price therefore has to be
        recovered from the two running averages rather than assumed to be the
        latest one - otherwise a second piece filled at a different price would
        be recorded at the blended average, and the realised P&L would be wrong
        by the difference.
        """
        prior = self._absorbed_fills.get(fill.order_id)
        if prior is None:
            return fill
        if not prior.quantity_known:
            return None
        delta = fill.quantity - prior.quantity
        if delta <= 1e-9:
            return None
        # value_new = total_value - value_already_counted
        increment_value = (fill.price * fill.quantity) - (prior.price * prior.quantity)
        price = increment_value / delta if delta > 0 else fill.price
        return replace(fill, quantity=delta, price=price)

    def watch_symbols_for_fills(self, symbols: Iterable[str]) -> None:
        """Symbols to ask about even though nothing here tracks a position in
        them (M50).

        A stop that fired while the app was down leaves NOTHING behind on this
        side: the broker no longer lists the position, and a fresh process
        adopts a book that never mentions it. Both of the obvious symbol sets
        are therefore empty for precisely the symbol whose exit needs recording.

        The caller that does know is the one holding the entry records - it
        believed it held these positions when it last ran. Registered once at
        startup and bounded by the number of positions ever open at a time.
        """
        self._fill_watch_hint.update(str(symbol) for symbol in symbols)

    def _symbols_to_watch_for_fills(self) -> list[str]:
        """Symbols a broker-side execution could plausibly arrive for (M48).

        The app's TRACKED quantities, not the broker's positions. A stop firing
        is precisely the event that removes a position from the broker's list,
        so asking about what the broker still holds would exclude the one
        symbol we most need to hear about - the same shape of mistake as
        bounding the protection query by `status=open`.

        Adopted positions are included by construction: `_filled_quantities`
        holds them from startup, and their protection was placed in an earlier
        session. Those are the holdings whose fills the old `after=submitted_at`
        window could never have returned.
        """
        symbols = {
            symbol for symbol, quantity in self._filled_quantities.items() if abs(quantity) > 1e-6
        }
        # Anything with an order in flight too, so a fill cannot arrive for a
        # symbol that has no tracked quantity yet.
        symbols.update(order.symbol for order in self._orders.values())
        # And anything a caller believes it held but this process has no record
        # of - see watch_symbols_for_fills.
        symbols.update(self._fill_watch_hint)
        return sorted(symbols)

    async def absorb_broker_fills(self, record_only: bool = False) -> list[BrokerFill]:
        """Records executions the broker performed that this app did not send.

        Only fills for orders this process did not originate are applied - an
        order the app transmitted has already been counted through sign_off,
        and counting it twice would create the very discrepancy this exists to
        prevent.

        Publishing OrderFilledEvent is the point as much as the arithmetic is:
        it is what the trade ledger listens to, so a stop-out or a target
        finally becomes a CLOSED TRADE on the Performance tab instead of a
        position that silently vanished.

        A broker that cannot answer changes nothing, and neither does a failed
        query - the previous behaviour is exactly preserved.
        """
        source = getattr(self.broker, "recent_fills", None)
        if source is None:
            return []
        # Taken BEFORE the query, and it is the value the watermark becomes
        # (M88). A stamp taken after the pass excludes everything that executed
        # during it: the query has already been answered, and the next floor
        # starts above the execution. Protective fills are the only exits this
        # system has, so one lost that way is a closed trade that never exists.
        scan_started = datetime.now(UTC)
        try:
            fills = await source(self._fill_query_floor(), self._symbols_to_watch_for_fills())
        except Exception:
            logger.exception("Could not read recent broker fills")
            return []

        absorbed: list[BrokerFill] = []
        for raw in fills:
            if not self._is_foreign_unrecorded(raw):
                # Ours, and already counted - but not therefore worthless. This
                # is the only place the price we actually PAID arrives for an
                # order this app sent, and it used to be dropped here (M70).
                await self._correct_announced_price(raw)
                continue
            fill = self._unabsorbed_part(raw)
            if fill is None:
                continue
            # The M50 trap, and the reason this is not simply "persist the
            # watermark". A fill from before the baseline was taken is ALREADY
            # in `_filled_quantities`, because adoption read it from the
            # broker's own position list. Applying it again subtracts the same
            # shares twice and trips the kill-switch on arithmetic - M46 by a
            # different route. It still has to be RECORDED: adoption re-baselines
            # what is held and says nothing about what closed.
            if not record_only:
                signed = fill.quantity if fill.side == "buy" else -fill.quantity
                self._filled_quantities[fill.symbol] = (
                    self._filled_quantities.get(fill.symbol, 0.0) + signed
                )
                if abs(self._filled_quantities.get(fill.symbol, 0.0)) < 1e-6:
                    # Flat: whatever was protecting it went with it at the broker.
                    self._position_stops.pop(fill.symbol, None)
            prior = self._absorbed_fills.get(raw.order_id)
            self._absorbed_fills[raw.order_id] = _AbsorbedFill(
                filled_at=raw.filled_at,
                quantity=(prior.quantity if prior else 0.0) + fill.quantity,
                price=raw.price,
            )
            absorbed.append(fill)
            logger.warning(
                "BROKER-SIDE FILL absorbed: %s %g %s at %.2f (order %s) - %s%s",
                fill.side,
                fill.quantity,
                fill.symbol,
                fill.price,
                fill.order_id,
                # Branched on side (M81). This was hard-coded for the sell case
                # M34 was written for, so a position opened AT THE BROKER while
                # the app was down - which arrives through the same path -
                # was announced as "a resting protective order executed, and
                # this is now a closed trade". Both clauses were false, and the
                # second was falsifiable against closed_trades.csv.
                (
                    "a resting protective order executed, and this is now a closed trade"
                    if fill.side == "sell"
                    else (
                        "a position was OPENED at the broker that this application did not "
                        "send. It opens a lot carrying the price paid, but no stop and no "
                        "strategy are known for it, so a trade closed from it will have no "
                        "R-multiple and will count towards no strategy's promotion evidence"
                    )
                ),
                (
                    ". It executed while this application was not running, so it is recorded "
                    "but not re-counted"
                    if record_only
                    else ""
                ),
            )
            if self.bus is not None:
                await self.bus.publish(
                    OrderFilledEvent(
                        order_id=fill.order_id,
                        symbol=fill.symbol,
                        side=fill.side,
                        quantity=fill.quantity,
                        price=fill.price,
                        strategy=None,
                        operator="broker (protective order)",
                        exit_reason=self._protective_exit_reason(fill),
                        # When it FILLED, not when we noticed (M50). The ledger
                        # stamps closed_at from this, and a replayed exit can be
                        # days older than the pass that finds it - which would
                        # put a holding period nobody held into the evidence.
                        ts=fill.filled_at,
                    )
                )

        if record_only and absorbed:
            # The M50 trap, and why this is not simply "persist the watermark".
            # These executions happened before this process read the account, so
            # `_filled_quantities` ALREADY reflects them - applying them again
            # would subtract the same shares twice and trip the kill-switch on
            # arithmetic, which is M46 arriving by a different route.
            #
            # Rather than deciding from timestamps whether a fill is inside the
            # baseline - two clocks microseconds apart cannot answer that, and
            # guessing either way trips the kill-switch from one side or the
            # other - the quantities are simply re-read from the broker, which
            # is the only thing that actually knows.
            await self._resync_tracked_quantities()

        # Advanced and persisted only after the pass, so a crash mid-loop
        # replays rather than skips - and `_absorbed_fills` is what makes a
        # replay safe to repeat. The VALUE is the instant the pass began rather
        # than the instant it ended (M88): an end stamp replays nothing and
        # skips whatever executed while the pass ran. A begin stamp replays
        # strictly more, which is the same property the crash argument relies
        # on, so this strengthens that reasoning rather than weakening it.
        self._last_fill_scan = scan_started
        self._save_fill_state()
        return absorbed

    def _order_the_broker_calls(self, broker_order_id: str) -> Order | None:
        """The app's record of an order, found by the id the BROKER uses.

        `_orders` is keyed by the app's own id and the adapter overwrites
        `order.order_id` with the broker's on transmit, so the key and the
        attribute disagree for every transmitted order - which is exactly the
        M46 mismatch. Both are checked, in that order: the attribute is the one
        a fill can be matched on, and the key is what an adapter that preserves
        the id leaves behind.
        """
        for order in self._orders.values():
            if str(order.order_id) == broker_order_id:
                return order
        return self._orders.get(broker_order_id)

    async def _correct_announced_price(self, raw: BrokerFill) -> None:
        """Announces what an order this app sent actually filled at (M70).

        `_announce_fill` publishes at "transmitted" as well as at "filled", and
        at transmit there is no fill price - so what went out was the price the
        order was SIZED against. Alpaca acknowledges asynchronously, so that is
        the normal case rather than the exceptional one: 8 of the 10 positions
        held on 8 August recorded a price the account never paid, AMD by 141
        bps.

        `reconcile_entry_prices` heals that at the next startup. A position
        opened and closed inside one session never reaches a next startup - its
        ClosedTrade is already written, against a basis that is wrong in both
        the P&L and the R-multiple denominator. This is that gap.

        Nothing here touches a quantity. The fill was counted at sign-off, and
        counting it again is the M46 discrepancy that halted 4 August.
        """
        if self.bus is None or raw.side != "buy" or raw.price <= 0:
            return
        order = self._order_the_broker_calls(raw.order_id)
        if order is None or order.side != "buy":
            return
        # Remembered only while the order is genuinely still filling, so
        # `_fill_query_floor` reaches back far enough to see the row carrying
        # the final average - which keeps the FIRST execution's stamp.
        if raw.quantity + 1e-9 < order.quantity:
            self._own_partial_fill_stamps[raw.order_id] = raw.filled_at
        else:
            self._own_partial_fill_stamps.pop(raw.order_id, None)
        announced = order.filled_price or order.reference_price
        if not announced or announced <= 0:
            # Nothing was published to correct - `_announce_fill` returns early
            # without a price, so no entry record was ever built from one.
            return
        if abs(raw.price - announced) <= _ANNOUNCED_PRICE_TOLERANCE * abs(announced):
            return
        if self.anomalies.is_quarantined(raw.symbol):
            # The rule `reconcile_entry_prices` already applies. A corporate
            # action changes what the broker reports legitimately, and a
            # position in that state is one M60 exists to stop anything writing
            # to - including this.
            return
        # Recorded on the order too, so the next poll compares against the
        # corrected figure and stays quiet. A partial that later completes
        # reports a larger cumulative average and corrects again, which is what
        # keeping the guard on DIFFERENCE rather than on having-run-once buys.
        order.filled_price = raw.price
        logger.warning(
            "ENTRY PRICE CORRECTED: %s filled at %.4f, announced at %.4f (%+.1f bps). The "
            "announcement went out at transmit, where the only price available is the one the "
            "order was SIZED against - so the entry record, the open lot's cost basis and every "
            "R-multiple measured from it were wrong by that difference.",
            raw.symbol,
            raw.price,
            announced,
            10_000.0 * (raw.price - announced) / announced,
        )
        await self.bus.publish(
            EntryPriceCorrectedEvent(
                order_id=raw.order_id,
                symbol=raw.symbol,
                price=raw.price,
                announced_price=float(announced),
            )
        )

    async def _resync_tracked_quantities(self) -> None:
        """Re-reads the position baseline from the broker after a replay.

        Deliberately quiet, unlike `adopt_broker_positions`: adoption is the
        event worth announcing, and this is the same read repeated moments later
        for a known reason.
        """
        try:
            positions = await self.broker.positions()
        except Exception:
            logger.exception("Could not re-read positions after replaying missed executions")
            return
        self._filled_quantities = {pos.symbol: pos.quantity for pos in positions}
        held = set(self._filled_quantities)
        for symbol in [s for s in self._position_stops if s not in held]:
            # Flat: whatever was protecting it went with it at the broker.
            self._position_stops.pop(symbol, None)

    def _protective_exit_reason(self, fill: BrokerFill) -> str:
        """Which leg of the OCO fired, decided by the level it landed on.

        A stop fills at or below its trigger and a target at or above its
        limit, so the two are separable by price - and this is the only
        distinction available, because neither order was sent from here.
        """
        stop = self._position_stops.get(fill.symbol)
        if stop is not None and fill.price <= stop * 1.02:
            return "stop"
        return "target"

    async def check_reconciliation(self) -> bool:
        """Compares OMS-tracked filled quantities against broker-reported
        positions; a mismatch trips the kill-switch (spec §I). Returns True
        if a mismatch was found.

        Call adopt_broker_positions() once at startup first, or an account with
        any pre-existing holding reads as a mismatch immediately.

        A divergence the anomaly store EXPLAINS is not a mismatch (M39). The
        return value keeps its meaning - "a halting mismatch was found" - so
        ReconciliationMonitor, which publishes KillSwitchEvent on True, needs
        no change. An explained symbol is still quarantined; explanation and
        quarantine are separate questions.
        """
        # Broker-side executions are absorbed BEFORE anything is judged (M34).
        #
        # A resting stop or target filling closes a position with no order
        # leaving this process, so nothing publishes OrderFilledEvent. Without
        # this step the comparison below sees tracked=58 against broker=0 and
        # trips the kill-switch on a stop doing exactly its job - and the trade
        # ledger never records the closed trade, so the promotion gate
        # accumulates nothing from the only exits this system actually has.
        await self.absorb_broker_fills()

        # Protection is checked alongside quantity, because they fail in
        # different ways and only one of them was ever being watched.
        await self.verify_position_stops()
        broker_positions = {pos.symbol: pos.quantity for pos in await self.broker.positions()}
        symbols = set(self._filled_quantities) | set(broker_positions)
        divergent = {
            symbol: (self._filled_quantities.get(symbol, 0.0), broker_positions.get(symbol, 0.0))
            for symbol in symbols
            if abs(self._filled_quantities.get(symbol, 0.0) - broker_positions.get(symbol, 0.0))
            > 1e-6
        }
        explained = {
            symbol: pair
            for symbol, pair in divergent.items()
            if self.anomalies.explains(symbol, pair[1])
        }
        unexplained = {
            symbol: pair for symbol, pair in divergent.items() if symbol not in explained
        }

        for symbol, (tracked, actual) in sorted(explained.items()):
            if symbol in self._explained_logged:
                continue
            self._explained_logged.add(symbol)
            anomaly = self.anomalies.get(symbol)
            logger.warning(
                "%s tracked=%g broker=%g is explained by a declared position anomaly (%s) - "
                "not halting. The symbol stays quarantined and its records are still "
                "uncorrected.",
                symbol,
                tracked,
                actual,
                anomaly.reason if anomaly is not None else "reason unavailable",
            )

        if unexplained:
            logger.error(
                "Broker reconciliation mismatch: %s",
                ", ".join(
                    f"{sym} tracked={tracked:g} broker={actual:g}"
                    for sym, (tracked, actual) in sorted(unexplained.items())
                ),
            )
            self.kill_switch.check_reconciliation()
        return bool(unexplained)

    def record_unsized_signal(
        self, symbol: str, side: Literal["buy", "sell"], strategy: str | None, reason: str
    ) -> Order:
        """A signal that could not even be SIZED, recorded as a refusal (M54).

        Everything upstream of the risk engine used to fail silently: if the
        account could not be read there was no candidate to reject, so no
        rejected order was created and nothing reached the journal. The signal
        left no trace but a stack trace.

        This produces the same rejected order any other refusal does, so the
        audit trail answers "why did nothing happen" with a reason rather than
        with a gap. It is deliberately a REJECTION and not a retry: the next
        tick will re-emit the signal if the condition still holds, and inventing
        a retry loop here would hide a broker outage rather than record it.
        """
        return self._new_rejected_order_for(symbol, side, 0.0, reason, strategy=strategy)

    def _pending_action(self, symbol: str) -> str | None:
        """A one-line description of a pending corporate action, or None (M39).

        Returns the DESCRIPTION rather than the record, so this module needs no
        import from the corporate-actions package and the refusal reason reads
        the same wherever it is shown.
        """
        monitor = self.corporate_actions
        if monitor is None:
            return None
        action = monitor.pending_action(symbol)  # type: ignore[attr-defined]
        if action is None:
            return None
        describe = getattr(action, "describe", None)
        return describe() if callable(describe) else str(action)

    def _new_rejected_order(
        self, candidate: OrderCandidate, quantity: float, reason: str = "rejected"
    ) -> Order:
        return self._new_rejected_order_for(
            candidate.symbol, candidate.side, quantity, reason, strategy=candidate.strategy
        )

    def _new_rejected_order_for(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: float,
        reason: str = "rejected",
        strategy: str | None = None,
    ) -> Order:
        order = Order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_id=new_order_id(),
            status="rejected",
            strategy=strategy,
        )
        self._orders[order.order_id] = order
        self._record(order, "rejected", reason)
        return order

    def _record(self, order: Order, outcome: str, reason: str, operator: str | None = None) -> None:
        """One line in the decision journal. Never raises: a journal write
        failure must not abort an order path that has already decided."""
        if self.journal is None:
            return
        try:
            self.journal.record(
                JournalEntry(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    outcome=outcome,
                    reason=reason,
                    quantity=order.quantity,
                    price=order.reference_price or order.filled_price,
                    strategy=order.strategy,
                    entity_name=operator or "",
                    execution_mode=self.risk_engine.settings.execution_mode,
                )
            )
        except Exception:  # noqa: BLE001 - journalling is never load-bearing
            logger.warning("Could not journal the %s decision for %s", outcome, order.order_id)
