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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

from qat.config import Settings
from qat.data.broker.adapter import BrokerAdapter, BrokerFill, Order
from qat.data.broker.mock_broker import new_order_id
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal, JournalEntry
from qat.domain.events import OrderFilledEvent, OrderPendingSignoffEvent
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


def _absorbed_from_json(entry: object) -> _AbsorbedFill:
    """One `absorbed` entry, in either the M50 or the M53 shape.

    M50 wrote a bare timestamp per order id. A file in that shape is loaded as
    "seen, quantity unknown" - quantity 0, which makes the whole of any such
    order eligible to be re-counted. That is the deliberate direction: the file
    is at most one poll old at startup, adoption has just re-baselined the
    quantities from the broker anyway, and under-recording a closed trade is the
    failure this milestone exists to end.
    """
    if isinstance(entry, str):
        return _AbsorbedFill(filled_at=datetime.fromisoformat(entry), quantity=0.0, price=0.0)
    if isinstance(entry, dict):
        return _AbsorbedFill(
            filled_at=datetime.fromisoformat(str(entry["filled_at"])),
            quantity=float(entry.get("quantity") or 0.0),
            price=float(entry.get("price") or 0.0),
        )
    raise ValueError("unrecognised absorbed-fill record")


_FILL_STATE_FILENAME = "absorbed_fills.json"
# How long an absorbed fill's id is remembered. Only needs to outlast the gap
# between the watermark and now - days, not weeks - but the file is tiny and a
# generous window costs nothing against the risk of recording a trade twice.
_ABSORBED_ID_RETENTION = timedelta(days=30)


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
        settings: Settings | None = None,
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
        """
        floor = self._last_fill_scan
        if self._absorbed_fills:
            oldest = min(seen.filled_at for seen in self._absorbed_fills.values())
            # A second before, because the brokers' filters are exclusive and an
            # order's remainder carries the same stamp as its first piece.
            floor = min(floor, oldest - timedelta(seconds=1))
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
        try:
            fills = await source(self._fill_query_floor(), self._symbols_to_watch_for_fills())
        except Exception:
            logger.exception("Could not read recent broker fills")
            return []

        absorbed: list[BrokerFill] = []
        for raw in fills:
            if not self._is_foreign_unrecorded(raw):
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
                "BROKER-SIDE FILL absorbed: %s %g %s at %.2f (order %s) - a resting "
                "protective order executed, and this is now a closed trade%s",
                fill.side,
                fill.quantity,
                fill.symbol,
                fill.price,
                fill.order_id,
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
        # replay safe to repeat.
        self._last_fill_scan = datetime.now(UTC)
        self._save_fill_state()
        return absorbed

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
