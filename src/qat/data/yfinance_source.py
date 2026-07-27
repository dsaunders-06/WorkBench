"""Real market data via yfinance (spec M14).

Until now the only MarketDataSource was a seeded random walk, so every
indicator, signal and backtest in the application was computed against
synthetic prices. This is the first real feed.

What yfinance is, stated plainly so the limits are designed around rather
than discovered later:

* **Free and unofficial.** It scrapes a public Yahoo endpoint. It can rate-
  limit, change shape, or return nothing, and none of that is a contract
  breach because there is no contract. Every call here is defensive.
* **Sparse.** A minute with no trade is omitted, not repeated. Callers get
  gaps; BarAggregator's gap filling and `fill_missing_intervals` below are
  what stop a 30-bar window from silently spanning two hours.
* **Delayed.** Quotes are typically 15 minutes behind for most exchanges.
  That is survivable for a daily-cadence swing system and is NOT survivable
  for anything intraday - which is why the price-drift gate in the autonomy
  path exists.
* **Blocking.** yfinance is synchronous and does network I/O, so every call
  is pushed off the event loop with asyncio.to_thread. Calling it inline
  would stall every other engine on the bus.

The `YFinanceClient` protocol exists so the network can be faked in tests:
nothing in the test suite reaches Yahoo, and nothing in this environment has
proven a live call works. Same stance the README already takes for IBKR and
Anthropic - the logic is tested, the connection is yours to verify.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import pandas as pd

from qat.data.market_data import RawTick
from qat.data.symbols import to_yfinance

logger = logging.getLogger(__name__)

# Yahoo's own column names, which are title-cased and differ from ours.
_COLUMN_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
    "Datetime": "ts",
    "Date": "ts",
}

DEFAULT_POLL_SECONDS = 60.0
DEFAULT_HISTORY_PERIOD = "6mo"
DEFAULT_HISTORY_INTERVAL = "1d"


class YFinanceClient(Protocol):
    """The slice of yfinance this module actually uses."""

    def download(self, tickers: Any, **kwargs: Any) -> pd.DataFrame: ...


def _real_client() -> YFinanceClient:
    import yfinance  # type: ignore[import-untyped]

    return cast(YFinanceClient, yfinance)


def normalise_frame(raw: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame:
    """Yahoo's frame -> this codebase's ts/open/high/low/close/volume shape.

    Handles the multi-symbol download case, where yfinance returns a
    column MultiIndex rather than plain columns - a shape difference that is
    easy to miss because it only appears once you request more than one
    ticker, so single-symbol testing never surfaces it.
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    frame = raw.copy()

    if isinstance(frame.columns, pd.MultiIndex):
        if symbol is not None and symbol in frame.columns.get_level_values(-1):
            frame = cast(pd.DataFrame, frame.xs(symbol, axis=1, level=-1))
        else:
            frame.columns = frame.columns.get_level_values(0)

    frame = frame.reset_index()
    frame = frame.rename(columns=_COLUMN_MAP)

    missing = {"open", "high", "low", "close"} - set(frame.columns)
    if missing:
        logger.warning("yfinance frame for %s is missing %s", symbol, sorted(missing))
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    if "volume" not in frame:
        frame["volume"] = 0.0
    if "ts" not in frame:
        frame["ts"] = pd.NaT

    frame = frame[["ts", "open", "high", "low", "close", "volume"]]
    frame = frame.dropna(subset=["close"])
    # Yahoo returns tz-aware timestamps for intraday and naive ones for daily.
    # Normalising to UTC here keeps every downstream comparison from having to
    # guess which it got.
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True, errors="coerce")
    return frame.reset_index(drop=True)


# Intraday only. Daily bars are deliberately absent: Yahoo already returns one
# row per *trading* day, so reindexing them onto a calendar timeline invents a
# flat bar for every weekend and holiday. Measured against a real 1-year SPY
# pull that turned 251 trading days into 365 calendar days - and since the
# invented days carry a zero return, realized volatility came out roughly
# sqrt(252/365) ~ 17% too low, with the 50-day average skewed to match. The
# sparse-interval problem this function exists to solve is an intraday one.
_FILLABLE_FREQS = {"1m": "1min", "2m": "2min", "5m": "5min", "15m": "15min", "1h": "1h"}


def fill_missing_intervals(frame: pd.DataFrame, interval: str = "1d") -> pd.DataFrame:
    """Reindexes intraday bars onto a continuous timeline, carrying price forward.

    A quiet minute means the price did not move, which is true, so close is
    carried forward and open/high/low are set to it. Volume is filled with 0,
    never carried - repeating the previous bar's volume would invent trades.

    Daily and longer intervals are returned untouched; see _FILLABLE_FREQS.
    """
    if frame.empty or frame["ts"].isna().all():
        return frame

    freq = _FILLABLE_FREQS.get(interval)
    if freq is None:
        return frame

    indexed = frame.set_index("ts").sort_index()
    full = pd.date_range(indexed.index[0], indexed.index[-1], freq=freq, tz=UTC)
    reindexed = indexed.reindex(full)

    reindexed["close"] = reindexed["close"].ffill()
    for column in ("open", "high", "low"):
        reindexed[column] = reindexed[column].fillna(reindexed["close"])
    reindexed["volume"] = reindexed["volume"].fillna(0.0)

    reindexed = reindexed.dropna(subset=["close"])
    return reindexed.rename_axis("ts").reset_index()


class YFinanceHistorySource:
    """Historical bars. Used for the macro read, the Screener and the Workbench,
    all of which previously ran on synthetic bars."""

    def __init__(self, client: YFinanceClient | None = None) -> None:
        self._client = client

    @property
    def client(self) -> YFinanceClient:
        if self._client is None:
            self._client = _real_client()
        return self._client

    async def get_bars(
        self,
        symbol: str,
        period: str = DEFAULT_HISTORY_PERIOD,
        interval: str = DEFAULT_HISTORY_INTERVAL,
    ) -> pd.DataFrame:
        """Daily (or intraday) bars for one symbol.

        Returns an empty frame rather than raising when the fetch fails: every
        caller already treats "not enough bars" as a skip, and a network blip
        should degrade one screen rather than propagate an exception into an
        engine loop.
        """
        try:
            raw = await asyncio.to_thread(
                self.client.download,
                to_yfinance(symbol),
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )
        except Exception:  # noqa: BLE001 - an unofficial feed fails in many ways
            logger.warning("yfinance history fetch failed for %s", symbol, exc_info=True)
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

        frame = normalise_frame(raw, to_yfinance(symbol))
        return fill_missing_intervals(frame, interval)


class YFinanceMarketDataSource:
    """A MarketDataSource (per data.market_data.MarketDataSource) backed by
    Yahoo's last-price quotes.

    Polls rather than streams: there is no push feed here. The poll interval
    defaults to 60s because this is a delayed feed on a daily-cadence system -
    polling faster costs rate-limit budget without producing newer prices.
    """

    def __init__(
        self,
        client: YFinanceClient | None = None,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        max_consecutive_failures: int = 5,
    ) -> None:
        self._client = client
        self.poll_seconds = poll_seconds
        self.max_consecutive_failures = max_consecutive_failures

    @property
    def client(self) -> YFinanceClient:
        if self._client is None:
            self._client = _real_client()
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
                    # Stopping lets MarketDataFeed's staleness detector raise
                    # DataStaleEvent, which trips the kill-switch. Silently
                    # looping forever on a dead feed would leave the app
                    # looking alive while trading on nothing.
                    logger.error(
                        "yfinance returned no data %d times consecutively - ending the stream",
                        consecutive_failures,
                    )
                    return
                logger.warning(
                    "yfinance poll produced no ticks (%d/%d)",
                    consecutive_failures,
                    self.max_consecutive_failures,
                )

            await asyncio.sleep(self.poll_seconds)

    async def _poll_once(self, symbols: list[str]) -> list[RawTick]:
        # Requested in Yahoo's spelling, emitted in the app's. A tick labelled
        # BRK-B would never match a broker position called BRK.B, so the
        # translation has to close again on the way back out.
        vendor = {to_yfinance(symbol): symbol for symbol in symbols}
        try:
            raw = await asyncio.to_thread(
                self.client.download,
                list(vendor),
                period="1d",
                interval="1m",
                progress=False,
                auto_adjust=True,
            )
        except Exception:  # noqa: BLE001 - an unofficial feed fails in many ways
            logger.warning("yfinance quote poll failed", exc_info=True)
            return []

        now = datetime.now(UTC)
        ticks: list[RawTick] = []
        for vendor_symbol, symbol in vendor.items():
            frame = normalise_frame(raw, vendor_symbol)
            if frame.empty:
                continue
            last = frame.iloc[-1]
            price = float(last["close"])
            if price <= 0:
                continue
            ticks.append(
                RawTick(
                    symbol=symbol,
                    ts=now,
                    price=price,
                    volume=float(last["volume"]) if pd.notna(last["volume"]) else 0.0,
                )
            )
        return ticks
