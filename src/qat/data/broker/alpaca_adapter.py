"""AlpacaAdapter (spec M12): the BrokerAdapter implementation over
alpaca-py's TradingClient, so a real Alpaca **paper** account supplies
positions, cash and fills instead of the in-process MockBroker.

Safety, mirroring IBAdapter (data/broker/ib_adapter.py):

- Constructed against the paper endpoint (`paper=True`) unless trading_mode
  is 'live' AND live_trading_confirmed was explicitly passed - the same
  two-key gate IBAdapter uses, so reaching a real-money endpoint can never
  be the result of a single config edit.
- Credentials come from the OS keyring via qat.security, never from config
  files or logs.
- The client is injectable behind AlpacaClientProtocol so tests run with a
  fake and need no API keys.

Scope is execution + account state only: market data stays synthetic
(MarketDataSource), so get_market_data/get_historical exist to satisfy the
BrokerAdapter Protocol and are honest about being unsupported here rather
than pretending to be a data feed. Nothing in the app calls them outside
the adapters - the live price path is MarketDataFeed, not the broker.

Alpaca is US equities only; an ASX watchlist cannot be traded through it
(runtime.resolve_broker logs this, and Settings warns).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, cast

from qat.config import Settings
from qat.data.broker.adapter import (
    AccountBalances,
    AccountSummary,
    BrokerFill,
    Order,
    Position,
)
from qat.data.broker.alpaca_client_protocol import AlpacaClientProtocol
from qat.security import get_secret

logger = logging.getLogger(__name__)

# These are the *names* of keyring entries, not credentials - the values are
# only ever read from the OS keyring at runtime, never stored in source.
API_KEY_SECRET_NAME = "ALPACA_API_KEY"  # nosec B105 - keyring lookup key, not a secret
SECRET_KEY_SECRET_NAME = "ALPACA_SECRET_KEY"  # nosec B105 - keyring lookup key, not a secret


class AlpacaCredentialsMissingError(RuntimeError):
    """Raised when no Alpaca API key/secret is available in the keyring."""


class AlpacaLiveTradingNotConfirmedError(RuntimeError):
    """Raised when trading_mode='live' but live_trading_confirmed was not
    explicitly set - the same deliberate gate IBAdapter applies."""


class AlpacaAdapter:
    def __init__(
        self,
        client: AlpacaClientProtocol | None = None,
        settings: Settings | None = None,
        live_trading_confirmed: bool = False,
    ) -> None:
        settings = settings or Settings()
        self.settings = settings

        if settings.is_live and not live_trading_confirmed:
            raise AlpacaLiveTradingNotConfirmedError(
                "trading_mode is 'live' but live_trading_confirmed was not explicitly set - "
                "refusing to construct an Alpaca adapter against the live endpoint"
            )
        self.paper = not (settings.is_live and live_trading_confirmed)
        self._client = client or self._build_default_client()

    def _build_default_client(self) -> AlpacaClientProtocol:
        from alpaca.trading.client import TradingClient

        api_key = get_secret(API_KEY_SECRET_NAME)
        secret_key = get_secret(SECRET_KEY_SECRET_NAME)
        if not api_key or not secret_key:
            raise AlpacaCredentialsMissingError(
                f"Set {API_KEY_SECRET_NAME} and {SECRET_KEY_SECRET_NAME} in the OS keyring "
                "(or via the Settings screen) before selecting the Alpaca broker"
            )
        logger.info("Connecting to Alpaca (paper=%s)", self.paper)
        return cast(
            AlpacaClientProtocol,
            TradingClient(api_key=api_key, secret_key=secret_key, paper=self.paper),
        )

    # --- account / positions ------------------------------------------------

    async def account(self) -> AccountSummary:
        account = await asyncio.to_thread(self._client.get_account)
        return AccountSummary(
            net_liquidation=_as_float(getattr(account, "equity", None)),
            cash=_as_float(getattr(account, "cash", None)),
            buying_power=_as_float(getattr(account, "buying_power", None)),
        )

    async def balances(self) -> AccountBalances:
        """Alpaca's own balance sheet, passed through rather than recomputed.

        Deriving figures like the day's P&L locally would eventually disagree
        with the broker's own page, and when two screens disagree about money
        the operator has to work out which one is lying.
        """
        account = await asyncio.to_thread(self._client.get_account)
        return AccountBalances(
            equity=_optional_float(getattr(account, "equity", None)),
            last_equity=_optional_float(getattr(account, "last_equity", None)),
            cash=_optional_float(getattr(account, "cash", None)),
            long_market_value=_optional_float(getattr(account, "long_market_value", None)),
            short_market_value=_optional_float(getattr(account, "short_market_value", None)),
            buying_power=_optional_float(getattr(account, "buying_power", None)),
            regt_buying_power=_optional_float(getattr(account, "regt_buying_power", None)),
            daytrading_buying_power=_optional_float(
                getattr(account, "daytrading_buying_power", None)
            ),
            non_marginable_buying_power=_optional_float(
                getattr(account, "non_marginable_buying_power", None)
            ),
            multiplier=_optional_float(getattr(account, "multiplier", None)),
            initial_margin=_optional_float(getattr(account, "initial_margin", None)),
            maintenance_margin=_optional_float(getattr(account, "maintenance_margin", None)),
            sma=_optional_float(getattr(account, "sma", None)),
            accrued_fees=_optional_float(getattr(account, "accrued_fees", None)),
            status=_optional_str(getattr(account, "status", None)),
            currency=_optional_str(getattr(account, "currency", None)),
            daytrade_count=_optional_int(getattr(account, "daytrade_count", None)),
            pattern_day_trader=_optional_bool(getattr(account, "pattern_day_trader", None)),
            trading_blocked=_optional_bool(getattr(account, "trading_blocked", None)),
            account_blocked=_optional_bool(getattr(account, "account_blocked", None)),
            shorting_enabled=_optional_bool(getattr(account, "shorting_enabled", None)),
        )

    async def positions(self) -> list[Position]:
        raw = await asyncio.to_thread(self._client.get_all_positions)
        return [
            Position(
                symbol=str(pos.symbol),
                quantity=_as_float(getattr(pos, "qty", None)),
                avg_price=_as_float(getattr(pos, "avg_entry_price", None)),
            )
            for pos in raw
        ]

    async def resting_stops(self) -> dict[str, float]:
        """Stop orders actually working at the broker, by symbol (M31b).

        The app keeps its own record of the stops it attached, and on 31 July
        that record was wrong for six positions: the brackets were submitted
        DAY, their take-profit legs expired at the close, and Alpaca cancelled
        the paired stops with them. Nothing noticed, because reconciliation
        compares filled quantities and an expired protective leg changes none.

        **Nested, and `held` counts as resting (M33d).** An OCO's stop leg sits
        at status `held` while its partner is live, and it is returned as a
        CHILD of the parent order rather than as a top-level row. A flat scan
        for open stop orders therefore saw nothing.

        That is not a cosmetic miss. On 1 August the app read a CRWD position
        carrying a perfectly good OCO as unprotected, and proposed a second
        one - which, signed, would have left 32 shares of resting sell orders
        against a 16-share position. The five plain stops all read back
        correctly, which is why every check before that passed: it took the new
        order shape to expose that the query never understood it.

        Erring toward "protected" here is the safe direction for THIS query and
        only because the caller is the one that proposes new protection. A
        false "unprotected" duplicates orders; a false "protected" merely
        leaves the governor measuring a stop that exists.
        """
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        request = GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=200, nested=True)
        orders = await asyncio.to_thread(self._client.get_orders, filter=request)
        resting: dict[str, float] = {}
        for order in orders:
            for candidate in _with_legs(order):
                side = str(getattr(candidate, "side", "")).lower()
                stop = getattr(candidate, "stop_price", None)
                # Tested on the stop PRICE rather than the order-type string.
                # An OCO leg reports its own type inconsistently across
                # versions, and "carries a stop level and would sell" is the
                # property that actually makes it protection.
                if "sell" in side and stop is not None:
                    resting[str(getattr(candidate, "symbol", ""))] = float(stop)
        return resting

    async def recent_fills(self, since: datetime) -> list[BrokerFill]:
        """Executions the broker performed that this app did not transmit (M34).

        A resting stop or target filling closes a position with no order
        leaving this process, so nothing publishes OrderFilledEvent. Without
        this the app finds out only through reconciliation, which reads it as
        a discrepancy and trips the kill-switch on a stop doing its job - and
        the trade ledger never records the closed trade at all.

        Asks for the real fill price rather than assuming the stop level. A
        stop fills at or below its trigger and a target at or above its limit,
        so using the level as a proxy would put a wrong number into every
        realised P&L the promotion gate reads.
        """
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        request = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED, limit=200, after=since, nested=True
        )
        orders = await asyncio.to_thread(self._client.get_orders, filter=request)
        fills: list[BrokerFill] = []
        for order in orders:
            for candidate in _with_legs(order):
                if str(getattr(candidate, "status", "")).lower().find("filled") < 0:
                    continue
                quantity = _as_float(getattr(candidate, "filled_qty", None))
                price = _as_float(getattr(candidate, "filled_avg_price", None))
                filled_at = getattr(candidate, "filled_at", None)
                if not quantity or not price or filled_at is None:
                    continue
                fills.append(
                    BrokerFill(
                        order_id=str(getattr(candidate, "id", "")),
                        symbol=str(getattr(candidate, "symbol", "")),
                        side=(
                            "sell"
                            if "sell" in str(getattr(candidate, "side", "")).lower()
                            else "buy"
                        ),
                        quantity=float(quantity),
                        price=float(price),
                        filled_at=filled_at,
                    )
                )
        return fills

    # --- orders -------------------------------------------------------------

    async def place_order(self, order: Order) -> Order:
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            LimitOrderRequest,
            MarketOrderRequest,
            StopLossRequest,
            StopOrderRequest,
            TakeProfitRequest,
        )

        side = OrderSide.BUY if order.side == "buy" else OrderSide.SELL

        # A standalone protective stop (M31d). Every stop before this rode in
        # as a bracket leg on an entry, so when those legs died there was no
        # way to put one back on a position already held - which is the state
        # all six positions were in on 1 August.
        #
        # GTC unconditionally. A protective stop submitted DAY is the exact
        # bug this exists to repair.
        if order.order_type == "stop":
            if order.stop_price is None:
                raise ValueError(f"stop order for {order.symbol} has no stop price")

            # Both levels known -> ONE OCO, never two orders (M33).
            #
            # A resting stop and a resting limit for the same shares are not
            # independent: if the price runs to the target and later gaps back
            # through the stop, both fill, and the account sells twice what it
            # holds - turning a protected long into an accidental short. OCO is
            # what makes the pair mutually exclusive at the broker, which is
            # exactly the property a bracket had before its legs expired.
            if order.take_profit_price is not None:
                oco_request = LimitOrderRequest(
                    symbol=order.symbol,
                    qty=order.quantity,
                    side=side,
                    limit_price=round(order.take_profit_price, 2),
                    time_in_force=TimeInForce.GTC,
                    order_class=OrderClass.OCO,
                    take_profit=TakeProfitRequest(limit_price=round(order.take_profit_price, 2)),
                    stop_loss=StopLossRequest(stop_price=round(order.stop_price, 2)),
                )
                placed = await asyncio.to_thread(self._client.submit_order, oco_request)
                order.order_id = str(getattr(placed, "id", order.order_id))
                order.status = _map_status(str(getattr(placed, "status", "")))
                return order

            stop_request = StopOrderRequest(
                symbol=order.symbol,
                qty=order.quantity,
                side=side,
                stop_price=round(order.stop_price, 2),
                time_in_force=TimeInForce.GTC,
            )
            placed = await asyncio.to_thread(self._client.submit_order, stop_request)
            order.order_id = str(getattr(placed, "id", order.order_id))
            order.status = _map_status(str(getattr(placed, "status", "")))
            return order
        # GTC on anything carrying protective legs (M31b).
        #
        # DAY killed every stop this system ever placed. On 31 July six
        # positions filled with brackets attached; at the close the
        # take-profit legs EXPIRED, Alpaca cancelled the paired stops with
        # them as OCO does, and six positions worth about $36,000 sat through
        # a three-day weekend with no protection at the broker at all.
        #
        # A protective stop whose whole purpose is to outlive the application
        # must also outlive the session. The README calls broker-side stops
        # the thing that survives a crash, a dead connection and a Windows
        # update - DAY meant they did not survive 4pm.
        #
        # A plain entry with no bracket keeps DAY: an unfilled market order
        # should not linger into the next session at a price nobody chose.
        carries_protection = order.is_bracket and order.side == "buy"
        kwargs: dict[str, object] = {
            "symbol": order.symbol,
            "qty": order.quantity,
            "side": side,
            "time_in_force": TimeInForce.GTC if carries_protection else TimeInForce.DAY,
        }

        # A bracket attaches the protective legs at the broker in the same
        # submission, so there is no window in which the position exists
        # without its stop. Alpaca rejects a bracket on a sell-to-close, so
        # this only applies to entries.
        if carries_protection:
            kwargs["order_class"] = OrderClass.BRACKET
            if order.stop_price is not None:
                kwargs["stop_loss"] = StopLossRequest(stop_price=round(order.stop_price, 2))
            if order.take_profit_price is not None:
                kwargs["take_profit"] = TakeProfitRequest(
                    limit_price=round(order.take_profit_price, 2)
                )

        request = MarketOrderRequest(**kwargs)
        placed = await asyncio.to_thread(self._client.submit_order, request)

        order.order_id = str(getattr(placed, "id", order.order_id))
        # Alpaca acknowledges asynchronously - an accepted order is live at the
        # broker but not yet filled, so it is reported as transmitted rather
        # than optimistically marked filled.
        order.status = _map_status(str(getattr(placed, "status", "")))
        filled_price = getattr(placed, "filled_avg_price", None)
        if filled_price is not None:
            order.filled_price = _as_float(filled_price)
        return order

    async def cancel_order(self, order_id: str) -> Order:
        await asyncio.to_thread(self._client.cancel_order_by_id, order_id)
        raw = await asyncio.to_thread(self._client.get_order_by_id, order_id)
        return _order_from_alpaca(raw, fallback_id=order_id)

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        raise NotImplementedError(
            "AlpacaAdapter does not support modifying a live order; cancel and resubmit instead"
        )

    # --- market data (not this adapter's job - see module docstring) --------

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        raise NotImplementedError(
            "AlpacaAdapter provides execution and account state only; market data comes "
            "from the configured MarketDataSource"
        )

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        raise NotImplementedError(
            "AlpacaAdapter provides execution and account state only; historical bars come "
            "from the configured MarketDataSource"
        )


def _as_float(value: object) -> float:
    """Alpaca returns numeric fields as strings; None means the field was absent."""
    if value is None:
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: object) -> float | None:
    """None-preserving sibling of _as_float (M21).

    _as_float coerces a missing field to 0.0, which is right for the cash rule
    - a buy must not proceed on an unknown balance - and wrong for display: a
    day-trade count Alpaca did not report is not a count of zero.
    """
    if value is None:
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _optional_int(value: object) -> int | None:
    parsed = _optional_float(value)
    return None if parsed is None else int(parsed)


def _optional_bool(value: object) -> bool | None:
    return None if value is None else bool(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    # Alpaca returns enums for status; their str() carries the class name.
    return str(getattr(value, "value", value))


_STATUS_MAP = {
    "new": "transmitted",
    "accepted": "transmitted",
    "pending_new": "transmitted",
    "partially_filled": "transmitted",
    "filled": "filled",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "expired": "cancelled",
    "rejected": "rejected",
}


def _with_legs(order: object) -> list[object]:
    """An order and any child legs it carries.

    Alpaca returns an advanced order set (bracket, OCO, OTO) as a parent with
    its legs nested underneath. Scanning only the top level sees the parent and
    misses the protection hanging off it.
    """
    found = [order]
    legs = getattr(order, "legs", None) or []
    for leg in legs:
        found.extend(_with_legs(leg))
    return found


def _map_status(alpaca_status: str) -> Any:
    """Maps Alpaca's order lifecycle onto this app's OrderStatus vocabulary.

    Anything unrecognised maps to "transmitted" rather than a terminal state:
    claiming an order is finished when its real state is unknown would be the
    dangerous direction to guess in.
    """
    return _STATUS_MAP.get(alpaca_status.lower().removeprefix("orderstatus."), "transmitted")


def _order_from_alpaca(raw: object, fallback_id: str) -> Order:
    side = str(getattr(raw, "side", "buy")).lower()
    return Order(
        symbol=str(getattr(raw, "symbol", "")),
        side="sell" if "sell" in side else "buy",
        quantity=_as_float(getattr(raw, "qty", None)),
        order_id=str(getattr(raw, "id", fallback_id)),
        status=_map_status(str(getattr(raw, "status", ""))),
        filled_price=_as_float(getattr(raw, "filled_avg_price", None)) or None,
    )
