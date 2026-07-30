"""Historical daily bars, real or synthetic (spec M14).

Three screens need daily bars - the Screener's trend read, the Workbench's
backtests, and the Regime Monitor's macro signal - and until M14 all three
called presentation.synthetic_bars.generate_daily_bars directly. That put a
data-source decision inside the presentation layer and made "switch to real
data" a three-file change with no single place to get it right.

HistoricalBarSource is the seam. Runtime resolves one implementation from
Settings and hands it to every screen, so the three agree by construction.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pandas as pd

from qat.config import Settings
from qat.data.market_data import SyntheticMarketDataSource

logger = logging.getLogger(__name__)

DEFAULT_BARS = 300


class HistoricalBarSource(Protocol):
    async def get_daily_bars(self, symbol: str, n_bars: int = DEFAULT_BARS) -> pd.DataFrame: ...


class BulkHistorySource(Protocol):
    """A source that can answer for many symbols in one request."""

    async def get_daily_bars_many(
        self, symbols: Sequence[str], n_bars: int = DEFAULT_BARS
    ) -> dict[str, pd.DataFrame]: ...


@dataclass(frozen=True, slots=True)
class DailyPanel:
    """Daily bars for a set of symbols, with the failures kept separate.

    `unavailable` is not a detail to log and move past. The warm start seeds
    live trading buffers, so a symbol whose real bars could not be fetched has
    to stay empty rather than be filled with anything - and the caller can only
    do that if it is told which symbols those were.
    """

    frames: dict[str, pd.DataFrame]
    unavailable: tuple[str, ...]


async def fetch_daily_panel(
    source: HistoricalBarSource, symbols: Sequence[str], n_bars: int = DEFAULT_BARS
) -> DailyPanel:
    """Daily bars for many symbols, preferring one bulk request.

    The per-symbol fallback checks `last_was_synthetic` after every call and
    discards anything that degraded, because both real sources answer a failed
    fetch with a seeded random walk. That is the right behaviour for a screen,
    which should show clearly-labelled synthetic data rather than nothing, and
    the wrong behaviour for a buffer that strategies size real orders from.
    Reading the flag is only sound because these calls are sequential.
    """
    symbols = list(dict.fromkeys(symbols))
    bulk = getattr(source, "get_daily_bars_many", None)
    if callable(bulk):
        frames = await bulk(symbols, n_bars)
    else:
        frames = {}
        for symbol in symbols:
            frame = await source.get_daily_bars(symbol, n_bars)
            if getattr(source, "last_was_synthetic", False):
                continue
            if frame is not None and not frame.empty:
                frames[symbol] = frame

    unavailable = tuple(symbol for symbol in symbols if symbol not in frames)
    if unavailable:
        logger.warning(
            "No real daily bars for %d of %d symbols - they are left unseeded rather than "
            "filled: %s",
            len(unavailable),
            len(symbols),
            ", ".join(unavailable),
        )
    return DailyPanel(frames=frames, unavailable=unavailable)


class YFinanceHistoryLike(Protocol):
    """The slice of YFinanceHistorySource used here, so the real one can be
    faked without importing yfinance in a test."""

    async def get_bars(
        self, symbol: str, period: str = ..., interval: str = ...
    ) -> pd.DataFrame: ...


def seed_for_symbol(symbol: str) -> int:
    """Derived from the symbol string rather than hash(), which is randomised
    per process - the same symbol must produce the same series across runs."""
    return sum(ord(char) for char in symbol) + 1


class SyntheticHistorySource:
    """The seeded random walk, relabelled onto daily timestamps.

    Moved here from presentation/synthetic_bars.py so the presentation layer no
    longer decides where bars come from. Behaviour is unchanged.
    """

    async def get_daily_bars(self, symbol: str, n_bars: int = DEFAULT_BARS) -> pd.DataFrame:
        source = SyntheticMarketDataSource(seed=seed_for_symbol(symbol), interval_seconds=0.0)
        start = datetime.now(UTC) - timedelta(days=n_bars)
        rows: list[dict[str, object]] = []
        async for tick in source.stream_ticks([symbol]):
            rows.append(
                {
                    "ts": start + timedelta(days=len(rows)),
                    "open": tick.price,
                    "high": tick.price,
                    "low": tick.price,
                    "close": tick.price,
                    "volume": tick.volume,
                }
            )
            if len(rows) >= n_bars:
                break
        return pd.DataFrame(rows)


class RealHistorySource:
    """Real daily bars via yfinance, with a documented synthetic fallback.

    The fallback matters: a rate-limited or unreachable feed should degrade one
    screen to clearly-labelled synthetic data rather than leave it blank, but
    it must never do so *silently* - believing you are looking at real market
    data when you are not is worse than seeing nothing. Callers can check
    `last_was_synthetic` to label the display.
    """

    def __init__(
        self,
        yf_source: YFinanceHistoryLike | None = None,
        fallback: HistoricalBarSource | None = None,
    ) -> None:
        if yf_source is None:
            from qat.data.yfinance_source import YFinanceHistorySource

            yf_source = YFinanceHistorySource()
        self.yf_source = yf_source
        self.fallback = fallback or SyntheticHistorySource()
        self.last_was_synthetic = False

    async def get_daily_bars(self, symbol: str, n_bars: int = DEFAULT_BARS) -> pd.DataFrame:
        period = _period_for(n_bars)
        frame = await self.yf_source.get_bars(symbol, period=period, interval="1d")

        if frame is None or frame.empty:
            logger.warning(
                "No real daily bars for %s - falling back to synthetic. This data is NOT real.",
                symbol,
            )
            self.last_was_synthetic = True
            return await self.fallback.get_daily_bars(symbol, n_bars)

        self.last_was_synthetic = False
        trimmed: pd.DataFrame = frame.tail(n_bars).reset_index(drop=True)
        return trimmed


def _period_for(n_bars: int) -> str:
    """Yahoo takes a period string, not a bar count. Rounded generously
    upward - roughly 252 trading days a year, and asking for too much history
    costs nothing while asking for too little silently truncates the window an
    indicator needs."""
    if n_bars <= 20:
        return "1mo"
    if n_bars <= 65:
        return "3mo"
    if n_bars <= 130:
        return "6mo"
    if n_bars <= 260:
        return "1y"
    if n_bars <= 520:
        return "2y"
    return "5y"


def resolve_history_source(settings: Settings) -> HistoricalBarSource:
    if settings.market_data_source == "alpaca":
        try:
            from qat.data.alpaca_source import AlpacaHistorySource

            return AlpacaHistorySource(feed=settings.alpaca_data_feed)
        except Exception as exc:  # noqa: BLE001 - degrade, but loudly
            logger.warning(
                "Could not build the Alpaca history source (%s) - falling back to SYNTHETIC "
                "bars. This data is NOT real.",
                exc,
            )
            return SyntheticHistorySource()
    if settings.market_data_source == "yfinance":
        return RealHistorySource()
    return SyntheticHistorySource()
