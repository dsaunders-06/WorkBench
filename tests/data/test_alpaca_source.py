"""Alpaca market data (spec M17), driven by a fake client.

Same discipline as the Alpaca broker tests: the translation, the feed
selection and the failure behaviour are what matter, and they are tested
without credentials or network access.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from qat.config import Settings
from qat.data.alpaca_source import AlpacaHistorySource, AlpacaMarketDataSource
from qat.data.history import SyntheticHistorySource, resolve_history_source
from qat.presentation.runtime import resolve_market_data_source


class FakeTrade:
    def __init__(self, price: float, size: float) -> None:
        self.price = price
        self.size = size
        self.timestamp = datetime(2026, 7, 24, 15, 30, tzinfo=UTC)


class FakeBar:
    def __init__(self, day: int, close: float) -> None:
        self.timestamp = datetime(2026, 7, day, tzinfo=UTC)
        self.open = close - 1
        self.high = close + 1
        self.low = close - 2
        self.close = close
        self.volume = 1_000 * day


class FakeDataClient:
    def __init__(self, trades=None, bars=None, raises: bool = False) -> None:
        self._trades = trades if trades is not None else {}
        self._bars = bars if bars is not None else {}
        self.raises = raises
        self.requests: list[object] = []

    def get_stock_latest_trade(self, request_params):
        self.requests.append(request_params)
        if self.raises:
            raise RuntimeError("subscription does not permit this feed")
        return self._trades

    def get_stock_bars(self, request_params):
        self.requests.append(request_params)
        if self.raises:
            raise RuntimeError("subscription does not permit this feed")
        return self._bars


async def test_latest_trades_become_ticks():
    client = FakeDataClient(trades={"AAPL": FakeTrade(191.25, 300)})
    source = AlpacaMarketDataSource(client=client, poll_seconds=0.0)

    ticks = await source._poll_once(["AAPL"])

    assert len(ticks) == 1
    assert ticks[0].symbol == "AAPL"
    assert ticks[0].price == 191.25
    assert ticks[0].volume == 300  # trade size, not an invented figure


async def test_the_configured_feed_is_sent_on_the_request():
    client = FakeDataClient(trades={"AAPL": FakeTrade(100.0, 1)})
    source = AlpacaMarketDataSource(client=client, feed="sip")

    await source._poll_once(["AAPL"])

    assert client.requests[0].feed.value == "sip"


async def test_a_failed_poll_yields_no_ticks_rather_than_raising():
    """A dead feed must surface as staleness, not as an exception that kills
    the stream task."""
    source = AlpacaMarketDataSource(client=FakeDataClient(raises=True))

    assert await source._poll_once(["AAPL"]) == []


async def test_zero_or_missing_prices_are_skipped():
    client = FakeDataClient(trades={"AAPL": FakeTrade(0.0, 100)})
    source = AlpacaMarketDataSource(client=client)

    assert await source._poll_once(["AAPL"]) == []


async def test_the_stream_keeps_retrying_instead_of_ending():
    """This reverses the M17 design, and the first live session is why.

    Ending the iterator was meant to let MarketDataFeed's staleness detector
    raise DataStaleEvent and trip the kill-switch. It never could: staleness is
    per-symbol and skips symbols that have not ticked even once, so a feed that
    failed from the first poll produced no ticks, no staleness, no halt - and
    the stream was over for the session. Six hours of an open market passed
    with the banner reading AUTO-TRADE ACTIVE.

    Visibility now comes from MarketDataFeed's feed-level health check, which
    frees this loop to keep trying.
    """
    source = AlpacaMarketDataSource(
        client=FakeDataClient(raises=True), poll_seconds=0.0, max_consecutive_failures=2
    )

    stream = source.stream_ticks(["AAPL"])
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.25)
    await stream.aclose()


async def test_backoff_grows_while_down_and_is_capped():
    """A feed that recovers must be picked up in a poll or two, not an hour."""
    source = AlpacaMarketDataSource(
        client=FakeDataClient(),
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


async def test_a_recovered_feed_yields_again_and_says_so(caplog):
    class _FlakyClient:
        def __init__(self) -> None:
            self.calls = 0

        def get_stock_latest_trade(self, request_params):
            self.calls += 1
            # The startup probe consumes the first two calls; the rest are the
            # poll loop failing enough times to be declared down.
            if self.calls <= 5:
                raise RuntimeError("transient")
            return {"AAPL": SimpleNamespace(price=101.0, size=5, timestamp=datetime.now(UTC))}

        def get_stock_bars(self, request_params):  # pragma: no cover - unused here
            return {}

    source = AlpacaMarketDataSource(
        client=_FlakyClient(), poll_seconds=0.0, max_consecutive_failures=2
    )
    stream = source.stream_ticks(["AAPL"])
    with caplog.at_level(logging.WARNING, logger="qat.data.alpaca_source"):
        tick = await asyncio.wait_for(anext(stream), timeout=2.0)
    await stream.aclose()

    assert tick.price == 101.0
    assert any("recovered" in r.getMessage() for r in caplog.records)


async def test_daily_bars_are_translated_without_gap_filling():
    bars = {"AAPL": [FakeBar(20, 100.0), FakeBar(21, 101.0), FakeBar(24, 102.0)]}
    source = AlpacaHistorySource(client=FakeDataClient(bars=bars))

    frame = await source.get_daily_bars("AAPL", n_bars=10)

    assert list(frame.columns) == ["ts", "open", "high", "low", "close", "volume"]
    # Three trading days in, three rows out - the weekend gap between the 21st
    # and 24th must not be filled, which would drag realized vol below true.
    assert len(frame) == 3
    assert source.last_was_synthetic is False


async def test_history_falls_back_to_synthetic_but_records_that_it_did():
    source = AlpacaHistorySource(
        client=FakeDataClient(raises=True), fallback=SyntheticHistorySource()
    )

    frame = await source.get_daily_bars("AAPL", n_bars=25)

    assert not frame.empty
    assert source.last_was_synthetic is True, "a silent fallback would be the dangerous outcome"


def test_settings_can_select_alpaca_for_both_sources():
    settings = Settings(_env_file=None, market_data_source="alpaca", alpaca_data_feed="iex")

    # No credentials in the test environment, so both resolvers degrade to
    # synthetic - the point here is that "alpaca" is a valid, wired choice and
    # that a missing key never prevents the app from starting.
    assert resolve_market_data_source(settings) is not None
    assert resolve_history_source(settings) is not None


@pytest.mark.parametrize("feed", ["iex", "sip", "delayed_sip"])
def test_every_documented_feed_is_accepted(feed):
    assert Settings(_env_file=None, alpaca_data_feed=feed).alpaca_data_feed == feed
