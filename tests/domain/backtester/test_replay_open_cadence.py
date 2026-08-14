"""Evaluating on the morning's information set, not the finished day (W2).

G1's disagreement was attributed to evaluation FREQUENCY - live polling every
60 seconds against a forming bar, the replay once per closed bar. Measuring the
code says something more specific: the two evaluate against information sets a
FULL DAY apart. The replay primes day D's true OHLC and decides on it; live at
13:30:10 has a complete D-1 and one print of D.

`evaluate_at="open"` reproduces the live frame. This module pins the two
properties that make it trustworthy: the decision sees a stub, and the recorded
history is still the true daily bar.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.events import MarketDataEvent
from qat.domain.strategies.swing import SwingStrategy


def _bars(days: int = 90) -> pd.DataFrame:
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i * 0.5 for i in range(days)]
    return pd.DataFrame(
        {
            "open": [c - 0.25 for c in closes],
            "high": [c + 2.0 for c in closes],
            "low": [c - 2.0 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * days,
        },
        index=index,
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )


def test_an_unknown_cadence_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="evaluate_at"):
        ReplaySession(
            bars={"AAA": _bars()},
            strategies=[SwingStrategy()],
            settings=_settings(tmp_path),
            evaluate_at="midday",
        )


@pytest.mark.asyncio
async def test_the_completed_history_is_still_the_true_daily_bar(tmp_path: Path):
    """The property the whole harness rests on. The day is folded in through
    ticks rather than primed, and a flattened bar would collapse ATR - which
    sets the stop distance, which sets position size, which every cap gates on.
    """
    frame = _bars()
    session = ReplaySession(
        bars={"AAA": frame},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        warm_bars=30,
        evaluate_at="open",
    )

    await session.run()

    built = session.engine.bars.frame("AAA")
    assert not built.empty
    assert (built["high"] > built["low"]).all(), "a flattened bar means ATR is zero"

    # The fixture's range is exactly 4.0 on every bar - high is close+2 and low
    # is close-2 - so the true range surviving the fold is checkable without
    # aligning two indexes, which is a different question from this one.
    #
    # The forming bar is excluded: the final day is a stub by construction,
    # because nothing has folded its range in yet.
    completed = session.engine.bars.frame("AAA", include_forming=False)
    spreads = (completed["high"] - completed["low"]).round(6).unique()
    assert list(spreads) == [4.0], f"a folded day lost its range: spreads seen {spreads}"


@pytest.mark.asyncio
async def test_the_strategy_is_evaluated_against_a_stub_of_today(tmp_path: Path):
    """The point of the cadence. At the moment evaluation runs, today's bar must
    be one print - not the finished range - or the decision is being made on
    information the live book did not have until the close."""
    frame = _bars()
    session = ReplaySession(
        bars={"AAA": frame},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        warm_bars=30,
        evaluate_at="open",
    )

    seen: list[float] = []

    async def inspect(event: MarketDataEvent) -> None:
        seen.append(event.price)

    session.bus.subscribe(MarketDataEvent, inspect)

    await session.run()

    assert seen, "no market data was published"
    opens = set(frame["open"].round(6))
    closes = set(frame["close"].round(6))
    assert {round(price, 6) for price in seen} <= opens, (
        "every evaluation must be triggered by the day's OPEN - a close means the "
        "decision saw the finished day, which is the look-ahead this cadence removes"
    )
    assert (
        not {round(price, 6) for price in seen} & closes
    ), "no evaluation may be triggered by a close in open cadence"


@pytest.mark.asyncio
async def test_close_cadence_is_unchanged_and_remains_the_default(tmp_path: Path):
    session = ReplaySession(
        bars={"AAA": _bars()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        warm_bars=30,
    )

    assert session.evaluate_at == "close"

    await session.run()

    built = session.engine.bars.frame("AAA")
    assert (built["high"] > built["low"]).all()
