"""A fill executing in the same clock tick as the scan was lost FOREVER.

`recent_fills` filters `filled_at > since`, strictly, and `_last_fill_scan`
advances to the stamp taken at the start of each sweep. So a broker execution
landing in the same tick as a sweep is excluded from that sweep - and then sits
permanently below the floor, because the floor has moved past it.

⚠️ THIS IS NOT A NARROW WINDOW ON WINDOWS. Measured on the development machine,
4 September: `datetime.now(UTC)` advances about every 2ms, and 199,967 of
200,000 consecutive calls returned an IDENTICAL timestamp. Ties are the common
case, not the rare one.

The consequence lands on the only exit path this system has. A protective stop
fills, nothing absorbs it, `tracked=100 broker=0`, and the kill switch halts on
a stop doing exactly its job - while the trade ledger never records the closed
trade, so the promotion gate accumulates nothing.

⚠️ Re-reading a fill is already free BY DESIGN - `_fill_query_floor`'s own
docstring says so: "its cumulative quantity is unchanged, the delta is zero, and
it is skipped". `_absorbed_fills` is what makes replaying safe. So the floor can
afford to reach back past a tie; it could never afford to skip one.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _returns(n: int = 30) -> pd.Series:
    return pd.Series([0.01, -0.01] * (n // 2), index=pd.date_range("2024-01-01", periods=n))


async def _opened(bus: EventBus) -> tuple[MockBroker, OMS]:
    settings = Settings(_env_file=None)
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    order = await oms.submit_order(
        OrderCandidate(
            symbol="AAA",
            side="buy",
            price=100.0,
            atr=2.0,
            win_rate=0.55,
            win_loss_ratio=1.5,
            candidate_returns=_returns(),
            strategy="swing",
        ),
        100_000.0,
        {},
        {},
    )
    await oms.sign_off(order.order_id, "operator")
    await oms.adopt_broker_positions()
    return broker, oms


def _restamp(broker: MockBroker, when: datetime) -> None:
    """`BrokerFill` is frozen, so the tie has to be built rather than assigned."""
    broker._broker_fills[-1] = replace(broker._broker_fills[-1], filled_at=when)


@pytest.mark.asyncio
async def test_a_stop_filling_in_the_scan_tick_is_still_absorbed() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. The fill is stamped EXACTLY at the
    scan's own watermark - the tie a 2ms clock produces constantly."""
    broker, oms = await _opened(EventBus())
    broker.fill_resting_stop("AAA", price=95.0)
    _restamp(broker, oms._last_fill_scan)

    mismatch = await oms.check_reconciliation()

    assert mismatch is False, "a stop that fired was read as a broker discrepancy"
    assert oms.kill_switch.tripped is False


@pytest.mark.asyncio
async def test_a_fill_from_BEFORE_the_baseline_is_still_refused() -> None:
    """⚠️ THE OTHER HALF OF THE TRADE-OFF, PINNED ON PURPOSE.

    Admitting ties means admitting the tick the baseline was taken in. Reaching
    back FURTHER than that must stay refused: adoption already counted anything
    older, inside the broker's own position list, and applying it again
    subtracts the same shares twice - the M50 trap, which is how this rail was
    made wrong in the opposite direction once before.
    """
    broker, oms = await _opened(EventBus())
    broker.fill_resting_stop("AAA", price=95.0)
    _restamp(broker, oms._last_fill_scan - timedelta(seconds=5))

    absorbed = await oms.absorb_broker_fills()

    assert absorbed == [], "a pre-baseline fill was applied on top of the adopted position"
    assert oms._filled_quantities["AAA"] == 100.0


@pytest.mark.asyncio
async def test_the_floor_still_excludes_genuinely_old_history() -> None:
    """⚠️ The reach-back must stay BOUNDED. Widening it without limit would
    replay months of executions on every sweep."""
    _, oms = await _opened(EventBus())

    assert oms._fill_query_floor() > datetime.now(UTC) - timedelta(days=1)
