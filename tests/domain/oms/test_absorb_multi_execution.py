"""One broker exit is one closed trade, however many executions it took.

LOV.AX filled 3,217 shares in 183 executions on 26 August 2026. Two things must
both hold: every share is absorbed, and the ledger gains ONE row rather than
183. The promotion gate counts closed trades toward 20 and 30, so an exit that
books itself 183 times clears the gate on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _lov_executions() -> list[BrokerFill]:
    """The real shape: many executions, one order, rising cumulative.

    Deliberately includes a LATER execution SMALLER than an earlier one - that
    is the exact condition the old code discarded, and a fixture of uniformly
    rising execution sizes would pass against the defect.
    """
    sizes = [10.0, 25.0, 4.0, 12.0, 51.0, 8.0, 374.0, 3.0, 2730.0]
    start = datetime(2026, 8, 26, 0, 6, 31, tzinfo=UTC)
    running = 0.0
    fills = []
    for i, size in enumerate(sizes):
        running += size
        fills.append(
            BrokerFill(
                order_id="1216552509",
                symbol="LOV.AX",
                side="sell",
                quantity=running,  # CUMULATIVE, per the BrokerFill contract
                price=28.45,
                filled_at=start + timedelta(seconds=i),
            )
        )
    return fills


@pytest.fixture
async def oms_with_lov_position(tmp_path):
    """An OMS adopted into a 3,217-share LOV.AX position this app never
    transmitted, with a broker stub whose `recent_fills` answers with the raw
    183-execution shape (compressed here to 9 executions - `_lov_executions`).

    Modelled on `tests/domain/oms/test_resting_order_reconciliation.py`'s
    `oms_factory` (a real, test-isolated `data_dir` passed through to `OMS`
    rather than left to construct one itself) and on the adopted-position
    tests in `tests/safety/test_broker_side_fills.py` (a position placed
    directly on the broker stub and picked up by `adopt_broker_positions`,
    which is what makes the fills read as foreign rather than the app's own).

    `data_dir=str(tmp_path)` is not optional: `conftest` sets `QAT_DATA_DIR`
    session-wide and `PositionAnomalyStore` persists there, so a test that
    lets a declared anomaly land in that shared directory would quarantine
    LOV.AX for every test that runs after it in the same session.
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    broker._positions["LOV.AX"] = Position(symbol="LOV.AX", quantity=3217.0, avg_price=28.45)
    oms = OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    await oms.adopt_broker_positions()

    executions = _lov_executions()
    broker._broker_fills = executions
    # The floor has to sit before the EARLIEST execution. Elsewhere in this
    # suite the pattern is `_last_fill_scan -= timedelta(seconds=1)` against
    # fills stamped `datetime.now(UTC)`; these fills carry fixed historical
    # timestamps instead, so the watermark is set directly against them
    # rather than against whatever the wall clock happens to read when the
    # test runs.
    oms._last_fill_scan = executions[0].filled_at - timedelta(seconds=1)
    return oms


@pytest.mark.asyncio
async def test_every_share_of_a_multi_execution_exit_is_absorbed(oms_with_lov_position):
    """3,217 filled, 3,217 absorbed.

    ⚠️ This assertion passes with the CUMULATIVE-quantity fix alone and does not
    need the per-order collapse - the delta arithmetic already sums correctly
    across many entries. It is here as a regression guard, not as the thing that
    demonstrates this task. The row-count test below is what the collapse fixes.

    The live 374 shortfall was the SHARES half of the defect
    (`from_ib_fill` supplying per-execution rather than cumulative), which is
    fixed one task earlier.
    """
    oms = oms_with_lov_position
    absorbed = await oms.absorb_broker_fills()

    total = sum(f.quantity for f in absorbed)
    assert total == pytest.approx(
        3217.0
    ), f"absorbed {total} of 3,217 - the shortfall is silently discarded fills"


@pytest.mark.asyncio
async def test_one_exit_produces_one_absorbed_fill(oms_with_lov_position):
    """Not 183. The gate counts rows."""
    oms = oms_with_lov_position
    absorbed = await oms.absorb_broker_fills()

    assert len(absorbed) == 1, (
        f"{len(absorbed)} fills for one order - the ledger will carry one row "
        "each and the promotion gate counts them"
    )
