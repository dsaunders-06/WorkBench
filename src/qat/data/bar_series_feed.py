"""Daily-bar tickers published onto the bus as `MacroEvent`, so a Yahoo series
can fill a regime-engine column that until now only FRED could reach.

`RegimeFeatureBuilder.vix_series` became configurable on 8 September, and the
test that made it so carried a warning: *"NAMING IT IS NOT FEEDING IT. The
column is filled from `MacroEvent`, which the macro feed publishes from FRED
alone; `^AXVI` is a Yahoo ticker. Until a bridge exists, pointing this at it
would leave the column at its default forever - silently."* This is that bridge.

⚠️ **IT DOES NOT USE `HistoricalBarSource`, AND THAT IS THE WHOLE POINT.**
`RealHistorySource.get_daily_bars` falls back to SYNTHETIC bars when the fetch
fails - deliberately, and documented, because degrading one screen beats leaving
it blank. Feeding that into the regime engine is a different matter entirely: a
synthetic random walk would enter the model as `^AXVI` and size the book, and
nothing downstream could tell. So this takes the raw source, which returns an
EMPTY frame on failure, and refuses to publish anything it cannot vouch for.
When a source does report a fallback, this refuses that too.

⚠️ **THE REFUSALS ARE THE FEATURE.** An empty frame, a stale bar and a
non-finite close all publish NOTHING and say so at WARNING. The alternative -
publishing the last thing available - freezes a column at a value the market
left behind, which is invisible: the engine fits happily on a flat column.
Measured 8 September 2026, `^AJOVIX` returns a 404 and `AU3M=F` returns zero
rows, so the empty case is not hypothetical.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

import pandas as pd

from qat.domain.bus import EventBus
from qat.domain.events import MacroEvent

logger = logging.getLogger(__name__)

# How old a daily close may be and still describe the present.
#
# Five days covers a long weekend plus a public holiday either side, which is
# the longest ordinary gap in an exchange calendar. Beyond that the series has
# stopped rather than paused, and publishing its last value would freeze a
# regime-engine column at a reading the market has left behind.
DEFAULT_MAX_BAR_AGE_DAYS = 5


class BarSeriesSource(Protocol):
    """The raw bar fetch - the one WITHOUT a synthetic fallback."""

    async def get_bars(
        self, symbol: str, period: str = ..., interval: str = ...
    ) -> pd.DataFrame: ...


class BarSeriesFeed:
    """Engine (per `domain.orchestrator.Engine`): polls each configured ticker
    and publishes its latest daily close as a `MacroEvent`.

    The event's `series` is the TICKER as configured, so a consumer selecting on
    `vix_series="^AXVI"` matches without a translation table in between.
    """

    name = "bar-series-feed"

    def __init__(
        self,
        bus: EventBus,
        source: BarSeriesSource,
        series_ids: Sequence[str],
        poll_interval_seconds: float = 3600.0,
        max_age_days: int = DEFAULT_MAX_BAR_AGE_DAYS,
    ) -> None:
        self.bus = bus
        self.source = source
        self.series_ids = list(series_ids)
        self.poll_interval_seconds = poll_interval_seconds
        self.max_age_days = max_age_days
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def poll_once(self) -> None:
        for symbol in self.series_ids:
            try:
                frame = await self.source.get_bars(symbol, period="3mo", interval="1d")
            except Exception:  # noqa: BLE001 - one bad ticker must not mute the rest
                logger.exception(
                    "Bar series %s could not be fetched - the column it feeds keeps its "
                    "previous value",
                    symbol,
                )
                continue

            event = self._event_for(symbol, frame)
            if event is not None:
                logger.info(
                    "Bar series %s = %s (bar of %s)",
                    event.series,
                    event.value,
                    event.ts.date().isoformat(),
                )
                await self.bus.publish(event)

    def _event_for(self, symbol: str, frame: pd.DataFrame) -> MacroEvent | None:
        """The latest close as an event, or `None` with a reason logged.

        ⚠️ Every branch here publishes NOTHING rather than something doubtful.
        A regime column that keeps its previous value is visibly stale to
        anything that checks; a column filled with a fabricated or stale number
        is not visible to anything at all.
        """
        # ⚠️ A source that fell back to synthetic data says so. `RealHistorySource`
        # sets this, and its synthetic bars must never reach the regime engine
        # wearing a real ticker's name.
        if getattr(self.source, "last_was_synthetic", False):
            logger.warning(
                "Bar series %s came back SYNTHETIC - not published. A generated series "
                "must never enter the regime engine under a real ticker's name",
                symbol,
            )
            return None

        if frame is None or frame.empty or "close" not in frame or "ts" not in frame:
            logger.warning(
                "Bar series %s returned no usable bars - not published. Measured 8 "
                "September 2026: ^AJOVIX 404s and AU3M=F returns zero rows, so a "
                "ticker that simply does not exist looks exactly like this",
                symbol,
            )
            return None

        last = frame.iloc[-1]
        value = float(last["close"])
        if not math.isfinite(value):
            logger.warning("Bar series %s last close is not finite - not published", symbol)
            return None

        ts = pd.Timestamp(last["ts"])
        stamp = ts.to_pydatetime()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        age_days = (datetime.now(UTC) - stamp).days
        if age_days > self.max_age_days:
            logger.warning(
                "Bar series %s last traded %d days ago (%s), past the %d-day limit - not "
                "published. Publishing it would freeze the column it feeds at a reading "
                "the market has left behind",
                symbol,
                age_days,
                stamp.date().isoformat(),
                self.max_age_days,
            )
            return None

        return MacroEvent(series=symbol, value=value, ts=stamp)

    async def _poll_loop(self) -> None:
        # A poll that raises must never end the loop - the same rule `MacroFeed`
        # records, and for the same reason: an unhandled exception here would
        # kill the task silently and freeze the column for the rest of the
        # session.
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop outlives any one poll
                logger.exception("Bar series poll failed")
            await asyncio.sleep(self.poll_interval_seconds)


def resolve_bar_series_feed(settings: object, bus: EventBus) -> BarSeriesFeed | None:
    """The bridge, or `None` with the reason logged.

    ⚠️ REFUSES ON A SYNTHETIC MARKET-DATA SETTING rather than bridging anyway.
    With `market_data_source="synthetic"` there is no real ticker to fetch, and
    a generated series entering the regime engine under the name `^AXVI` is
    precisely what `_event_for`'s synthetic guard exists to stop. Better to
    publish nothing and say why.
    """
    series = tuple(getattr(settings, "bar_macro_series", ()) or ())
    if not series:
        return None
    if getattr(settings, "market_data_source", "synthetic") != "yfinance":
        logger.warning(
            "bar_macro_series names %s but market_data_source is %r - the bridge is NOT "
            "started, because there is no real feed behind it and a generated series must "
            "not reach the regime engine wearing a real ticker's name",
            ", ".join(series),
            getattr(settings, "market_data_source", "synthetic"),
        )
        return None

    from qat.data.yfinance_source import YFinanceHistorySource

    logger.info("Bridging daily-bar series onto the bus: %s", ", ".join(series))
    return BarSeriesFeed(bus, YFinanceHistorySource(), series)
