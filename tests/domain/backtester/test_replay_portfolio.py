"""Several symbols, one book, and the governor live (W2 step 3)."""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.strategies.swing import SwingStrategy


def _bars_with_pullback_at(dip_index: int, days: int = 200) -> pd.DataFrame:
    """The dip depth is computed, not tuned - an EMA20 lags a +0.5/day trend by
    about (20-1)/2 * 0.5 = 4.75, so 10 clears it. See the step-2 fixture for
    the derivation and for the shallower version that never fired."""
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i * 0.5 for i in range(days)]
    closes[dip_index] -= 10.0
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


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )


@pytest.mark.asyncio
async def test_several_symbols_share_one_book(tmp_path):
    """Each symbol pulls back on a different day, so entries arrive spread out
    rather than all at once - which is what a portfolio actually looks like."""
    bars = {
        "AAA": _bars_with_pullback_at(120),
        "BBB": _bars_with_pullback_at(140),
        "CCC": _bars_with_pullback_at(160),
    }
    session = ReplaySession(bars=bars, strategies=[SwingStrategy()], settings=_settings(tmp_path))

    await session.run()

    held = {p.symbol for p in await session.broker.positions()}
    orders = {o.symbol for o in session.broker._orders.values()}
    assert orders, "the production path produced no order across three symbols"
    assert held <= {"AAA", "BBB", "CCC"}


@pytest.mark.asyncio
async def test_the_position_limit_refuses_an_entry_and_says_so(tmp_path):
    """The first rail observation the harness can make, and the point of step 3.

    With the limit at one, a second symbol's valid setup must be refused BY THE
    GOVERNOR, and the refusal must be visible in the journal rather than
    inferred from silence. Until this works, no ablation means anything - the
    difference between a rail on and a rail off cannot be read from a run that
    cannot show the rail acting.
    """
    bars = {
        "AAA": _bars_with_pullback_at(120),
        "BBB": _bars_with_pullback_at(124),  # while AAA is still held
    }
    settings = _settings(tmp_path).model_copy(update={"max_concurrent_positions": 1})
    session = ReplaySession(bars=bars, strategies=[SwingStrategy()], settings=settings)

    await session.run()

    # ENTRIES, not every order. This counted all orders until 14 August and
    # passed only because exits were broken: `_announce_fill` published no `ts`,
    # so every entry was dated from the wall clock and the time stop could never
    # fire. With exits working, AAA legitimately has two orders - the entry and
    # its time-stop exit - and the question here has only ever been which
    # symbols were ENTERED.
    entered = sorted(o.symbol for o in session.broker._orders.values() if o.side == "buy")
    assert entered == ["AAA"], f"only the first setup should be entered, got {entered}"

    # risk_decisions.csv, not decision_journal.csv. The journal records the
    # SIGN-OFF path - what was transmitted and why it was allowed. Which rail
    # bound, and against what inputs, is a different question and has its own
    # ledger. A test looking in the journal would find silence and call it a
    # refusal, which is the failure this whole harness exists to avoid.
    decisions = (tmp_path / "risk_decisions.csv").read_text(encoding="utf-8")
    assert (
        "already at the 1-position limit" in decisions
    ), "the governor's refusal must be recorded by name, not inferred from an absence"
