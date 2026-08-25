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
from collections.abc import Awaitable
from datetime import datetime
from typing import TypeVar

from ib_async import ExecutionFilter

from qat.config import Settings
from qat.data.broker.adapter import (
    AccountBalances,
    AccountSummary,
    BrokerFill,
    Order,
    Position,
    RestingOrder,
    RestingStopOrder,
    balances_from_summary,
)
from qat.data.broker.ib_client_protocol import IBClientProtocol
from qat.data.broker.ib_translate import (
    from_ib_account_values,
    from_ib_fill,
    from_ib_open_order,
    from_ib_position,
    from_ib_resting_stop,
    from_ib_trade,
    tighter_stop,
    to_ib_contract,
    to_ib_oca_pair,
    to_ib_order,
    to_ib_parent,
    to_ib_protective_legs,
)
from qat.data.broker.ticks import round_to_tick
from qat.data.symbols import from_ibkr
from qat.domain.bus import EventBus
from qat.domain.events import KillSwitchEvent

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

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
        # Six attempts over ~1 minute at the default backoff (M125). Enough for
        # a human to finish a Gateway login; short enough that a genuinely
        # closed port still fails before the open rather than hanging.
        max_connect_attempts: int = 6,
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
        self.max_connect_attempts = max_connect_attempts

        self._heartbeat_task: asyncio.Task[None] | None = None
        self._orders: dict[str, Order] = {}
        self._ib_orders: dict[str, object] = {}
        # One app Order can map to several IBKR orders (M95 Stage B): a
        # bracketed entry is a parent plus two legs, a standalone protective
        # pair is two OCA legs. `_ib_orders` keeps the PRIMARY one so every
        # existing single-order path is untouched; group operations - cancel,
        # and repricing the right leg - use this.
        self._ib_groups: dict[str, list[object]] = {}

    async def connect(self) -> None:
        """Connect, retrying a refused port for a bounded time (M125).

        A single attempt used to be the whole of this method, and on 21 August
        at 08:53 that cost a full restart four minutes before the ASX open: the
        Gateway process was running but nobody had logged in, so port 4002 was
        closed, `connectAsync` raised ConnectionRefusedError, and the
        application shut down. A Gateway thirty seconds late should not end the
        session before it starts.

        The asymmetry this fixes is the odd part: `_reconnect_with_backoff`
        already existed for the HEARTBEAT, so a connection lost at 14:17
        mid-session recovered by itself - as one did - while a connection not
        yet established at startup did not retry once.

        Bounded, not infinite. Six attempts over roughly a minute covers a
        human finishing a Gateway login; past that, something is wrong that
        waiting will not fix, and the original exception is raised so the
        operator sees the real reason rather than a timeout.
        """
        last: Exception | None = None
        for attempt in range(1, self.max_connect_attempts + 1):
            try:
                await self.ib_client.connectAsync(
                    self.settings.ibkr_host,
                    self.settings.ibkr_port,
                    self.settings.ibkr_client_id,
                    readonly=self.read_only,
                )
            except Exception as exc:  # noqa: BLE001 - any connect failure is a retry
                last = exc
                if attempt == self.max_connect_attempts:
                    break
                delay = min(
                    self.max_backoff_seconds, self.initial_backoff_seconds * (2 ** (attempt - 1))
                )
                logger.warning(
                    "IBKR connect attempt %d/%d failed (%s: %s) - retrying in %.0fs. "
                    "A Gateway that is running but not logged in refuses the port.",
                    attempt,
                    self.max_connect_attempts,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if attempt > 1:
                logger.info(
                    "IBKR connected on attempt %d of %d", attempt, self.max_connect_attempts
                )
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            return

        logger.error(
            "IBKR refused the connection %d times - giving up. Check that the Gateway "
            "is logged in and that its API port (%s) is open.",
            self.max_connect_attempts,
            self.settings.ibkr_port,
        )
        raise last if last is not None else RuntimeError("IBKR connect failed")

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
            await self._call(self.ib_client.reqCurrentTimeAsync(), "reqCurrentTime")
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
        """A quote, actually WAITED for (item 37).

        This used to call `reqMktData` and then `await asyncio.sleep(0)` - a
        single event-loop yield - before reading a `Ticker` whose fields default
        to `nan`. One yield is nowhere near enough for IBKR to deliver a tick,
        so the caller almost always got `nan` on every field.

        That is not a cosmetic miss. `AutonomousExecutor._current_price` is the
        only consumer, and its `None` return SKIPS the autonomy gate's
        price-drift check - the one guard standing between an order parked for
        eighty minutes and being signed at a price nobody chose. No
        `has drifted` line exists in any log back to 12 August.

        `reqTickersAsync` waits for the ticker to be populated rather than
        hoping, and is bounded by `_call`'s deadline like every other request
        here, so "no data" now costs a timeout rather than an eternity.
        """
        contract = to_ib_contract(symbol, self.settings.market)
        request = getattr(self.ib_client, "reqTickersAsync", None)
        if not callable(request):
            return {}
        tickers = await self._call(request(contract), f"reqTickers({symbol})")
        if not tickers:
            return {}
        ticker = tickers[0]
        return {
            "bid": getattr(ticker, "bid", float("nan")),
            "ask": getattr(ticker, "ask", float("nan")),
            "last": getattr(ticker, "last", float("nan")),
        }

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        contract = to_ib_contract(symbol, self.settings.market)
        bar_data = await self._call(
            self.ib_client.reqHistoricalDataAsync(
                contract,
                endDateTime=None,
                durationStr=f"{bars} D",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
            ),
            "reqHistoricalData",
        )
        return [{"close": float(bar.close)} for bar in bar_data]  # type: ignore[attr-defined]

    def _register(self, order: Order, ib_order: object, group: list[object]) -> None:
        self._orders[order.order_id] = order
        self._ib_orders[order.order_id] = ib_order
        self._ib_groups[order.order_id] = group

    async def _place_bracket(self, order: Order, contract: object) -> Order:
        """An entry plus its protective legs, in IBKR's required order (M95 B).

        The parent goes first and UNTRANSMITTED so it cannot reach the market
        ahead of its protection; `placeOrder` assigns its `orderId` (real
        ib_async does this when the field is unset), which the legs then
        reference as `parentId`; the final leg carries `transmit=True` and
        releases the group.
        """
        parent = to_ib_parent(order)
        parent_trade = self.ib_client.placeOrder(contract, parent)  # type: ignore[arg-type]
        group: list[object] = [parent]
        for leg in to_ib_protective_legs(order, parent.orderId):
            self.ib_client.placeOrder(contract, leg)  # type: ignore[arg-type]
            group.append(leg)

        app_order_id = order.order_id
        self._register(order, parent, group)
        result = from_ib_trade(parent_trade, order)
        if result.order_id != app_order_id:
            self._register(result, parent, group)
        return result

    async def _place_oca(self, order: Order, contract: object) -> Order:
        """A standalone protective stop and target, mutually exclusive at the
        broker rather than merely both present (M33)."""
        pair = to_ib_oca_pair(order, oca_group=f"qat-{order.order_id}")
        trades = [
            self.ib_client.placeOrder(contract, leg) for leg in pair  # type: ignore[arg-type]
        ]

        app_order_id = order.order_id
        stop_leg = next(leg for leg in pair if leg.orderType == "STP")
        self._register(order, stop_leg, list(pair))
        # The STOP leg's identity is the one worth carrying: it is the
        # protection, and it is what `resting_stops` will later have to match.
        stop_trade = trades[pair.index(stop_leg)]
        result = from_ib_trade(stop_trade, order)
        if result.order_id != app_order_id:
            self._register(result, stop_leg, list(pair))
        return result

    async def recent_fills(
        self, since: datetime, symbols: list[str] | None = None
    ) -> list[BrokerFill]:
        """Executions IBKR performed that this app did not transmit (M34/M48).

        A protective stop or target filling closes a position with no order
        leaving this process, so nothing publishes `OrderFilledEvent`. Without
        this, `absorb_broker_fills` returns immediately: the ledger never
        records the closed trade, reconciliation reads the changed quantity as
        a discrepancy and trips the kill-switch on a stop doing its job, and
        `_correct_announced_price` (M70/M71) never runs at all.

        **`reqExecutions`, not `IB.fills()`.** `IB.fills()` is documented "all
        fills from this session", so it cannot see a fill that happened while
        the app was DOWN - which is precisely the case this method exists for.
        The wrong choice would pass every test and fail only on the restart
        that mattered.

        **The window is applied HERE, on fill time.** `ExecutionFilter` carries
        a `time`, and it is deliberately not used to bound the answer: Alpaca's
        `after=` read like "activity since then" and turned out to mean
        `submitted_at`, so the one execution the method existed to catch was
        the one it could not see (M48). A broker-side filter whose semantics
        have not been MEASURED is not trusted to decide what this returns.

        **Two things still unmeasured, recorded rather than assumed.** Whether
        executions are `clientId`-scoped the way open orders turned out to be
        (a cancel from the wrong clientId fails with error 10147 while
        `reqAllOpenOrders` still shows the order) - `ExecutionFilter` is left
        with its default clientId, expected to mean "all", and that expectation
        is untested. And how far back IBKR's executions actually go, which is
        Task 1's question 4 and needs a real fill. If retention proves large
        enough that asking for everything is wasteful, bound the request
        broker-side ONLY after measuring what `time` does.
        """
        if symbols is not None and not symbols:
            # Nothing tracked, so nothing can have closed behind our back - and
            # no reason to spend a request establishing that.
            return []

        request = getattr(self.ib_client, "reqExecutionsAsync", None)
        if not callable(request):
            return []
        executions = await self._call(request(ExecutionFilter()), "reqExecutions")

        wanted = set(symbols) if symbols else None
        fills: list[BrokerFill] = []
        for execution in executions:
            fill = from_ib_fill(execution, self.settings.market)
            if fill is None:
                continue
            if fill.filled_at <= since:
                continue
            if wanted is not None and fill.symbol not in wanted:
                continue
            fills.append(fill)
        return fills

    async def open_orders(self) -> list[RestingOrder]:
        """Every order working at the broker, unfiltered (M141, item 23).

        **`reqAllOpenOrders`, not `openTrades`.** `openTrades()` is CLIENT
        SCOPED: on 24 August it reported no protective stops while sixteen were
        resting, because they belonged to clientId 1 and the probe was 99. The
        sync form is a `util.run` wrapper that raises "event loop is already
        running" inside the app (the M102 trap, hit three times in one
        afternoon), so this uses the async form and nothing else.

        Returns `[]` when the underlying client cannot answer (not yet
        connected, or too old to carry `reqAllOpenOrdersAsync`) - the SAME
        `[]` a genuinely clean broker returns (I3, final review, correcting an
        earlier version of this docstring that told callers to read the two
        apart). `BrokerAdapter.open_orders`'s own contract is that an empty
        list means "nothing to report", full stop, and `OMS.check_resting_
        orders` follows it: it cannot and does not distinguish "asked and
        found nothing" from "could not ask" at this layer. What DOES surface
        the difference is `OMS.check_resting_orders`'s own `source is None`
        branch, one level up - that fires when THIS adapter has no
        `open_orders` attribute at all, which is a different failure than the
        one handled here.
        """
        request = getattr(self.ib_client, "reqAllOpenOrdersAsync", None)
        if not callable(request):
            return []
        trades = await self._call(request(), "reqAllOpenOrders")
        return [from_ib_open_order(trade, self.settings.market) for trade in trades]

    async def resting_stop_orders(self) -> dict[str, RestingStopOrder]:
        """Protective stops actually working at the broker, with enough to
        CHANGE one (M31b/M39, Stage 1 Task 4).

        This is the primary; `resting_stops` derives from it. One scan rather
        than two, because two could disagree about what counts as protection
        and "protected" is the answer the re-arm acts on.

        **`reqAllOpenOrders`, not `openTrades`.** `openTrades()` returns only
        the CONNECTED client's orders. A stop placed under a different clientId
        would be invisible to it - and invisible protection reads as NO
        protection, so the app would re-arm a position that is already
        protected and the duplicate would be refused for insufficient shares.
        The same measurement that showed this also showed the trap in the other
        direction: an order visible here may still not be CANCELLABLE from this
        connection, which is why the record carries `owner_client_id`.

        Returns an empty dict when nothing is working, which
        `OMS.verify_position_stops` reads as "no protection found" - and it
        means we went and looked, not that a page ran out.
        """
        request = getattr(self.ib_client, "reqAllOpenOrdersAsync", None)
        if not callable(request):
            return {}

        resting: dict[str, RestingStopOrder] = {}
        for trade in await self._call(request(), "reqAllOpenOrders"):
            stop = from_ib_resting_stop(trade, self.settings.market)
            if stop is None:
                continue
            existing = resting.get(stop.symbol)
            if existing is None:
                resting[stop.symbol] = stop
                continue
            logger.warning(
                "%s has TWO live protective stops at the broker (%s @ %s and %s @ %s) - "
                "reporting the one that would fire first. A duplicate re-arm or a leg that "
                "outlived its parent.",
                stop.symbol,
                existing.order_id,
                existing.stop_price,
                stop.order_id,
                stop.stop_price,
            )
            resting[stop.symbol] = tighter_stop(
                existing, stop, selling=str(trade.order.action).upper() == "SELL"
            )
        return resting

    async def resting_stops(self) -> dict[str, float]:
        """Symbol to stop price, from the one scan `resting_stop_orders` runs.

        M31b. The app keeps its own record of the stops it attached, and that
        record has been wrong: on 31 July six brackets' take-profit legs
        expired at the close, the paired stops were cancelled with them, and
        nothing noticed - reconciliation compares filled quantities and an
        expired protective leg changes none.
        """
        return {
            symbol: stop.stop_price for symbol, stop in (await self.resting_stop_orders()).items()
        }

    def _price_side(self, order: Order, field: str) -> str:
        """Which side a given price field is actually transmitted as (M123).

        Protective legs REVERSE the entry's side - a long's stop and its target
        are both SELLs - unless the order IS the resting stop, in which case its
        own side is already the closing side.
        """
        if field == "limit_price":
            return order.side
        if order.order_type == "stop":
            return order.side
        return "sell" if order.side == "buy" else "buy"

    def _round_prices_onto_ticks(self, order: Order) -> None:
        """Move every price on this order onto a valid exchange increment (M123).

        Done HERE, at the broker boundary, for the same reason AlpacaAdapter
        rounds to 2dp here: fifteen call sites construct order prices and none
        of them should have to know what an exchange's price steps are. Mutated
        in place rather than copied so the object the OMS keeps is the one the
        broker holds - a stop the app records at 1.8734 while IBKR rests at
        1.875 is the M95 Stage A failure in miniature.

        Nothing rounded before the ASX move and nothing needed to: the US tick
        is a cent at every price a megacap trades at, so AlpacaAdapter's 2dp
        and "on tick" were the same thing. On the ASX between $0.10 and $2.00
        the step is half a cent, and an ATR-derived stop lands off it.
        """
        for field in ("limit_price", "stop_price", "take_profit_price"):
            price = getattr(order, field)
            if price is None:
                continue
            rounded = round_to_tick(price, self.settings.market, self._price_side(order, field))
            if rounded != price:
                logger.info(
                    "%s %s moved onto the %s tick: %s -> %s",
                    order.symbol,
                    field,
                    self.settings.market,
                    price,
                    rounded,
                )
                setattr(order, field, rounded)

    async def place_order(self, order: Order) -> Order:
        self._check_not_read_only()
        self._round_prices_onto_ticks(order)
        contract = to_ib_contract(order.symbol, self.settings.market)
        if order.is_bracket:
            return await self._place_bracket(order, contract)
        if order.order_type == "stop" and order.take_profit_price is not None:
            return await self._place_oca(order, contract)
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

    async def _adopt_from_broker(self, order_id: str) -> Order | None:
        """Learn an order the broker knows and this process does not (M99).

        Two ways an id can be real and unregistered, and the second is why this
        resolves against the broker rather than tightening placement.

        **The permId arrives late.** Real IBKR returns `permId=0` from
        `placeOrder` - TWS has not acknowledged - so `from_ib_trade` leaves the
        app's own id in place (correctly) and `place_order`'s dual
        registration never fires. Moments later the broker reports the order
        under its permId, which is exactly what `resting_stop_orders` returns.
        M39 then re-prices a stop through a split using the id the scan gave
        it, and got a `KeyError`. Found by the Task 4 live check; every fake in
        the suite stamped permId synchronously, so the tests agreed with each
        other and with nothing real.

        **The app never placed it.** An adopted position's protective stop has
        no local handle at all, and was equally unreachable.

        Registers what it finds, so a second call does not re-scan.
        """
        request = getattr(self.ib_client, "reqAllOpenOrdersAsync", None)
        if not callable(request):
            return None

        for trade in await self._call(request(), "reqAllOpenOrders"):
            ib_order = trade.order
            if order_id not in {str(ib_order.permId), str(ib_order.orderId)}:
                continue

            owner = int(getattr(ib_order, "clientId", 0) or 0)
            if owner != self.settings.ibkr_client_id:
                # Measured 19 August: a cancel from another clientId fails with
                # error 10147 while reqAllOpenOrders() STILL SHOWS the order
                # and the local object reports PendingCancel. Visible is not
                # cancellable. The attempt is still made - IBKR is the
                # authority on its own orders - but it does not go unremarked.
                logger.warning(
                    "IBKR order %s belongs to clientId %s, not this session's %s. A modify "
                    "or cancel from here fails with error 10147 while the order stays "
                    "visible in reqAllOpenOrders(). Attempting anyway.",
                    order_id,
                    owner,
                    self.settings.ibkr_client_id,
                )

            order_type = str(ib_order.orderType)
            adopted = Order(
                symbol=from_ibkr(trade.contract.symbol, self.settings.market),
                side="buy" if str(ib_order.action).upper() == "BUY" else "sell",
                quantity=float(ib_order.totalQuantity),
                order_id=order_id,
                status="transmitted",
                stop_price=float(ib_order.auxPrice) or None,
                order_type="stop" if order_type.startswith("STP") else "market",
            )
            self._register(adopted, ib_order, [ib_order])
            return adopted
        return None

    async def _known_order(self, order_id: str) -> Order:
        """The app Order for an id, resolving it against the broker if this
        process does not already hold it. Raises rather than resolving to
        nothing - an id nobody has heard of is a caller bug, and answering
        quietly would leave the app believing it had cancelled something."""
        order = self._orders.get(order_id)
        if order is not None:
            return order
        adopted = await self._adopt_from_broker(order_id)
        if adopted is None:
            raise KeyError(order_id)
        return adopted

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        self._check_not_read_only()
        order = await self._known_order(order_id)
        # M123. The re-priced value has to be on a tick too. A split-adjusted
        # stop is the old level divided by the ratio, which lands off the grid
        # far more often than it lands on it - and a rejected adjustment leaves
        # the OLD stop resting at the broker while the app records the new one.
        for key in ("limit_price", "stop_price", "take_profit_price"):
            if key in changes and changes[key] is not None:
                changes[key] = round_to_tick(
                    float(changes[key]),  # type: ignore[arg-type]
                    self.settings.market,
                    self._price_side(order, key),
                )
        for key, value in changes.items():
            setattr(order, key, value)
        ib_order = self._ib_orders.get(order_id)
        if ib_order is None:
            return order

        # Re-priced fields have to reach the broker, not just our own object.
        # Only `limit_price` did, so M39 re-pricing a resting stop through a
        # corporate action was accepted, recorded here, and never sent -
        # leaving the app believing the stop had moved while the broker held
        # the old level. That is the MNST shape: an unadjusted stop through a
        # split (M95 Stage A).
        #
        # And it has to reach the RIGHT ORDER. A bracketed entry is three
        # orders; repricing the parent when the stop moved would edit the
        # entry and report success, which is the same failure wearing a
        # different hat (M95 Stage B).
        group = self._ib_groups.get(order_id, [ib_order])
        touched: list[object] = []

        if "limit_price" in changes:
            ib_order.lmtPrice = changes["limit_price"]  # type: ignore[attr-defined]
            touched.append(ib_order)
        if "stop_price" in changes:
            target = self._leg_of_type(group, "STP") or ib_order
            target.auxPrice = changes["stop_price"]  # type: ignore[attr-defined]
            touched.append(target)
        if "take_profit_price" in changes:
            target = self._leg_of_type(group, "LMT")
            if target is not None:
                target.lmtPrice = changes["take_profit_price"]  # type: ignore[attr-defined]
                touched.append(target)

        if touched:
            contract = to_ib_contract(order.symbol, self.settings.market)
            for leg in touched:
                self.ib_client.placeOrder(contract, leg)  # type: ignore[arg-type]
        return order

    @staticmethod
    def _leg_of_type(group: list[object], order_type: str) -> object | None:
        """The leg of a group that carries a given IBKR order type.

        Skips the entry: a bracketed LIMIT entry and its take-profit leg are
        both "LMT", and repricing the entry when the target moved would be the
        precise mistake this exists to avoid. Legs carry a parentId or an
        ocaGroup; an entry carries neither.
        """
        for leg in group:
            if getattr(leg, "orderType", None) != order_type:
                continue
            if getattr(leg, "parentId", 0) or getattr(leg, "ocaGroup", ""):
                return leg
        # No protective leg of that type - fall back to a lone order, which is
        # the standalone-stop case where the order IS the protection.
        for leg in group:
            if getattr(leg, "orderType", None) == order_type:
                return leg
        return None

    async def cancel_order(self, order_id: str) -> Order:
        """Cancel the order, and everything attached to it, VERIFIED.

        IBKR cascades a parent cancel to its children, and "cascades" is not a
        guarantee this project accepts on trust: on 19 August a cancel
        reported `PendingCancel` while being rejected outright (error 10147 -
        an order belongs to the clientId that placed it, and another client
        cannot cancel it). An orphaned stop resting against a position that no
        longer exists is worth one extra read.
        """
        self._check_not_read_only()
        order = await self._known_order(order_id)
        ib_order = self._ib_orders.get(order_id)
        group = self._ib_groups.get(order_id) or ([ib_order] if ib_order is not None else [])
        if not group:
            order.status = "cancelled"
            return order

        for leg in group:
            self.ib_client.cancelOrder(leg)  # type: ignore[arg-type]

        # Then confirm, where the client can tell us. `openTrades` is optional
        # on IBClientProtocol, so this degrades to the unverified path rather
        # than failing on a client that does not serve it.
        open_trades = getattr(self.ib_client, "openTrades", None)
        if callable(open_trades):
            ours = {id(leg) for leg in group}
            still_resting = [
                trade
                for trade in open_trades()
                if any(getattr(trade, "order", None) is leg for leg in group)
                or id(getattr(trade, "order", None)) in ours
            ]
            for trade in still_resting:
                logger.warning(
                    "IBKR leg %s survived the group cancel - cancelling it individually",
                    getattr(trade.order, "orderId", "?"),
                )
                self.ib_client.cancelOrder(trade.order)

        order.status = "cancelled"
        return order

    async def balances(self) -> AccountBalances:
        """Derived from the account summary: the IB translation layer does not
        map margin or day-trade fields, so those stay None rather than being
        guessed at from the three figures that are mapped."""
        return balances_from_summary(await self.account())

    async def _call(self, coro: Awaitable[_T], what: str) -> _T:
        """Every IBKR request, under a deadline (item 34, root cause).

        The adapter previously had eight awaits on the client and no timeout on
        any of them. `reqExecutionsAsync` resolves only when IBKR sends
        `execDetailsEnd`, and if that message is lost - a known failure after a
        reconnect - the future never completes. On 25 August that wedged the
        reconciliation poll for 6h50m across nine new positions, and said
        nothing, because a hung await raises nothing.

        RAISES rather than returning a default, deliberately. A timeout means
        "we could not look", and every caller here has a consumer that reads an
        empty result as "there is nothing there" - which would turn a dead
        broker connection into a fabricated all-clear. Losing one poll loudly
        is recoverable; losing every future poll silently is what happened.
        """
        timeout = self.settings.ibkr_call_timeout_seconds
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            logger.error(
                "IBKR did not answer %s within %.0fs. The call is abandoned so the caller "
                "can fail and retry rather than hang forever (item 34).",
                what,
                timeout,
            )
            raise

    async def positions(self) -> list[Position]:
        """Held positions, carrying the broker's mark (item 45).

        `IB.positions()` returns `Position(account, contract, position,
        avgCost)` and no price. `IB.portfolio()` returns `PortfolioItem` with
        `marketPrice`, is already populated by the `updatePortfolio` events the
        Gateway pushes, and costs no extra request. Before this, every row of
        the Positions panel showed a blank Last, P&L and To stop, and every one
        read `(escape unknown)` - because the minimum-hold loss escape had no
        price to measure a loss against. That is a rail, not a display.

        **`positions()` stays the source of truth for QUANTITY.**
        `check_reconciliation` builds its kill-switch input from this set, so
        the portfolio is used ONLY to enrich the price. A portfolio item that
        disagreed about size must not silently redefine the book.
        """
        marks = self._portfolio_marks()
        return [
            from_ib_position(pos, self.settings.market, marks.get(pos.contract.symbol))
            for pos in self.ib_client.positions()
        ]

    def _portfolio_marks(self) -> dict[str, float]:
        """Raw-symbol -> broker mark, for whatever the portfolio reports.

        Keyed on the RAW IBKR symbol because that is what both calls carry;
        translation happens once, downstream. A client without `portfolio` -
        an older fake, or an adapter that predates this - yields no marks
        rather than an error.

        A mark of zero or less is dropped: IBKR reports 0.0 for an instrument
        it has no data on, and a position marked at zero measures as a total
        loss.
        """
        portfolio = getattr(self.ib_client, "portfolio", None)
        if not callable(portfolio):
            return {}
        marks: dict[str, float] = {}
        for item in portfolio():
            price = float(getattr(item, "marketPrice", 0.0) or 0.0)
            if price > 0:
                marks[item.contract.symbol] = price
        return marks

    async def account(self) -> AccountSummary:
        """The account summary, asked through the form that works in a loop.

        `IB.accountSummary()` is a SYNC wrapper around `util.run`, which calls
        `loop.run_until_complete` - and this application runs inside an asyncio
        loop already, so it raises "This event loop is already running". That
        made `account()` and `balances()` unusable in the running app while
        passing every test, because the fakes implement `accountSummary` as a
        plain method returning a list (M102).

        Found the first time the APP ran on IBKR rather than a script. The same
        trap as M99's synchronous permId: a fake wrong in exactly the direction
        production is.
        """
        summary = getattr(self.ib_client, "accountSummaryAsync", None)
        if callable(summary):
            return from_ib_account_values(await summary())
        return from_ib_account_values(self.ib_client.accountSummary())
