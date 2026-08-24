"""End-to-end: a signed-off order becomes a measurable outcome (spec M16).

The evidence layer is only worth anything if it is actually fed. This walks a
real order from submission through sign-off to a closed trade in the ledger,
through the live engine graph rather than by calling the ledger directly.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _candidate(symbol: str = "AAA", side: str = "buy") -> OrderCandidate:
    dates = pd.date_range("2024-01-01", periods=30)
    return OrderCandidate(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=pd.Series([0.001] * 30, index=dates),
        strategy="swing",
    )


async def _build(tmp_path):
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None, max_aggregate_risk_at_stop_pct=1.0)
    engine = RiskEngine(bus, switch, settings=settings)
    broker = MockBroker(seed=1)
    oms = OMS(broker, engine, switch, max_order_pct_of_cash=1.0, bus=bus)
    ledger = TradeLedger(bus, tmp_path)
    await ledger.start()
    return oms, broker, ledger


@pytest.mark.asyncio
async def test_a_signed_off_buy_opens_a_tracked_lot(tmp_path):
    oms, _, ledger = await _build(tmp_path)

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, operator="tester")

    lots = ledger.open_lots("AAA")
    assert len(lots) == 1
    assert lots[0].strategy == "swing"
    assert lots[0].stop_price is not None, "the bracket stop must reach the ledger for R"


@pytest.mark.asyncio
async def test_a_round_trip_produces_a_closed_trade_with_an_r_multiple(tmp_path):
    oms, _, ledger = await _build(tmp_path)

    entry = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    filled_entry = await oms.sign_off(entry.order_id, operator="tester")

    exit_order = await oms.submit_exit_order("AAA", quantity=filled_entry.quantity, price=110.0)
    await oms.sign_off(exit_order.order_id, operator="tester")

    trades = ledger.closed_trades()
    assert len(trades) == 1
    assert trades[0].strategy == "swing"
    assert trades[0].r_multiple is not None
    assert ledger.open_lots("AAA") == []


@pytest.mark.asyncio
async def test_an_unsigned_order_produces_no_trade_record(tmp_path):
    """Only fills count. A pending order is an intention, and the evidence
    layer must never be fed by intentions."""
    oms, _, ledger = await _build(tmp_path)

    await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert ledger.open_lots() == []
    assert ledger.closed_trades() == []


@pytest.mark.asyncio
async def test_a_rejected_order_produces_no_trade_record(tmp_path):
    oms, _, ledger = await _build(tmp_path)
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.reject_order(order.order_id, operator="tester", reason="changed my mind")

    assert ledger.open_lots() == []
    assert ledger.closed_trades() == []
