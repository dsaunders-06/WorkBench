"""A replay can start from the book as it stood (W2 step 5, task 1).

G1 replays a window of the live record, and 2,511 of that record's 2,886
refusals are `already at the 10-position limit (10 held or pending)`. A replay
starting flat would fill up over weeks on different symbols and reproduce
almost none of them: the dominant rail in the record is a consequence of the
OPENING STATE, not of the window's own decisions.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.simulated_broker import OpeningPosition
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.strategies.swing import SwingStrategy

DAYS = 120
INDEX = pd.date_range("2026-01-05", periods=DAYS, freq="B", tz="UTC")


def _bars() -> pd.DataFrame:
    closes = [100.0 + i * 0.5 for i in range(DAYS)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.5 for c in closes],
            "low": [c - 1.5 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * DAYS,
        },
        index=INDEX,
    )


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )


def _session(tmp_path, opening) -> ReplaySession:
    return ReplaySession(
        bars={"SPY": _bars(), "AAA": _bars()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        opening_positions=opening,
        warm_bars=40,
    )


@pytest.mark.asyncio
async def test_the_replay_can_start_from_a_book_that_is_already_full(tmp_path):
    opening = {
        f"H{i}": OpeningPosition(quantity=10.0, avg_price=100.0, stop_price=90.0) for i in range(10)
    }

    session = _session(tmp_path, opening)

    held = {p.symbol for p in await session.broker.positions()}
    assert len(held) == 10, "the book must be full before the first replayed day"


@pytest.mark.asyncio
async def test_adopted_positions_carry_their_protection(tmp_path):
    """A position restored without its stop counts its FULL value against the
    aggregate cap, so an opening book without stops would overstate risk and
    refuse trades the live record permitted."""
    opening = {"H0": OpeningPosition(quantity=10.0, avg_price=100.0, stop_price=90.0)}

    session = _session(tmp_path, opening)

    assert await session.broker.resting_stops() == {"H0": 90.0}


@pytest.mark.asyncio
async def test_a_position_without_a_stop_is_held_but_unprotected(tmp_path):
    """The live record has carried unprotected positions, so the seam must be
    able to represent one rather than inventing protection that was not there."""
    opening = {"H0": OpeningPosition(quantity=10.0, avg_price=100.0, stop_price=None)}

    session = _session(tmp_path, opening)

    assert [p.symbol for p in await session.broker.positions()] == ["H0"]
    assert await session.broker.resting_stops() == {}


@pytest.mark.asyncio
async def test_no_opening_book_still_starts_flat(tmp_path):
    session = _session(tmp_path, None)
    assert await session.broker.positions() == []
