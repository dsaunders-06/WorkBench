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
        captured = [o for o in before if o.symbol == symbol]
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
