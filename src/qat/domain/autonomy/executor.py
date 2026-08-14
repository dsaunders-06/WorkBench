"""Unattended execution (spec M13).

The one place in this codebase that can sign an order off without a person.
It is deliberately thin: it fetches live state, asks AutonomyGate, journals the
answer, and either calls OMS.sign_off or does not. No decision logic lives
here, and nothing here can bypass OMS - the sign-off gate, the no-leverage
cash re-check and the kill-switch all still apply exactly as they do to a
human's click.

Three properties worth stating because they are easy to lose in a refactor:

* **Account state is fetched per order, never per batch.** A floor checked
  once and then reused across several orders is not a floor - it is the
  documented cause of a real margin loan on a paper account, where nine orders
  in one cycle all logged the same stale equity and collectively overdrew.
* **Every decision is journalled, including the blocked ones.** A journal of
  only what fired cannot distinguish a quiet day from a day when the rails
  stopped everything.
* **A failure blocks.** Any exception in the evaluation path leaves the order
  pending for a human, which is the safe direction to fail in.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from qat.config import Settings
from qat.data import instruments
from qat.data.broker.adapter import Order
from qat.domain.autonomy.equity_monitor import EquityMonitor
from qat.domain.autonomy.gate import AccountState, AutonomyGate, GateDecision
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal, JournalEntry
from qat.domain.events import OrderPendingSignoffEvent
from qat.domain.oms.oms import OMS

logger = logging.getLogger(__name__)

# Recorded as the sign-off operator so the audit log and blotter can always
# distinguish an unattended approval from a human one.
AUTONOMOUS_OPERATOR = "autonomous-executor"


class AutonomousExecutor:
    """Engine (per domain.orchestrator.Engine protocol)."""

    name = "autonomous-executor"

    def __init__(
        self,
        bus: EventBus,
        oms: OMS,
        gate: AutonomyGate,
        journal: DecisionJournal,
        equity_monitor: EquityMonitor | None = None,
        settings: Settings | None = None,
        retry_interval_seconds: float = 60.0,
    ) -> None:
        self.bus = bus
        self.oms = oms
        self.gate = gate
        self.journal = journal
        self.equity_monitor = equity_monitor
        self.settings = settings or Settings()
        # Matches the market-data poll: there is no point re-examining an
        # order more often than the prices behind it change.
        self.retry_interval_seconds = retry_interval_seconds
        self._retry_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.bus.subscribe(OrderPendingSignoffEvent, self._on_pending)
        self._retry_task = asyncio.create_task(self._retry_loop())

    async def stop(self) -> None:
        self.bus.unsubscribe(OrderPendingSignoffEvent, self._on_pending)
        if self._retry_task is not None:
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task
            self._retry_task = None

    async def _retry_loop(self) -> None:
        """Re-examines orders still awaiting sign-off (M31b).

        Evaluation used to happen exactly once, when the order became pending.
        That treats a reason which expires in minutes - 'session phase
        Opening Volatility is not eligible' - identically to one that never
        will, and the symbol stays suppressed meanwhile because the bridge
        skips anything already pending. It cost three manual reject cycles on
        30 July and one position on the 31st.

        Re-evaluating a stale order is safe because the gate re-reads the
        current price and refuses anything that has drifted past
        autonomous_price_drift_limit_pct from what it was sized against. An
        order that sat too long fails on drift rather than being signed at a
        price nobody chose.
        """
        while True:
            await asyncio.sleep(self.retry_interval_seconds)
            await self.retry_pending()

    async def retry_pending(self) -> None:
        """One pass over the orders still awaiting sign-off.

        Extracted from the loop above so a caller with its own clock can drive
        it (W2). A replay cannot use the timer: `retry_interval_seconds` is
        wall-clock, and `ReplaySession` pushes it out of reach precisely because
        a decade of simulated time passes in seconds.

        WITHOUT THIS THE REPLAY LOSES EVERY BLOCKED ORDER. Measured: a time stop
        fired correctly on 27 May 2024, the exit was created and audited, and
        the autonomy gate refused it because that day was Memorial Day - a real
        US market holiday, so the gate was right. Nothing ever asked again. The
        order sat in `pending_signoff` for the remaining hundred sessions, the
        position was never closed, and the run reported no closed trade at all.

        Live retries every sixty seconds; a replay retries once per simulated
        day, which is the same thing at the resolution it has.
        """
        if not self.settings.autonomy_enabled:
            return
        try:
            for order in self.oms.pending_orders():
                await self._consider(order.order_id)
        except Exception:  # noqa: BLE001 - a bad sweep must not end the loop
            logger.exception("Retry of pending orders failed - will try again")

    async def _on_pending(self, event: OrderPendingSignoffEvent) -> None:
        # Cheapest possible early exit. In recommend mode - the default - this
        # engine costs one comparison per order and touches nothing else.
        if not self.settings.autonomy_enabled:
            return

        try:
            await self._consider(event.order_id)
        except Exception:  # noqa: BLE001 - fail closed, leaving it for a human
            logger.exception(
                "Autonomous evaluation failed for order %s - left pending for sign-off",
                event.order_id,
            )
            self._journal_failure(event)

    async def _consider(self, order_id: str) -> None:
        order = self.oms.get_order(order_id)

        # Fetched now, for this order, not carried over from a batch.
        account_summary = await self.oms.broker.account()
        equity = float(account_summary.net_liquidation)
        account = AccountState(
            equity=equity,
            cash=float(account_summary.cash),
            day_pnl_pct=(
                self.equity_monitor.day_pnl_pct(equity) if self.equity_monitor is not None else 0.0
            ),
        )

        current_price = await self._current_price(order.symbol)
        decision = self.gate.evaluate(order, account, current_price=current_price)

        if not decision.allowed:
            logger.info(
                "Autonomy blocked order %s (%s %s): %s",
                order_id,
                order.side,
                order.symbol,
                decision.reason,
            )
            self._journal(order, decision.outcome, decision.reason, account, decision)
            return

        if decision.resized and decision.quantity < order.quantity:
            order.quantity = decision.quantity

        signed = await self.oms.sign_off(order_id, operator=AUTONOMOUS_OPERATOR)

        if signed.status == "rejected":
            # OMS refused it after the gate allowed it - the cash re-check or
            # the kill-switch caught something between the two. Journal the
            # OMS verdict, not the gate's, or the record would claim this
            # order executed.
            reason = f"gate allowed but OMS rejected at sign-off ({decision.reason})"
            logger.info("Autonomy order %s rejected by OMS", order_id)
            self._journal(signed, "blocked_by_oms", reason, account, decision)
            return

        logger.info(
            "Autonomy signed off order %s: %s %g %s",
            order_id,
            signed.side,
            signed.quantity,
            signed.symbol,
        )
        self._journal(signed, decision.outcome, decision.reason, account, decision)

    async def _current_price(self, symbol: str) -> float | None:
        """A live quote for the drift check, or None when the broker has none.

        None means the drift check is skipped rather than failed - an
        execution-only adapter never quoting is a known configuration, not a
        signal that anything is wrong. The order still faces every other gate
        and the fail-closed cash check at sign-off.
        """
        try:
            quote = await self.oms.broker.get_market_data(symbol)
        except Exception:  # noqa: BLE001 - adapters without quotes are expected
            return None
        price = float(quote.get("last") or quote.get("ask") or 0.0)
        return price if price > 0 else None

    def _journal(
        self,
        order: Order,
        outcome: str,
        reason: str,
        account: AccountState,
        decision: GateDecision,
    ) -> None:
        self.journal.record(
            JournalEntry(
                order_id=order.order_id,
                symbol=order.symbol,
                entity_name=instruments.name_for(order.symbol),
                side=order.side,
                quantity=float(order.quantity),
                price=order.filled_price or order.reference_price,
                strategy=order.strategy,
                outcome=outcome,
                reason=reason,
                market=decision.market,
                session_phase=decision.session_phase,
                equity=account.equity,
                cash=account.cash,
                day_pnl_pct=account.day_pnl_pct,
                execution_mode=self.settings.execution_mode,
            )
        )

    def _journal_failure(self, event: OrderPendingSignoffEvent) -> None:
        self.journal.record(
            JournalEntry(
                order_id=event.order_id,
                symbol=event.symbol,
                entity_name=instruments.name_for(event.symbol),
                side=event.side,
                quantity=float(event.quantity),
                strategy=event.strategy,
                outcome="blocked",
                reason="evaluation raised - left pending for human sign-off",
                execution_mode=self.settings.execution_mode,
            )
        )
