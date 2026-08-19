"""IBAdapter (spec §I, paper §15): the BrokerAdapter implementation over
ib_async, connecting to a local IB Gateway/TWS instance.

Connection health is checked via an active heartbeat loop (isConnected() +
reqCurrentTimeAsync()) rather than subscribing to ib_async's Event objects -
simpler to reason about and test, and it satisfies the same spec
requirement ("auto-reconnect with back-off; heartbeat").

Two structural safety gates, not just documentation:
- live_trading_confirmed must be explicitly True before this adapter will
  even construct when settings.trading_mode == "live" - only the in-app
  confirmation dialog (not yet wired - presentation layer) should ever set
  this to True.
- read_only, when True, is passed through to ib_async's own connectAsync
  (a real IBKR API-level read-only connection) AND is enforced again in
  software on every order-placing call - defense in depth, not reliance on
  a single layer.
"""

from __future__ import annotations

import asyncio
import logging

from qat.config import Settings
from qat.data.broker.adapter import (
    AccountBalances,
    AccountSummary,
    Order,
    Position,
    balances_from_summary,
)
from qat.data.broker.ib_client_protocol import IBClientProtocol
from qat.data.broker.ib_translate import (
    from_ib_account_values,
    from_ib_position,
    from_ib_trade,
    to_ib_contract,
    to_ib_order,
)
from qat.domain.bus import EventBus
from qat.domain.events import KillSwitchEvent

logger = logging.getLogger(__name__)

_LIVE_PORTS = {4001, 7496}
_PAPER_PORTS = {4002: "Gateway", 7497: "TWS"}


class ReadOnlyModeError(Exception):
    """Raised when an order-placing call is attempted while read_only=True."""


class LiveTradingNotConfirmedError(Exception):
    """Raised when trading_mode='live' but live_trading_confirmed was not
    explicitly passed True."""


class LivePortInPaperModeError(Exception):
    """Raised when trading_mode='paper' but ibkr_port reaches a LIVE session.

    W1.4. This was a warning until 12 August, and a warning is not enough,
    because `Settings.is_live` is `trading_mode == "live"` and nothing else -
    it is a claim about configuration, never a check against what the socket
    actually reached. Thirteen call sites trust that claim, including the
    autonomy gate, promotion-evidence enforcement, the cost model and the
    mode banner. A paper claim against a live Gateway leaves every one of them
    reading 'paper' while real orders are reachable.

    Deliberately one-directional. The reverse - trading_mode='live' against a
    paper port - is the SAFE mismatch and is allowed: costs are applied,
    autonomy is gated, the banner says DANGER, and the account underneath is
    a simulator.
    """


class IBAdapter:
    name = "ib-adapter"

    def __init__(
        self,
        ib_client: IBClientProtocol,
        bus: EventBus,
        settings: Settings | None = None,
        live_trading_confirmed: bool = False,
        read_only: bool = False,
        heartbeat_interval_seconds: float = 10.0,
        initial_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 30.0,
        max_reconnect_attempts: int = 5,
    ) -> None:
        settings = settings or Settings()
        if settings.is_live and not live_trading_confirmed:
            raise LiveTradingNotConfirmedError(
                "trading_mode is 'live' but live_trading_confirmed was not explicitly set - "
                "the in-app confirmation dialog must accept live trading before this adapter "
                "will connect."
            )
        if not settings.is_live and settings.ibkr_port in _LIVE_PORTS:
            paper = ", ".join(f"{port} (paper {name})" for port, name in _PAPER_PORTS.items())
            raise LivePortInPaperModeError(
                f"trading_mode is 'paper' but ibkr_port={settings.ibkr_port} reaches a LIVE "
                "IBKR session. Connecting would put real orders within reach while every "
                "is_live consumer in this application - the autonomy gate, promotion-evidence "
                f"enforcement, the cost model and the mode banner - reads 'paper'. Use {paper}, "
                "or set trading_mode=live deliberately and confirm it."
            )

        self.ib_client = ib_client
        self.bus = bus
        self.settings = settings
        self.read_only = read_only
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.initial_backoff_seconds = initial_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.max_reconnect_attempts = max_reconnect_attempts

        self._heartbeat_task: asyncio.Task[None] | None = None
        self._orders: dict[str, Order] = {}
        self._ib_orders: dict[str, object] = {}

    async def connect(self) -> None:
        await self.ib_client.connectAsync(
            self.settings.ibkr_host,
            self.settings.ibkr_port,
            self.settings.ibkr_client_id,
            readonly=self.read_only,
        )
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        self.ib_client.disconnect()

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval_seconds)
            if not await self._is_healthy():
                await self._reconnect_with_backoff()

    async def _is_healthy(self) -> bool:
        if not self.ib_client.isConnected():
            return False
        try:
            await self.ib_client.reqCurrentTimeAsync()
        except Exception:  # noqa: BLE001 - any failure here means "unhealthy"
            return False
        return True

    async def _reconnect_with_backoff(self) -> None:
        for attempt in range(self.max_reconnect_attempts):
            delay = min(self.max_backoff_seconds, self.initial_backoff_seconds * (2**attempt))
            await asyncio.sleep(delay)
            try:
                await self.ib_client.connectAsync(
                    self.settings.ibkr_host,
                    self.settings.ibkr_port,
                    self.settings.ibkr_client_id,
                    readonly=self.read_only,
                )
            except Exception as exc:  # noqa: BLE001 - any connect failure just means "retry"
                logger.warning("IBKR reconnect attempt %d failed: %s", attempt + 1, exc)
                continue
            if self.ib_client.isConnected():
                logger.info("IBKR reconnected after %d attempt(s)", attempt + 1)
                return

        logger.error("IBKR reconnect attempts exhausted - halting new orders")
        await self.bus.publish(
            KillSwitchEvent(
                reason="IBKR connection lost and reconnect attempts exhausted",
                triggered_by="ib-adapter",
            )
        )

    def _check_not_read_only(self) -> None:
        if self.read_only:
            raise ReadOnlyModeError(
                "IBAdapter is in read-only mode - cannot place/modify/cancel orders"
            )

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        contract = to_ib_contract(symbol)
        ticker = self.ib_client.reqMktData(contract)
        await asyncio.sleep(0)  # yield once so a just-arrived tick can populate the ticker
        return {
            "bid": getattr(ticker, "bid", float("nan")),
            "ask": getattr(ticker, "ask", float("nan")),
            "last": getattr(ticker, "last", float("nan")),
        }

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        contract = to_ib_contract(symbol)
        bar_data = await self.ib_client.reqHistoricalDataAsync(
            contract,
            endDateTime=None,
            durationStr=f"{bars} D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
        )
        return [{"close": float(bar.close)} for bar in bar_data]  # type: ignore[attr-defined]

    async def place_order(self, order: Order) -> Order:
        self._check_not_read_only()
        contract = to_ib_contract(order.symbol)
        ib_order = to_ib_order(order)
        trade = self.ib_client.placeOrder(contract, ib_order)
        app_order_id = order.order_id
        self._orders[app_order_id] = order
        self._ib_orders[app_order_id] = ib_order
        result = from_ib_trade(trade, order)
        # `from_ib_trade` may have overwritten `order.order_id` with IBKR's
        # permId (see its docstring - the Task 3 identity bridge). Both
        # `_orders` and `_ib_orders` above were keyed under the id that
        # existed BEFORE that overwrite, so a caller holding the RETURNED
        # order - the only id it has after transmit - would get a KeyError
        # from `modify_order`/`cancel_order`, and a protective stop would
        # become uncancellable. Registered under the new id too, rather than
        # moved: OMS's own bookkeeping (`_sign_off_locked`) keeps the
        # ORIGINAL id as its dict key for the order's whole lifetime and
        # calls `broker.cancel_order`/`modify_order` back with that id, so
        # both identifiers have to keep resolving.
        if result.order_id != app_order_id:
            self._orders[result.order_id] = result
            self._ib_orders[result.order_id] = ib_order
        return result

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        self._check_not_read_only()
        order = self._orders[order_id]
        for key, value in changes.items():
            setattr(order, key, value)
        ib_order = self._ib_orders.get(order_id)
        if ib_order is not None:
            # Re-priced fields have to reach the broker, not just our own
            # object. Only `limit_price` did, so M39 re-pricing a resting stop
            # through a corporate action was accepted, recorded here, and
            # never sent - leaving the app believing the stop had moved while
            # the broker still held the old level. That is the MNST shape: an
            # unadjusted stop through a split (M95).
            resend = False
            if "limit_price" in changes:
                ib_order.lmtPrice = changes["limit_price"]  # type: ignore[attr-defined]
                resend = True
            if "stop_price" in changes:
                ib_order.auxPrice = changes["stop_price"]  # type: ignore[attr-defined]
                resend = True
            if resend:
                contract = to_ib_contract(order.symbol)
                self.ib_client.placeOrder(contract, ib_order)  # type: ignore[arg-type]
        return order

    async def cancel_order(self, order_id: str) -> Order:
        self._check_not_read_only()
        order = self._orders[order_id]
        ib_order = self._ib_orders.get(order_id)
        if ib_order is not None:
            self.ib_client.cancelOrder(ib_order)  # type: ignore[arg-type]
        order.status = "cancelled"
        return order

    async def balances(self) -> AccountBalances:
        """Derived from the account summary: the IB translation layer does not
        map margin or day-trade fields, so those stay None rather than being
        guessed at from the three figures that are mapped."""
        return balances_from_summary(await self.account())

    async def positions(self) -> list[Position]:
        return [from_ib_position(pos) for pos in self.ib_client.positions()]

    async def account(self) -> AccountSummary:
        return from_ib_account_values(self.ib_client.accountSummary())
