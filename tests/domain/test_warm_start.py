"""The warm start that makes a daily cadence viable (M27a)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.data.bars import MultiSymbolAggregator
from qat.data.macro_fred import MacroObservation
from qat.domain.bus import EventBus
from qat.domain.regime_engine.engine import RegimeEngine
from qat.domain.warm_start import WarmStart

_DAY = 86_400.0


def _daily_frame(days: int, last: datetime | None = None) -> pd.DataFrame:
    last = last or datetime.now(UTC) - timedelta(days=1)
    rows = []
    for i in range(days):
        day = (last - timedelta(days=days - 1 - i)).replace(
            hour=4, minute=0, second=0, microsecond=0
        )
        price = 100.0 + i
        rows.append(
            {
                "ts": day,
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price + 0.5,
                "volume": 1_000.0,
            }
        )
    return pd.DataFrame(rows)


class _Panel:
    def __init__(self, available: set[str], days: int = 80) -> None:
        self.available = available
        self.days = days

    async def get_daily_bars_many(self, symbols, n_bars=300):
        return {s: _daily_frame(self.days) for s in symbols if s in self.available}

    async def get_daily_bars(self, symbol, n_bars=300):  # pragma: no cover - bulk path wins
        return _daily_frame(self.days)


class _Macro:
    def __init__(self) -> None:
        self.requested: list[str] = []

    async def fetch_series(self, series_id: str) -> list[MacroObservation]:
        self.requested.append(series_id)
        first = datetime.now(UTC) - timedelta(days=400)
        return [
            MacroObservation(series=series_id, ts=first + timedelta(days=i), value=1.0 + i * 0.01)
            for i in range(400)
        ]


@pytest.mark.asyncio
async def test_every_aggregator_is_seeded_not_just_the_strategy_engine():
    """The bridge keeps its own aggregator and its ATR sets the stop distance,
    which sets the position size. Seeding the strategy engine alone would move
    the strategies to daily bars while sizing them off an empty buffer."""
    strategy_bars = MultiSymbolAggregator(interval_seconds=_DAY)
    bridge_bars = MultiSymbolAggregator(interval_seconds=_DAY)
    feature_bars = MultiSymbolAggregator(interval_seconds=_DAY)

    warm_start = WarmStart(
        _Panel({"SPY", "AAPL"}),
        _Macro(),
        ["AAPL"],
        "SPY",
        aggregators=(strategy_bars, bridge_bars, feature_bars),
    )
    await warm_start.seed()

    for aggregator in (strategy_bars, bridge_bars, feature_bars):
        assert len(aggregator.frame("SPY")) == 80
        assert len(aggregator.frame("AAPL")) == 80


@pytest.mark.asyncio
async def test_a_symbol_without_real_bars_is_left_empty():
    """Never filled with anything. A buffer positions are sized from must not
    contain a random walk."""
    bars = MultiSymbolAggregator(interval_seconds=_DAY)

    warm_start = WarmStart(
        _Panel({"SPY"}), _Macro(), ["AAPL", "DELISTED"], "SPY", aggregators=(bars,)
    )
    await warm_start.seed()

    assert len(bars.frame("SPY")) == 80
    assert bars.frame("DELISTED").empty
    assert warm_start.seeded_symbols == ("SPY",)


@pytest.mark.asyncio
async def test_the_regime_engine_is_seeded_with_varying_macro_columns():
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")

    warm_start = WarmStart(
        _Panel({"SPY", "AAPL", "MSFT"}, days=120),
        _Macro(),
        ["AAPL", "MSFT"],
        "SPY",
        regime_engine=engine,
        macro_series=("VIXCLS", "T10Y3M", "BAA10Y"),
    )
    await warm_start.seed()

    matrix = engine._feature_builder.feature_matrix()
    assert len(matrix) == 120
    for column in (2, 3, 4):  # vix, yield curve, credit spread
        assert matrix[:, column].max() > matrix[:, column].min()


@pytest.mark.asyncio
async def test_a_failed_warm_start_never_blocks_startup(caplog):
    """A cold start is the state every milestone before this one ran in. An
    application that will not open is worse."""

    class _Broken:
        async def get_daily_bars_many(self, symbols, n_bars=300):
            raise RuntimeError("Alpaca unreachable")

    warm_start = WarmStart(_Broken(), _Macro(), ["AAPL"], "SPY")

    with caplog.at_level(logging.ERROR, logger="qat.domain.warm_start"):
        await warm_start.start()

    assert "Warm start FAILED" in caplog.text


@pytest.mark.asyncio
async def test_no_bars_at_all_is_reported_as_an_error(caplog):
    warm_start = WarmStart(_Panel(set()), _Macro(), ["AAPL"], "SPY")

    with caplog.at_level(logging.ERROR, logger="qat.domain.warm_start"):
        await warm_start.seed()

    assert "starts cold" in caplog.text


@pytest.mark.asyncio
async def test_a_missing_benchmark_leaves_the_regime_engine_cold_and_says_so(caplog):
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")
    warm_start = WarmStart(_Panel({"AAPL"}), _Macro(), ["AAPL"], "SPY", regime_engine=engine)

    with caplog.at_level(logging.ERROR, logger="qat.domain.warm_start"):
        await warm_start.seed()

    assert not engine._feature_builder.feature_matrix().size
    assert "default regime" in caplog.text
