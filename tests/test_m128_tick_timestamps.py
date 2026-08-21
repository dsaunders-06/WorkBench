"""M128: the feed's delay was invisible to the rail that exists to see it.

`YFinanceMarketDataSource._poll_once` stamped every tick `ts=now` - the moment
the poll returned, not the moment the price printed. Yahoo publishes ASX
intraday about twenty minutes late (MEASURED 21 August: the ASX opened at 10:00,
the first bars appeared at 10:22, and the bar visible at 10:22 was 10:02), so a
twenty-minute-old price entered the system labelled as if it had just traded.

The staleness rail measures price age from `tick.ts`. Under receive-time
stamping it could not see the delay AT ALL - it measured feed silence and
nothing else, which is why a whole session reported `excluded 0` while every
price in it was twenty minutes old. Its own config comment says the hazard is
"sizing a trade against an hour-old print"; it could not have detected one.

**The fix is coupled, which is why it was not done under a four-hour clock on
the Friday.** Telling the truth about `ts` makes every ASX tick ~1,200s old on
arrival, which is past the 900s threshold - so stamping bar time ALONE would
have excluded every symbol from signals and traded nothing at all, silently.
The rail now measures staleness BEYOND the feed's known structural delay.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.market_data import MarketDataFeed
from qat.data.yfinance_source import YFinanceMarketDataSource
from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent

_BAR = datetime(2026, 8, 21, 0, 2, tzinfo=UTC)  # 10:02 AEST


class _FrameClient:
    def __init__(self, ts: datetime) -> None:
        self.ts = ts

    def download(self, tickers, **kwargs):
        index = pd.DatetimeIndex([self.ts], name="Datetime")
        return pd.DataFrame(
            {"Open": [1.9], "High": [1.92], "Low": [1.89], "Close": [1.91], "Volume": [1000.0]},
            index=index,
        )


@pytest.mark.asyncio
async def test_a_tick_carries_the_bars_time_not_the_arrival_time() -> None:
    source = YFinanceMarketDataSource(client=_FrameClient(_BAR), poll_seconds=0.0)

    stream = source.stream_ticks(["MGR.AX"])
    tick = await anext(stream)
    await stream.aclose()

    assert tick.ts.replace(tzinfo=UTC) == _BAR
    assert tick.ts.replace(tzinfo=UTC) != datetime.now(UTC)


@pytest.mark.asyncio
async def test_the_delay_alone_does_not_make_a_symbol_stale() -> None:
    """The regression the coupling exists to prevent. A 20-minute-old price on
    a 20-minute-delayed feed is NORMAL, and a rail that excluded it would stop
    the system trading entirely while reporting nothing wrong."""
    bus = EventBus()
    events: list[DataStaleEvent] = []
    bus.subscribe(DataStaleEvent, lambda event: events.append(event))

    feed = MarketDataFeed(
        bus,
        source=None,  # type: ignore[arg-type]
        symbols=["MGR.AX"],
        staleness_seconds=900.0,
        source_delay_seconds=1200.0,
    )
    feed._last_seen["MGR.AX"] = datetime.now(UTC) - timedelta(seconds=1250)

    await feed._check_staleness_once()

    assert feed._stale_symbols.get("MGR.AX") is not True


@pytest.mark.asyncio
async def test_a_print_genuinely_older_than_the_delay_is_still_caught() -> None:
    """The rail must not be blinded by the accommodation. An hour-old print on
    a twenty-minute feed is forty minutes of real staleness."""
    bus = EventBus()
    feed = MarketDataFeed(
        bus,
        source=None,  # type: ignore[arg-type]
        symbols=["MGR.AX"],
        staleness_seconds=900.0,
        source_delay_seconds=1200.0,
    )
    feed._last_seen["MGR.AX"] = datetime.now(UTC) - timedelta(seconds=3600)

    await feed._check_staleness_once()

    assert feed._stale_symbols.get("MGR.AX") is True


@pytest.mark.asyncio
async def test_a_real_time_source_is_unchanged() -> None:
    """Zero delay means the rail behaves exactly as it always did - the US path
    had no defect here and must not acquire one."""
    bus = EventBus()
    feed = MarketDataFeed(
        bus,
        source=None,  # type: ignore[arg-type]
        symbols=["AAPL"],
        staleness_seconds=900.0,
        source_delay_seconds=0.0,
    )
    feed._last_seen["AAPL"] = datetime.now(UTC) - timedelta(seconds=1000)

    await feed._check_staleness_once()

    assert feed._stale_symbols.get("AAPL") is True


def test_the_measured_delay_is_recorded_as_a_setting() -> None:
    """1,200s is a CLAIM ABOUT THE VENDOR, measured against the live feed, not
    a tolerance to be tuned upward when something trips."""
    assert Settings(_env_file=None).market_data_delay_seconds == 1200.0
