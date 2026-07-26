"""Historical bar source resolution (spec M14).

The property worth protecting: a degraded real feed must never look like a
working one. Falling back to synthetic data is acceptable; doing so silently
is not.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.history import (
    RealHistorySource,
    SyntheticHistorySource,
    _period_for,
    resolve_history_source,
    seed_for_symbol,
)


class _StubYF:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[dict] = []

    async def get_bars(self, symbol, period="6mo", interval="1d"):
        self.calls.append({"symbol": symbol, "period": period, "interval": interval})
        return self.frame


def _bars(n: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=n, freq="1D", tz="UTC"),
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1000.0] * n,
        }
    )


def test_settings_default_to_synthetic():
    assert isinstance(resolve_history_source(Settings(_env_file=None)), SyntheticHistorySource)


def test_settings_can_select_the_real_source():
    settings = Settings(_env_file=None, market_data_source="yfinance")
    assert isinstance(resolve_history_source(settings), RealHistorySource)


@pytest.mark.asyncio
async def test_synthetic_bars_are_reproducible_across_runs():
    """Seeded from the symbol string, not hash(), which is randomised per
    process - otherwise the same screen gives different answers each launch."""
    first = await SyntheticHistorySource().get_daily_bars("AAPL", n_bars=50)
    second = await SyntheticHistorySource().get_daily_bars("AAPL", n_bars=50)
    assert first["close"].tolist() == second["close"].tolist()
    assert seed_for_symbol("AAPL") == seed_for_symbol("AAPL")


@pytest.mark.asyncio
async def test_synthetic_bars_differ_by_symbol():
    apple = await SyntheticHistorySource().get_daily_bars("AAPL", n_bars=50)
    microsoft = await SyntheticHistorySource().get_daily_bars("MSFT", n_bars=50)
    assert apple["close"].tolist() != microsoft["close"].tolist()


@pytest.mark.asyncio
async def test_real_bars_are_returned_when_the_feed_works():
    source = RealHistorySource(yf_source=_StubYF(_bars(120)))
    frame = await source.get_daily_bars("AAPL", n_bars=100)
    assert len(frame) == 100
    assert source.last_was_synthetic is False


@pytest.mark.asyncio
async def test_an_empty_feed_falls_back_to_synthetic_and_says_so(caplog):
    source = RealHistorySource(yf_source=_StubYF(pd.DataFrame()))
    with caplog.at_level("WARNING"):
        frame = await source.get_daily_bars("AAPL", n_bars=50)

    assert not frame.empty, "the screen should still render something"
    assert source.last_was_synthetic is True, "callers must be able to label it"
    assert "NOT real" in caplog.text


@pytest.mark.asyncio
async def test_the_synthetic_flag_resets_when_the_feed_recovers():
    stub = _StubYF(pd.DataFrame())
    source = RealHistorySource(yf_source=stub)
    await source.get_daily_bars("AAPL", n_bars=50)
    assert source.last_was_synthetic is True

    stub.frame = _bars(60)
    await source.get_daily_bars("AAPL", n_bars=50)
    assert source.last_was_synthetic is False


@pytest.mark.asyncio
async def test_the_requested_period_covers_the_requested_bar_count():
    """Asking for too short a period silently truncates the window an
    indicator needs, which shows up as a strategy that never fires."""
    stub = _StubYF(_bars(600))
    await RealHistorySource(yf_source=stub).get_daily_bars("AAPL", n_bars=300)
    assert stub.calls[0]["period"] == "2y"
    assert stub.calls[0]["interval"] == "1d"


@pytest.mark.parametrize(
    ("n_bars", "expected"),
    [(10, "1mo"), (50, "3mo"), (100, "6mo"), (250, "1y"), (400, "2y"), (900, "5y")],
)
def test_period_grows_with_the_bar_count(n_bars, expected):
    assert _period_for(n_bars) == expected
