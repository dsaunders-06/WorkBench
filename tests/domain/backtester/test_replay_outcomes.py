"""A stop that fires must become a ClosedTrade (W2 step 6).

Without this the harness opens positions, watches stops fire, correctly drops
the position count - and records no P&L, no expectancy and no R-multiple at
all. `TradeLedger` was never constructed by `ReplaySession` and
`absorb_broker_fills` was never called, so `oms.py`'s only publisher of an
`OrderFilledEvent` for a protective execution never ran.

It matters because an ablation switch with no outcome can compare which rails
BOUND but never whether the rails HELPED, and "do the rails help" is the
question the harness exists to answer.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.strategies.swing import SwingStrategy


def _trend_then_collapse(days: int = 160) -> pd.DataFrame:
    """An uptrend with one pullback-and-reclaim, then a gap through the stop.

    The dip is COMPUTED, not tuned, and is taken from `test_replay_session`'s
    fixture: swing needs `prior_close <= prior_fast` then `last_close >
    last_fast`, and an EMA20 lags a +0.5/day trend by about (20-1)/2 * 0.5 =
    4.75 - so a shallower dip never reaches the average and the thesis cannot
    fire however long the series runs. A monotonic rise produces NO entry at
    all, which would make this test fail for a reason unrelated to what it
    measures.

    The collapse sits in the last three bars, well after the entry has filled.
    open == close here, so the collapse bar OPENS far below any plausible
    2.5x ATR stop - which exercises the gap rule the fill model commits to:
    a bar opening below the stop fills at the OPEN, not politely at the trigger.
    """
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i * 0.5 for i in range(days)]
    closes[days - 10] -= 10.0
    for offset, level in ((3, 140.0), (2, 139.0), (1, 138.0)):
        closes[days - offset] = level
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.5 for c in closes],
            "low": [c - 1.5 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * days,
        },
        index=index,
    )


def _settings(tmp_path: Path) -> Settings:
    # Its own data_dir, per the standing constraint.
    return Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )


@pytest.mark.asyncio
async def test_a_fired_stop_becomes_a_closed_trade(tmp_path: Path):
    session = ReplaySession(
        bars={"AAA": _trend_then_collapse()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        # The regime gate refuses entries until a regime is published, so a
        # replay needs a benchmark it actually has bars for. In a single-symbol
        # fixture that symbol IS the market proxy.
        benchmark="AAA",
    )

    await session.run()

    path = tmp_path / "closed_trades.csv"
    assert path.exists(), "the harness recorded no closed trades at all"
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, "closed_trades.csv exists but holds no trades"
    assert any(row["symbol"] == "AAA" for row in rows)


@pytest.mark.asyncio
async def test_the_recorded_entry_price_is_what_the_simulator_charged(tmp_path: Path):
    """The fill model's central decision is that entries fill at the NEXT bar's
    open. `_announce_fill` publishes at `filled_price or reference_price`, and a
    SimulatedBroker order is QUEUED rather than filled at sign-off - so without
    a correction the ledger records the signal bar's CLOSE, expectancy is
    computed against a basis the simulator never charged, and the look-ahead the
    fill model exists to exclude comes back in through the record.

    Asserted against what the broker actually charged rather than against a
    hand-computed bar price: the invariant that matters is that the record and
    the simulator agree, and re-deriving the expected fill here would just be a
    second implementation of the fill model to keep in step.
    """
    session = ReplaySession(
        bars={"AAA": _trend_then_collapse()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        # The regime gate refuses entries until a regime is published, so a
        # replay needs a benchmark it actually has bars for. In a single-symbol
        # fixture that symbol IS the market proxy.
        benchmark="AAA",
    )

    await session.run()

    buys = [o for o in session.broker._orders.values() if o.side == "buy" and o.filled_price]
    assert buys, "no entry filled, so there is nothing to check"
    charged = float(buys[0].filled_price)
    reference = float(buys[0].reference_price)
    assert charged != pytest.approx(reference), (
        "fixture is not exercising the defect - the next open must differ from "
        "the signal bar's close for this test to mean anything"
    )

    closed = session.ledger.closed_trades()
    assert closed, "no closed trade to check the basis of"
    assert closed[0].entry_price == pytest.approx(charged, rel=1e-6)


@pytest.mark.asyncio
async def test_the_ledger_is_wired_to_the_session(tmp_path: Path):
    """The ledger must be the session's own, on the session's bus. A ledger
    built elsewhere would record nothing and look identical from outside."""
    session = ReplaySession(
        bars={"AAA": _trend_then_collapse()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        # The regime gate refuses entries until a regime is published, so a
        # replay needs a benchmark it actually has bars for. In a single-symbol
        # fixture that symbol IS the market proxy.
        benchmark="AAA",
    )

    assert session.ledger is not None
    assert session.ledger.bus is session.bus
