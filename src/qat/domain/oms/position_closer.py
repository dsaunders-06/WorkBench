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

from qat.data.broker.adapter import BrokerAdapter, RestingOrder
from qat.domain.oms.oms import OMS
from qat.domain.oms.resting_orders import WORKING_STATUSES
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

    async def _held_quantity(self, symbol: str) -> float:
        """The BROKER's quantity. App records are a claim; this is the fact."""
        for position in await self.broker.positions():
            if position.symbol == symbol:
                return abs(position.quantity)
        return 0.0

    async def _legs_for(self, symbol: str) -> list[RestingOrder]:
        """Working orders for `symbol`, read with `open_orders()`.

        NOT `openTrades()`: that read is clientId-scoped and on 24 August
        reported zero protective stops while sixteen were resting.
        """
        orders = await self.broker.open_orders()
        return [o for o in orders if o.symbol == symbol and o.status in WORKING_STATUSES]

    async def _cancel_legs(self, symbol: str) -> tuple[list[RestingOrder], str | None]:
        """Cancel every working leg, then RE-READ to prove they are gone.

        ⚠️ The cancel's own response is not evidence. On 19 August one reported
        PendingCancel while being rejected outright (error 10147).
        """
        captured = await self._legs_for(symbol)
        for leg in captured:
            try:
                await self.broker.cancel_order(leg.order_id)
            except Exception as exc:  # noqa: BLE001 - report it, never proceed
                return captured, f"cancel of leg {leg.order_id} failed: {exc}"

        survivors = await self._legs_for(symbol)
        if survivors:
            ids = ", ".join(o.order_id for o in survivors)
            return captured, (
                f"{len(survivors)} leg(s) still resting after the cancel ({ids}). "
                f"NOTHING was sold - selling now would leave them resting against a "
                f"position no longer held and put the account short."
            )
        return captured, None

    async def close_position(
        self,
        symbol: str,
        *,
        operator: str,
        acknowledge_halt: bool = False,
        quantity: float | None = None,
    ) -> CloseResult:
        if quantity is not None:
            return self._refuse(
                symbol,
                "v1 supports full close only - pass quantity=None. A partial close "
                "would leave the remainder needing a re-placed bracket.",
            )

        held = await self._held_quantity(symbol)
        if held <= 0:
            return self._refuse(symbol, f"{symbol} is not held at the broker")

        if self.entries.get(symbol) is None:
            return self._refuse(
                symbol,
                f"no entry record for {symbol}, so the exit would record no closed "
                f"trade and no R-multiple. Use {_SCRIPT_HINT} instead.",
            )

        if self.kill_switch.tripped and not acknowledge_halt:
            return self._refuse(
                symbol,
                f"the kill switch is tripped ({self.kill_switch.reason}) and the "
                f"halt was not acknowledged",
            )

        captured, failure = await self._cancel_legs(symbol)
        if failure is not None:
            return self._refuse(symbol, failure)
        cancelled = tuple(leg.order_id for leg in captured)
        return CloseResult(CloseOutcome.REFUSED, symbol, 0.0, cancelled, "sell not implemented yet")
