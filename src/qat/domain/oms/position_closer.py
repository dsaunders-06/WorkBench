"""Manual full-close requests and operator results.

OMS owns protection cancellation, durable recovery intent and transmission.
The closer preserves the managed-position preconditions and reports issued
versus confirmed cancellations without sending recovery orders itself.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from qat.data.broker.adapter import BrokerAdapter, Order, is_protective_leg
from qat.domain.oms.oms import OMS
from qat.domain.oms.resting_orders import TERMINAL_STATUSES
from qat.domain.oms.signal_bridge import PositionEntry
from qat.domain.risk_engine.kill_switch import KillSwitch

logger = logging.getLogger(__name__)

_SCRIPT_HINT = "scripts/flatten_positions.py"


class CloseOutcome(Enum):
    CLOSED = "closed"
    REFUSED = "refused"
    RECOVERED = "recovered"
    UNPROTECTED = "unprotected"


@dataclass(frozen=True, slots=True)
class CloseResult:
    """Confirmed removals and issued requests are separate operator facts."""

    outcome: CloseOutcome
    symbol: str
    quantity: float
    cancelled_legs: tuple[str, ...]
    detail: str
    issued_legs: tuple[str, ...] = ()


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
        """Return the app's local protective-order preview for the confirmation dialog. The OMS
        re-reads broker truth at sign-off; this preview never authorises cancellation.
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
        """Read the broker's signed holding. A negative quantity must never be closed by sending
        another sell.
        """
        for position in await self.broker.positions():
            if position.symbol == symbol:
                return position.quantity
        return 0.0

    async def _sign_off_or_reread(self, order: Order, operator: str) -> Order | None:
        """Sign the approved order, or re-read it if another event handler already signed it. A
        competing sign-off does not justify retransmission.
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
        """Request a full manual close through the shared OMS safety boundary. Preflight refusal
        is reversible; only OMS sign-off may cancel protection, send the exit or restore its
        captured stop.
        """
        if quantity is not None:
            return self._refuse(
                symbol,
                "v1 supports full close only - pass quantity=None. A partial close "
                "would leave the remainder needing a re-placed bracket.",
            )

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

        entry = self.entries.get(symbol)
        if entry is None:
            return self._refuse(
                symbol,
                f"no entry record for {symbol}, so the exit would record no closed "
                f"trade and no R-multiple. Use {_SCRIPT_HINT} instead.",
            )

        live = [
            o
            for o in await self.broker.open_orders()
            if o.symbol == symbol and o.status not in TERMINAL_STATUSES
        ]
        if not live:
            return self._refuse(
                symbol,
                (
                    f"The broker reports no protective legs; this app believes "
                    f"{len(self.believed_legs_for(symbol))} are resting. Verify the position "
                    f"and use {_SCRIPT_HINT} for an unprotected holding."
                ),
            )
        intruders = [o for o in live if not is_protective_leg(o)]
        if intruders:
            return self._refuse(
                symbol,
                "Non-protective orders are working: " + ", ".join(o.order_id for o in intruders),
            )

        order = await self.oms.submit_exit_order(symbol, held, entry.price, reason="manual_close")
        signed: Order | None = order
        if order.status == "pending_signoff":
            signed = await self._sign_off_or_reread(order, operator)
        attempt = self.oms.exit_attempt(order.order_id)
        if signed is not None and (
            signed.status == "transmitted"
            or (
                signed.status == "filled"
                and signed.filled_quantity is not None
                and signed.filled_quantity > 0
                and signed.filled_price is not None
            )
        ):
            if signed.status == "filled":
                detail = f"The broker reports {signed.filled_quantity:g} {symbol} FILLED."
            elif signed.filled_quantity is not None and signed.filled_quantity > 0:
                detail = (
                    f"The broker confirms {signed.filled_quantity:g} {symbol} filled; "
                    f"{max(0.0, signed.quantity - signed.filled_quantity):g} shares remain "
                    "on the WORKING sell order."
                )
            else:
                detail = (
                    f"The market sell of {held:g} {symbol} is WORKING at the broker; "
                    "the broker has not reported a fill yet."
                )
            return CloseResult(
                CloseOutcome.CLOSED,
                symbol,
                held,
                attempt.cancelled,
                detail,
                issued_legs=attempt.issued,
            )
        if not attempt.issued and not self.oms.exit_protection_pending(symbol):
            return self._refuse(symbol, "The OMS refused the close before cancelling protection.")
        try:
            remaining = await self._held_quantity(symbol)
        except Exception:
            remaining = None
        if remaining == 0 and not self.oms.exit_protection_pending(symbol):
            return CloseResult(
                CloseOutcome.CLOSED,
                symbol,
                0,
                attempt.cancelled,
                (
                    "The broker now reports the position FLAT. A protective leg may have filled "
                    "during cancellation. No additional sell or stop was sent by the closer."
                ),
                issued_legs=attempt.issued,
            )
        if not self.oms.exit_protection_pending(symbol) and remaining is not None and remaining > 0:
            outcome = CloseOutcome.RECOVERED if attempt.cancelled else CloseOutcome.REFUSED
            detail = (
                "The close did not execute; recovery verified the original stop "
                "protecting the remaining holding."
            )
        else:
            outcome = CloseOutcome.REFUSED if attempt.issued else CloseOutcome.UNPROTECTED
            detail = (
                "The close did not complete. Orders may still be resting. Cancellation or "
                "transmission remains uncertain; protection recovery is pending. "
                "Check broker orders before retrying or placing protection."
            )
        if remaining is not None and remaining < 0:
            logger.critical(
                "Manual close found %s SHORT %g; no sell stop may be placed", symbol, abs(remaining)
            )
            detail += (
                " The broker reports a SHORT position. Do NOT place a sell stop; "
                "it would deepen the short."
            )
        detail += (
            f" Cancels issued: {', '.join(attempt.issued)}. "
            f"Confirmed gone: {', '.join(attempt.cancelled) or 'none'}."
        )
        return CloseResult(
            outcome, symbol, 0, attempt.cancelled, detail, issued_legs=attempt.issued
        )
