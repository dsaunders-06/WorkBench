"""yfinance adapter (spec M14).

Nothing here touches the network. The client is faked, so these test the
parsing, gap-handling and failure behaviour - the parts that are ours. A live
call is unverified in this environment, same as IBKR and Anthropic.
"""

from __future__ import annotations

import asyncio
import logging

import pandas as pd
import pytest

from qat.data.yfinance_source import (
    YFinanceHistorySource,
    YFinanceMarketDataSource,
    fill_missing_intervals,
    normalise_frame,
)


def _yahoo_frame(n: int = 5, start: str = "2026-07-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq="1D", name="Date")
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.5 + i for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=index,
    )


def _multi_symbol_frame(symbols: tuple[str, ...] = ("AAPL", "MSFT")) -> pd.DataFrame:
    index = pd.date_range("2026-07-01", periods=3, freq="1D", name="Date")
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], symbols])
    data = {}
    for field_index, field in enumerate(["Open", "High", "Low", "Close", "Volume"]):
        for symbol_index, symbol in enumerate(symbols):
            base = 100.0 + field_index + symbol_index * 50
            data[(field, symbol)] = [base, base + 1, base + 2]
    return pd.DataFrame(data, index=index, columns=columns)


class _FakeClient:
    def __init__(self, frame: pd.DataFrame | Exception) -> None:
        self.frame = frame
        self.calls: list[dict] = []

    def download(self, tickers, **kwargs):
        self.calls.append({"tickers": tickers, **kwargs})
        if isinstance(self.frame, Exception):
            raise self.frame
        return self.frame


# --- Normalisation ------------------------------------------------------------


def test_yahoo_columns_are_renamed_to_our_shape():
    frame = normalise_frame(_yahoo_frame())
    assert list(frame.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert len(frame) == 5


def test_timestamps_are_normalised_to_utc():
    """Yahoo returns tz-aware for intraday and naive for daily; downstream code
    should not have to guess which it got."""
    frame = normalise_frame(_yahoo_frame())
    assert str(frame["ts"].dt.tz) == "UTC"


def test_a_multi_symbol_frame_is_split_by_symbol():
    """This column shape only appears when more than one ticker is requested,
    so single-symbol testing never surfaces it."""
    raw = _multi_symbol_frame()
    apple = normalise_frame(raw, "AAPL")
    microsoft = normalise_frame(raw, "MSFT")

    assert not apple.empty and not microsoft.empty
    assert apple["close"].iloc[0] != microsoft["close"].iloc[0]


def test_an_empty_frame_yields_a_well_formed_empty_result():
    frame = normalise_frame(pd.DataFrame())
    assert frame.empty
    assert list(frame.columns) == ["ts", "open", "high", "low", "close", "volume"]


def test_a_frame_missing_price_columns_is_rejected_rather_than_half_parsed():
    raw = pd.DataFrame({"Volume": [1, 2, 3]})
    assert normalise_frame(raw).empty


def test_rows_without_a_close_are_dropped():
    raw = _yahoo_frame()
    raw.loc[raw.index[2], "Close"] = None
    assert len(normalise_frame(raw)) == 4


# --- Gap filling --------------------------------------------------------------


def _intraday_frame(n: int = 6) -> pd.DataFrame:
    index = pd.date_range("2026-07-23 14:00", periods=n, freq="1min", name="Datetime", tz="UTC")
    return pd.DataFrame(
        {
            "Open": [100.0] * n,
            "High": [101.0] * n,
            "Low": [99.0] * n,
            "Close": [100.5 + i for i in range(n)],
            "Volume": [1000.0] * n,
        },
        index=index,
    )


def test_missing_minutes_are_filled_onto_a_continuous_timeline():
    raw = _intraday_frame(n=6)
    sparse = raw.drop(raw.index[[1, 2]])  # two quiet minutes, as a sparse feed omits
    frame = fill_missing_intervals(normalise_frame(sparse), "1m")

    assert len(frame) == 6
    gaps = frame["ts"].diff().dropna().dt.total_seconds().unique()
    assert list(gaps) == [60.0]


def test_filled_rows_carry_price_forward_and_zero_volume():
    raw = _intraday_frame(n=5)
    sparse = raw.drop(raw.index[[1]])
    frame = fill_missing_intervals(normalise_frame(sparse), "1m")

    filled = frame.iloc[1]
    assert filled["close"] == frame.iloc[0]["close"]
    assert filled["open"] == filled["close"]
    assert filled["volume"] == 0.0


def test_daily_bars_are_never_gap_filled():
    """Regression cover for a bug caught by a live pull: Yahoo already returns
    one row per *trading* day, so reindexing onto a calendar timeline invents a
    flat bar for every weekend and holiday. A real 1-year SPY request became
    365 rows instead of 251, and the invented zero-return days dragged realized
    volatility roughly 17% below its true value."""
    raw = _yahoo_frame(n=10)
    # Drop a Saturday/Sunday pair the way a real trading calendar does.
    weekdays_only = raw[raw.index.dayofweek < 5]
    frame = fill_missing_intervals(normalise_frame(weekdays_only), "1d")

    assert len(frame) == len(weekdays_only)
    assert (frame["ts"].dt.dayofweek < 5).all(), "no weekend rows may be invented"


def test_a_realistic_year_of_daily_bars_keeps_its_trading_day_count():
    trading_days = pd.bdate_range("2026-01-01", periods=251, name="Date")
    raw = pd.DataFrame(
        {
            "Open": [100.0] * 251,
            "High": [101.0] * 251,
            "Low": [99.0] * 251,
            "Close": [100.5] * 251,
            "Volume": [1000.0] * 251,
        },
        index=trading_days,
    )
    frame = fill_missing_intervals(normalise_frame(raw), "1d")
    assert len(frame) == 251


def test_an_unknown_interval_is_passed_through_untouched():
    frame = normalise_frame(_yahoo_frame())
    assert fill_missing_intervals(frame, "3mo").equals(frame)


# --- History source -----------------------------------------------------------


@pytest.mark.asyncio
async def test_history_returns_normalised_bars():
    source = YFinanceHistorySource(client=_FakeClient(_yahoo_frame(n=10)))
    frame = await source.get_bars("AAPL")
    assert len(frame) == 10
    assert list(frame.columns) == ["ts", "open", "high", "low", "close", "volume"]


@pytest.mark.asyncio
async def test_history_requests_adjusted_prices():
    """Unadjusted prices put a false gap in the series at every split."""
    client = _FakeClient(_yahoo_frame())
    await YFinanceHistorySource(client=client).get_bars("AAPL")
    assert client.calls[0]["auto_adjust"] is True


@pytest.mark.asyncio
async def test_a_history_failure_degrades_to_an_empty_frame():
    """Callers already treat too-few-bars as a skip; an exception here would
    propagate into an engine loop instead."""
    source = YFinanceHistorySource(client=_FakeClient(ConnectionError("rate limited")))
    frame = await source.get_bars("AAPL")
    assert frame.empty


# --- Quote stream -------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_stream_yields_one_tick_per_symbol_per_poll():
    source = YFinanceMarketDataSource(client=_FakeClient(_multi_symbol_frame()), poll_seconds=0.0)
    ticks = []
    async for tick in source.stream_ticks(["AAPL", "MSFT"]):
        ticks.append(tick)
        if len(ticks) >= 4:
            break

    assert {tick.symbol for tick in ticks} == {"AAPL", "MSFT"}
    assert all(tick.price > 0 for tick in ticks)
    assert all(tick.ts.tzinfo is not None for tick in ticks)


@pytest.mark.asyncio
async def test_an_empty_symbol_list_ends_immediately():
    source = YFinanceMarketDataSource(client=_FakeClient(_yahoo_frame()), poll_seconds=0.0)
    assert [tick async for tick in source.stream_ticks([])] == []


@pytest.mark.asyncio
async def test_the_stream_keeps_retrying_instead_of_ending():
    """M119. This reverses the original design, and the first live ASX session
    is why.

    Ending the iterator was meant to let MarketDataFeed's staleness detector
    fire and trip the kill-switch. It never could: staleness is per-symbol and
    skips symbols that have not ticked even once, so a feed that failed from its
    first poll produced no ticks, no staleness and no halt - and the stream was
    over for the session.

    On 21 August all five polls from the ASX open landed inside Yahoo's ~20
    minute publication delay. The stream ended at 10:04:20; the data it was
    waiting for arrived at 10:22. The market stayed open for another five and a
    half hours with nothing watching it.
    """
    source = YFinanceMarketDataSource(
        client=_FakeClient(pd.DataFrame()), poll_seconds=0.0, max_consecutive_failures=3
    )

    stream = source.stream_ticks(["AAPL"])
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.25)
    await stream.aclose()


@pytest.mark.asyncio
async def test_backoff_grows_while_down_and_is_capped():
    """A feed that recovers must be picked up in a poll or two, not an hour."""
    source = YFinanceMarketDataSource(
        client=_FakeClient(_yahoo_frame()),
        poll_seconds=10.0,
        max_consecutive_failures=3,
        max_backoff_seconds=120.0,
    )

    assert source._delay_after(0) == 10.0  # healthy: normal cadence
    assert source._delay_after(2) == 10.0  # still inside the strike count
    first = source._delay_after(3)
    second = source._delay_after(4)
    assert first > 10.0 and second > first
    assert source._delay_after(50) == 120.0  # capped, never unbounded


@pytest.mark.asyncio
async def test_a_feed_that_was_down_yields_again_and_says_so(caplog):
    """The ASX open case: empty polls past the strike count, then real data."""

    class _LateClient:
        def __init__(self) -> None:
            self.count = 0

        def download(self, tickers, **kwargs):
            self.count += 1
            # Three empty polls - one more than the strike count, so the feed is
            # declared down - and then Yahoo publishes.
            if self.count <= 3:
                return pd.DataFrame()
            return _yahoo_frame()

    source = YFinanceMarketDataSource(
        client=_LateClient(), poll_seconds=0.0, max_consecutive_failures=2
    )

    stream = source.stream_ticks(["AAPL"])
    with caplog.at_level(logging.WARNING, logger="qat.data.yfinance_source"):
        tick = await asyncio.wait_for(anext(stream), timeout=2.0)
    await stream.aclose()

    assert tick.price > 0
    assert any("recovered" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_a_transient_failure_does_not_end_the_stream():
    class _FlakyClient:
        def __init__(self) -> None:
            self.count = 0

        def download(self, tickers, **kwargs):
            self.count += 1
            if self.count <= 2:
                raise ConnectionError("transient")
            return _yahoo_frame()

    source = YFinanceMarketDataSource(
        client=_FlakyClient(), poll_seconds=0.0, max_consecutive_failures=5
    )
    ticks = []
    async for tick in source.stream_ticks(["AAPL"]):
        ticks.append(tick)
        break

    assert len(ticks) == 1


@pytest.mark.asyncio
async def test_the_stream_satisfies_the_market_data_source_protocol():
    from qat.data.market_data import MarketDataFeed
    from qat.domain.bus import EventBus
    from qat.domain.events import MarketDataEvent

    seen: list[MarketDataEvent] = []

    async def _capture(event: MarketDataEvent) -> None:
        seen.append(event)

    bus = EventBus()
    bus.subscribe(MarketDataEvent, _capture)
    source = YFinanceMarketDataSource(client=_FakeClient(_yahoo_frame()), poll_seconds=0.0)
    feed = MarketDataFeed(bus, source, ["AAPL"], staleness_seconds=999)

    await feed.start()
    for _ in range(50):
        if seen:
            break
        await _sleep_tick()
    await feed.stop()

    assert seen, "the feed should have published at least one MarketDataEvent"
    assert seen[0].symbol == "AAPL"


async def _sleep_tick() -> None:
    import asyncio

    await asyncio.sleep(0.01)
