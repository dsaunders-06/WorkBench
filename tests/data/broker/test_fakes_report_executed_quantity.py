"""A fake that does not report executed quantity hides the defect being fixed.

The manual-close branch was rejected three times, each with 3,000+ tests passing,
because a fake did not model the real broker. If these two keep returning
`filled_quantity is None`, every OMS test exercises the absent path and none
exercises the real one.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.data.broker.adapter import Order
from qat.data.broker.mock_broker import MockBroker
from qat.data.broker.simulated_broker import SimulatedBroker
from qat.domain.backtester.costs import CostModel


def _order() -> Order:
    return Order(symbol="BHP.AX", side="buy", quantity=10.0, order_id="app-1")


@pytest.mark.asyncio
async def test_mock_broker_reports_what_it_filled():
    filled = await MockBroker().place_order(_order())

    assert filled.status == "filled"
    assert filled.filled_quantity == 10.0


@pytest.mark.asyncio
async def test_simulated_broker_reports_what_it_filled():
    # SimulatedBroker requires bars and cost_model
    # Need two bars: one at the current date and one at the next date
    # so the order can fill on advance()
    bars = {
        "BHP.AX": pd.DataFrame(
            {
                "open": [100.0, 100.0],
                "high": [101.0, 101.0],
                "low": [99.0, 99.0],
                "close": [100.5, 100.5],
            },
            index=pd.DatetimeIndex([pd.Timestamp("2026-09-02"), pd.Timestamp("2026-09-03")]),
        )
    }
    cost_model = CostModel(commission_bps=0, slippage_bps=0)
    broker = SimulatedBroker(bars=bars, cost_model=cost_model)

    filled = await broker.place_order(_order())

    assert filled.status == "transmitted"
    # We need to advance the broker to fill the order
    broker.advance()
    # Get the order from the broker's storage to check the fill
    filled_order = broker._orders[_order().order_id]
    assert filled_order.status == "filled"
    assert filled_order.filled_quantity == 10.0
