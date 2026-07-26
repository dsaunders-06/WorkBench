"""Market data from Alpaca (spec M17): live ticks and daily bars.

Until now AlpacaAdapter supplied only execution and account state, and prices
came from yfinance or the synthetic walk. That meant the venue the account
actually trades against and the venue its decisions were made from were two
different places. These sources close that gap, so quotes, bars and fills
agree by construction.

Feed entitlement matters and is deliberately explicit rather than assumed:

* ``iex`` (default) - real time on any account including free paper, but a
  single exchange carrying only a small share of US consolidated volume.
  Quotes for less liquid names can be sparse or stale relative to the tape.
* ``sip`` - the full consolidated tape, and the right answer for real
  decisions, but it needs a paid Algo Trader Plus subscription. Requesting it
  without one fails rather than silently degrading.
* ``delayed_sip`` - consolidated but 15 minutes behind; complete coverage on
  the free tier, fine for daily/swing cadence and not for intraday.

US equities only, matching AlpacaAdapter - an ASX watchlist cannot be served
from here.

The client is injected behind a Protocol so tests never touch the network or
need credentials, the same seam alpaca_client_protocol.py gives the broker.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import pandas as pd

from qat.data.market_data import RawTick
from qat.security import get_secret

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 60.0
# Calendar days of padding when asking for N trading days: ~252 trading days
# a year, so 1.5x plus a week comfortably covers weekends and holidays.
_CALENDAR_PADDING_DAYS = 7


class AlpacaDataClientProtocol(Protocol):
    def get_stock_latest_trade(self, request_params: Any) -> Any: ...

    def get_stock_bars(self, request_params: Any) -> Any: ...


def build_data_client() -> AlpacaDataClientProtocol:
    """Builds a real StockHistoricalDataClient from keyring credentials.

    Uses the same ALPACA_API_KEY/ALPACA_SECRET_KEY as the broker adapter -
    Alpaca issues one key pair for both trading and data, so asking for them
    twice would be a worse experience for no security gain.
    """
    from alpaca.data.historical import StockHistoricalDataClient

    from qat.data.broker.alpaca_adapter import API_KEY_SECRET_NAME, SECRET_KEY_SECRET_NAME

    api_key = get_secret(API_KEY_SECRET_NAME)
    secret_key = get_secret(SECRET_KEY_SECRET_NAME)
    if not api_key or not secret_key:
        raise RuntimeError(
            f"Set {API_KEY_SECRET_NAME} and {SECRET_KEY_SECRET_NAME} (Settings -> Broker) "
            "before selecting Alpaca market data"
        )
    return cast(
        AlpacaDataClientProtocol,
        StockHistoricalDataClient(api_key=api_key, secret_key=secret_key),
    )


def _feed_enum(feed: str) -> Any:
    from alpaca.data.enums import DataFeed

    return DataFeed(feed)


def _trades_from(response: Any) -> dict[str, Any]:
    """Alpaca returns a dict keyed by symbol, or a raw dict in raw_data mode."""
    if isinstance(response, dict):
        return response
    return dict(getattr(response, "data", {}) or {})


class AlpacaMarketDataSource:
    """A MarketDataSource backed by Alpaca's latest-trade endpoint.

    Polls rather than streams. Alpaca does offer a websocket feed, but the
    rest of this app is built around a polled AsyncIterator and a daily/swing
    cadence; a streaming client would be a larger change for prices this
    system does not act on tick-by-tick anyway.

    Uses the latest *trade* rather than the latest quote: a trade carries an
    executed price and a size, which is what RawTick means. A quote's bid/ask
    midpoint would be an invented price no one traded at.
    """

    def __init__(
        self,
        client: AlpacaDataClientProtocol | None = None,
        feed: str = "iex",
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        max_consecutive_failures: int = 5,
    ) -> None:
        self._client = client
        self.feed = feed
        self.poll_seconds = poll_seconds
        self.max_consecutive_failures = max_consecutive_failures

    @property
    def client(self) -> AlpacaDataClientProtocol:
        if self._client is None:
            self._client = build_data_client()
        return self._client

    async def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]:
        symbol_list = list(symbols)
        if not symbol_list:
            return

        consecutive_failures = 0
        while True:
            ticks = await self._poll_once(symbol_list)

            if ticks:
                consecutive_failures = 0
                for tick in ticks:
                    yield tick
            else:
                consecutive_failures += 1
                if consecutive_failures >= self.max_consecutive_failures:
                    # Ending the stream lets MarketDataFeed's staleness
                    # detector raise DataStaleEvent and trip the kill-switch.
                    # Looping forever on a dead feed would leave the app
                    # looking alive while trading on nothing.
                    logger.error(
                        "Alpaca returned no trades %d times consecutively - ending the stream",
                        consecutive_failures,
                    )
                    return
                logger.warning(
                    "Alpaca quote poll produced no ticks (%d/%d)",
                    consecutive_failures,
                    self.max_consecutive_failures,
                )

            await asyncio.sleep(self.poll_seconds)

    async def _poll_once(self, symbols: list[str]) -> list[RawTick]:
        from alpaca.data.requests import StockLatestTradeRequest

        request = StockLatestTradeRequest(symbol_or_symbols=symbols, feed=_feed_enum(self.feed))
        try:
            response = await asyncio.to_thread(self.client.get_stock_latest_trade, request)
        except Exception:  # noqa: BLE001 - network, auth and entitlement all land here
            logger.warning("Alpaca latest-trade poll failed", exc_info=True)
            return []

        ticks: list[RawTick] = []
        for symbol, trade in _trades_from(response).items():
            price = float(getattr(trade, "price", 0.0) or 0.0)
            if price <= 0:
                continue
            ticks.append(
                RawTick(
                    symbol=str(symbol),
                    ts=getattr(trade, "timestamp", None) or datetime.now(UTC),
                    price=price,
                    volume=float(getattr(trade, "size", 0.0) or 0.0),
                )
            )
        return ticks


class AlpacaHistorySource:
    """Daily bars from Alpaca, with the same documented synthetic fallback
    discipline as RealHistorySource (data/history.py).

    The fallback is deliberate: an unreachable or unentitled feed should
    degrade a screen to clearly-labelled synthetic data rather than leave it
    blank, but never *silently* - believing you are looking at real market
    data when you are not is worse than seeing nothing. Callers can read
    `last_was_synthetic` to label the display.
    """

    def __init__(
        self,
        client: AlpacaDataClientProtocol | None = None,
        feed: str = "iex",
        fallback: Any | None = None,
    ) -> None:
        self._client = client
        self.feed = feed
        if fallback is None:
            from qat.data.history import SyntheticHistorySource

            fallback = SyntheticHistorySource()
        self.fallback = fallback
        self.last_was_synthetic = False

    @property
    def client(self) -> AlpacaDataClientProtocol:
        if self._client is None:
            self._client = build_data_client()
        return self._client

    async def get_daily_bars(self, symbol: str, n_bars: int = 300) -> pd.DataFrame:
        frame = await self._fetch(symbol, n_bars)

        if frame is None or frame.empty:
            logger.warning(
                "No Alpaca daily bars for %s - falling back to synthetic. This data is NOT real.",
                symbol,
            )
            self.last_was_synthetic = True
            fallback: pd.DataFrame = await self.fallback.get_daily_bars(symbol, n_bars)
            return fallback

        self.last_was_synthetic = False
        trimmed: pd.DataFrame = frame.tail(n_bars).reset_index(drop=True)
        return trimmed

    async def _fetch(self, symbol: str, n_bars: int) -> pd.DataFrame | None:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        # Ask by date window rather than bar count: Alpaca's `limit` counts
        # rows returned, so a plain limit would silently include partial
        # sessions rather than n complete trading days.
        start = datetime.now(UTC) - timedelta(days=int(n_bars * 1.5) + _CALENDAR_PADDING_DAYS)
        request = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame.Day,
            start=start,
            feed=_feed_enum(self.feed),
        )
        try:
            response = await asyncio.to_thread(self.client.get_stock_bars, request)
        except Exception:  # noqa: BLE001 - network, auth and entitlement all land here
            logger.warning("Alpaca daily-bar request failed for %s", symbol, exc_info=True)
            return None

        bars = _trades_from(response).get(symbol) or []
        if not bars:
            return None

        # No gap filling. Alpaca already returns one row per trading day, so
        # reindexing onto a calendar timeline would invent rows for weekends
        # and holidays and drag realized volatility below true (the same bug
        # M14 found and fixed for yfinance daily bars).
        return pd.DataFrame(
            [
                {
                    "ts": bar.timestamp,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                }
                for bar in bars
            ]
        )
