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
from typing import Any, cast

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position
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

    # --- orders -------------------------------------------------------------

    async def place_order(self, order: Order) -> Order:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        request = MarketOrderRequest(
            symbol=order.symbol,
            qty=order.quantity,
            side=OrderSide.BUY if order.side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
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
