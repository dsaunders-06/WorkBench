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
import logging
from typing import Literal

import pandas as pd

from qat.data.broker.adapter import BrokerAdapter, Order
from qat.data.broker.mock_broker import new_order_id
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal, JournalEntry
from qat.domain.events import OrderFilledEvent, OrderPendingSignoffEvent
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

logger = logging.getLogger(__name__)


class OMS:
    def __init__(
        self,
        broker: BrokerAdapter,
        risk_engine: RiskEngine,
        kill_switch: KillSwitch,
        max_order_notional: float = 50_000.0,
        symbol_allow_list: set[str] | None = None,
        bus: EventBus | None = None,
        journal: DecisionJournal | None = None,
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
        self.bus = bus
        self._orders: dict[str, Order] = {}
        self._filled_quantities: dict[str, float] = {}
        self._adopted_baseline: dict[str, float] = {}
        # Stops this session attached to its own entries, kept so the portfolio
        # governor can measure aggregate risk-at-stop without re-querying open
        # orders from the broker on every candidate.
        self._position_stops: dict[str, float] = {}
        # Serialises sign-off so the "re-check cash against the CURRENT
        # balance" step below is actually a check. Concurrently signed orders
        # each fetch the balance before either has spent it, so both see the
        # same cash and both pass - the documented failure mode where several
        # individually-affordable orders collectively overdraw the account.
        # Bulk human sign-off and unattended execution both hit this path.
        self._signoff_lock = asyncio.Lock()

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
        )
        await self._announce_pending(order)
        return order

    async def submit_exit_order(self, symbol: str, quantity: float, price: float) -> Order:
        """Closes an existing position at exactly `quantity` shares (spec §I).

        Separate from submit_order() rather than a flag on it, because the two
        size orders completely differently - an entry is sized by the risk
        engine, an exit is sized by what is actually held. Like submit_order(),
        this only ever creates a pending_signoff order and NEVER calls
        broker.place_order(): sign_off() remains the sole path to the broker.
        """
        if self.symbol_allow_list is not None and symbol not in self.symbol_allow_list:
            return self._new_rejected_order_for(symbol, "sell", 0.0)

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
                operator=operator,
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
            "Adopted %d pre-existing broker position(s) as the reconciliation baseline: %s. "
            "%d carries a stop resting at the broker, which is what its risk is measured to.",
            len(adopted),
            ", ".join(f"{sym} {qty:g}" for sym, qty in sorted(adopted.items())),
            len(self._position_stops),
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
        evidence instead of assumption. Returns the symbols that lost a stop.

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
        lost = [
            symbol
            for symbol in list(self._position_stops)
            if symbol in held and symbol not in resting
        ]
        for symbol in lost:
            self._position_stops.pop(symbol, None)
        if lost:
            logger.error(
                "POSITION UNPROTECTED: %s held with no stop resting at the broker. The stop "
                "this app recorded is gone, so these now count their full value as at risk",
                ", ".join(sorted(lost)),
            )
        return lost

    async def check_reconciliation(self) -> bool:
        """Compares OMS-tracked filled quantities against broker-reported
        positions; a mismatch trips the kill-switch (spec §I). Returns True
        if a mismatch was found.

        Call adopt_broker_positions() once at startup first, or an account with
        any pre-existing holding reads as a mismatch immediately.
        """
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
        if divergent:
            logger.error(
                "Broker reconciliation mismatch: %s",
                ", ".join(
                    f"{sym} tracked={tracked:g} broker={actual:g}"
                    for sym, (tracked, actual) in sorted(divergent.items())
                ),
            )
            self.kill_switch.check_reconciliation()
        return bool(divergent)

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
