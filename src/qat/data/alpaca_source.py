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
# Ceiling on the retry wait while the feed is down. Five minutes, so a feed
# that comes back is picked up inside a couple of polls rather than after an
# ever-doubling wait that outlives the session.
MAX_BACKOFF_SECONDS = 300.0
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
        max_backoff_seconds: float = MAX_BACKOFF_SECONDS,
    ) -> None:
        self._client = client
        self.feed = feed
        self.poll_seconds = poll_seconds
        self.max_consecutive_failures = max_consecutive_failures
        self.max_backoff_seconds = max_backoff_seconds

    @property
    def client(self) -> AlpacaDataClientProtocol:
        if self._client is None:
            self._client = build_data_client()
        return self._client

    async def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]:
        symbol_list = list(symbols)
        if not symbol_list:
            return

        symbol_list = await self._prune_unknown(symbol_list)
        if not symbol_list:
            logger.error("No usable symbols left to poll - the feed cannot start")
            return

        consecutive_failures = 0
        while True:
            ticks = await self._poll_once(symbol_list)

            if ticks:
                if consecutive_failures >= self.max_consecutive_failures:
                    logger.warning("Alpaca market data has recovered")
                consecutive_failures = 0
                for tick in ticks:
                    yield tick
            else:
                consecutive_failures += 1
                if consecutive_failures == self.max_consecutive_failures:
                    # Logged once at ERROR, then the loop keeps trying. Ending
                    # the stream here used to be the design - the reasoning was
                    # that a dead feed must not look alive - but it made a
                    # transient outage permanent for the session, and the
                    # staleness detector it relied on never fires for symbols
                    # that have not ticked even once, so the halt it was
                    # supposed to trigger never came. Visibility is now
                    # MarketDataFeed's job (it publishes MarketDataFeedEvent),
                    # which leaves this loop free to keep reconnecting.
                    logger.error(
                        "Alpaca has returned no trades %d times consecutively - "
                        "market data is down. Retrying with backoff.",
                        consecutive_failures,
                    )
                elif consecutive_failures < self.max_consecutive_failures:
                    logger.warning(
                        "Alpaca quote poll produced no ticks (%d/%d)",
                        consecutive_failures,
                        self.max_consecutive_failures,
                    )

            await asyncio.sleep(self._delay_after(consecutive_failures))

    def _delay_after(self, consecutive_failures: int) -> float:
        """Normal cadence while healthy, backing off while down.

        Capped, because a feed that recovers after an hour should be picked up
        within a poll or two rather than after an ever-doubling wait.
        """
        if consecutive_failures < self.max_consecutive_failures:
            return self.poll_seconds
        over = consecutive_failures - self.max_consecutive_failures
        return float(min(self.poll_seconds * (2 ** min(over + 1, 5)), self.max_backoff_seconds))

    async def _prune_unknown(self, symbols: list[str]) -> list[str]:
        """Drop symbols Alpaca rejects, so one bad ticker cannot mute the feed.

        Alpaca fails a multi-symbol request whole: ask for a hundred symbols
        with one unknown among them and the response is HTTP 400 and no data
        for any of them. A watchlist carrying BRK-B (Yahoo's spelling of
        BRK.B) therefore produced no prices at all, and the app spent a full
        session with a healthy strategy stack and nothing to feed it.

        Probing once at start costs a handful of requests only when something
        is actually wrong, and turns a silent session-long outage into a named
        warning about one ticker.
        """
        if await self._probe(symbols):
            return symbols

        good, bad = await self._bisect(symbols)
        if bad and good:
            logger.error(
                "Alpaca rejects %d watchlist symbol(s), dropping them for this session: %s. "
                "Fix them in the watchlist - a rejected symbol returns no data at all.",
                len(bad),
                ", ".join(sorted(bad)),
            )
        elif not good:
            # Everything failed, which is an outage or bad credentials, not a
            # hundred simultaneously delisted tickers. Pruning on that evidence
            # would empty the watchlist over a network blip.
            logger.error(
                "Alpaca rejected every symbol - treating this as an outage rather than "
                "an invalid watchlist, and keeping the list intact"
            )
            return symbols
        return good

    async def _probe(self, symbols: list[str]) -> bool:
        from alpaca.data.requests import StockLatestTradeRequest

        request = StockLatestTradeRequest(symbol_or_symbols=symbols, feed=_feed_enum(self.feed))
        try:
            await asyncio.to_thread(self.client.get_stock_latest_trade, request)
        except Exception:  # noqa: BLE001 - any rejection means "not usable as a batch"
            return False
        return True

    async def _bisect(self, symbols: list[str]) -> tuple[list[str], list[str]]:
        """Split a failing batch until the offenders are isolated."""
        if len(symbols) == 1:
            return ([], symbols) if not await self._probe(symbols) else (symbols, [])
        middle = len(symbols) // 2
        left_good, left_bad = await self._halve(symbols[:middle])
        right_good, right_bad = await self._halve(symbols[middle:])
        return left_good + right_good, left_bad + right_bad

    async def _halve(self, symbols: list[str]) -> tuple[list[str], list[str]]:
        if not symbols:
            return [], []
        if await self._probe(symbols):
            return symbols, []
        return await self._bisect(symbols)

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

    async def get_daily_bars_many(
        self, symbols: Sequence[str], n_bars: int = 300
    ) -> dict[str, pd.DataFrame]:
        """Daily bars for many symbols in one request, real data only.

        The warm start needs the whole watchlist at once, and one symbol at a
        time is not a viable way to get it: measured against this account, a
        single symbol takes about 1.3s, so 101 of them would block startup for
        over two minutes, where one multi-symbol request returns all of them in
        about 3s.

        This deliberately has no synthetic fallback, unlike get_daily_bars. A
        blank screen is a reasonable degradation for a screen; seeding a live
        trading buffer with a seeded random walk is not, and the caller can
        only tell the difference if the missing symbols are simply absent.
        """
        symbols = list(dict.fromkeys(symbols))
        if not symbols:
            return {}

        response = await self._request(symbols, n_bars)
        if response is None:
            return {}

        by_symbol = _trades_from(response)
        frames: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            bars = by_symbol.get(symbol) or []
            if bars:
                frames[symbol] = _bars_to_frame(bars).tail(n_bars).reset_index(drop=True)
        return frames

    async def _fetch(self, symbol: str, n_bars: int) -> pd.DataFrame | None:
        response = await self._request([symbol], n_bars)
        if response is None:
            return None

        bars = _trades_from(response).get(symbol) or []
        if not bars:
            return None

        return _bars_to_frame(bars)

    async def _request(self, symbols: Sequence[str], n_bars: int) -> Any | None:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        # Ask by date window rather than bar count: Alpaca's `limit` counts
        # rows returned, so a plain limit would silently include partial
        # sessions rather than n complete trading days.
        start = datetime.now(UTC) - timedelta(days=int(n_bars * 1.5) + _CALENDAR_PADDING_DAYS)
        request = StockBarsRequest(
            symbol_or_symbols=list(symbols),
            timeframe=TimeFrame.Day,
            start=start,
            feed=_feed_enum(self.feed),
        )
        try:
            return await asyncio.to_thread(self.client.get_stock_bars, request)
        except Exception:  # noqa: BLE001 - network, auth and entitlement all land here
            logger.warning(
                "Alpaca daily-bar request failed for %d symbol(s)", len(symbols), exc_info=True
            )
            return None


def _bars_to_frame(bars: Sequence[Any]) -> pd.DataFrame:
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
