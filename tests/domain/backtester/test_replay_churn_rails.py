"""The churn rails must be able to fire in a replay (W2).

`OMS._announce_fill` published `OrderFilledEvent` without a `ts`, so it took
`Event`'s default of `datetime.now(UTC)`. The absorb path two hundred lines
below passes `ts=fill.filled_at` explicitly - *"When it FILLED, not when we
noticed (M50)"* - and the sign-off path never did.

`SignalToOrderBridge._on_fill` stamps `entry.opened_at` from that event, so
every position a replay opened was recorded as opened TODAY while the simulated
clock was months earlier. `_trading_days_between(opened_at, now)` then returns
zero forever, and **the time stop, the minimum holding period and the weekly
churn cap could never fire in any replay ever run.**

Found on the first ASX run: seven positions opened in September 2025 and held
across two hundred and fifty sessions with no exit of any kind, and no closed
trade at all. The seventh wall-clock dependency in the trading path, and the
same lesson as the other six - every wall-clock read is a place a replay
silently produces nothing.

This asserts the OUTCOME rather than the field. A test that checked
`event.ts` would pass on a fix that stamped the right value into a rail nothing
consults.
"""

from __future__ import annotations

import csv
from datetime import UTC
from pathlib import Path

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.strategies.swing import SwingStrategy


def _dip_then_drift(days: int = 200) -> pd.DataFrame:
    """One pullback-and-reclaim, then a long flat drift.

    The drift is what makes this a TIME-STOP test: the position neither reaches
    its 2R target nor falls to its ATR stop, so the only exit left is the one
    that fires on elapsed time. A series that resolved either way would pass
    without the rail working at all.

    **THE WINDOW SITS ENTIRELY IN THE PAST, and that is load-bearing.** A first
    version of this fixture started in January 2026 and ran two hundred business
    days - past the real date it was written on. A wall-clock `opened_at` was
    therefore in the MIDDLE of the replayed window, so once the simulated clock
    crossed it the position began to age and the time stop fired. Both tests
    passed against the unfixed code. A replay whose window includes today cannot
    detect a wall-clock stamp at all.
    """
    index = pd.date_range("2024-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i * 0.5 for i in range(80)]
    closes[70] -= 10.0  # the dip that fires swing's entry
    last = closes[-1]
    closes += [last + (0.02 * (i % 3 - 1)) for i in range(days - 80)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.6 for c in closes],
            "low": [c - 0.6 for c in closes],
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


@pytest.mark.asyncio
async def test_an_entry_is_dated_by_the_simulated_clock_not_the_wall_clock(tmp_path: Path):
    """The bridge's entry record is what every churn rail measures from."""
    session = ReplaySession(
        bars={"AAA": _dip_then_drift()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        warm_bars=60,
    )

    await session.run()

    entries = session.bridge._entries
    assert entries, "no entry was recorded, so the churn rails have nothing to measure"
    opened = next(iter(entries.values())).opened_at
    last_bar = session.broker.session_dates[-1].to_pydatetime().replace(tzinfo=UTC)
    assert opened <= last_bar, (
        f"entry dated {opened.date()} against a window ending {last_bar.date()} - it was "
        "stamped from the WALL CLOCK, so every churn rail measures zero days held forever"
    )
    assert opened.year == 2024, "the entry belongs to the replayed window, not to today"


@pytest.mark.asyncio
async def test_the_time_stop_fires_and_produces_a_closed_trade(tmp_path: Path):
    """The rail this defect disabled, asserted end to end.

    A thesis that neither resolves nor fails must still be closed out. Without
    it a replay holds every position to the end of the window, which is exactly
    what the first ASX run did across two hundred and fifty sessions.
    """
    session = ReplaySession(
        bars={"AAA": _dip_then_drift()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        warm_bars=60,
    )

    await session.run()

    path = tmp_path / "closed_trades.csv"
    assert path.exists(), "no closed trade at all - the time stop never fired"
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert any(
        row["exit_reason"] == "time_stop" for row in rows
    ), f"expected a time_stop exit, got {[r['exit_reason'] for r in rows]}"
