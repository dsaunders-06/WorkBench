"""Transiently-blocked orders get another look (M31b/3).

The executor evaluated each order exactly once, when it became pending. That
treats a reason which expires in minutes - "session phase 'Opening Volatility'
is not eligible" - identically to one that never will, and the symbol stays
suppressed meanwhile because the bridge skips anything already pending.

It cost three manual reject cycles on 30 July, and one position on the 31st:
PANW, 10 shares, blocked at 15:39 in the Midday Lull and never revisited.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position
from qat.domain.autonomy.executor import AutonomousExecutor
from qat.domain.autonomy.gate import AutonomyGate
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_NY = ZoneInfo("America/New_York")
OPENING_VOLATILITY = datetime(2026, 7, 23, 9, 35, tzinfo=_NY)
MORNING_TREND = datetime(2026, 7, 23, 10, 30, tzinfo=_NY)


class _Broker:
    def __init__(self) -> None:
        self.placed: list[Order] = []

    async def account(self) -> AccountSummary:
        return AccountSummary(net_liquidation=100_000.0, cash=100_000.0, buying_power=100_000.0)

    async def positions(self) -> list[Position]:
        return []

    async def place_order(self, order: Order) -> Order:
        self.placed.append(order)
        order.status = "filled"
        order.filled_price = order.reference_price
        return order

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        return {"last": 100.0, "bid": 99.99, "ask": 100.01}


def _candidate() -> OrderCandidate:
    dates = pd.date_range("2024-01-01", periods=30)
    return OrderCandidate(
        symbol="PANW",
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=pd.Series([0.001] * 30, index=dates),
        strategy="swing",
        stop_price=95.0,
    )


@pytest.mark.asyncio
async def test_an_order_blocked_by_the_phase_is_signed_once_the_phase_turns(tmp_path):
    settings = Settings(
        _env_file=None,
        execution_mode="auto",
        autonomous_strategies="swing",
        max_single_name_concentration_pct=1.0,
    )
    bus = EventBus()
    switch = KillSwitch()
    broker = _Broker()
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    clock = {"now": OPENING_VOLATILITY}
    gate = AutonomyGate(settings, switch, clock=lambda: clock["now"])
    executor = AutonomousExecutor(
        bus, oms, gate, DecisionJournal(tmp_path), settings=settings, retry_interval_seconds=0.02
    )

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await executor._consider(order.order_id)

    assert not broker.placed, "the opening auction must not be traded unattended"
    assert oms.get_order(order.order_id).status == "pending_signoff"

    # The phase turns, and the retry sweep picks the order back up.
    clock["now"] = MORNING_TREND
    await executor.start()
    try:
        for _ in range(50):
            if broker.placed:
                break
            await asyncio.sleep(0.02)
    finally:
        await executor.stop()

    assert broker.placed, "a reason that expired must be re-examined"
    assert broker.placed[0].symbol == "PANW"


@pytest.mark.asyncio
async def test_the_retry_stops_cleanly(tmp_path):
    """The sweep is a background task; stop() must not leave it running."""
    settings = Settings(_env_file=None, execution_mode="auto", autonomous_strategies="swing")
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(_Broker(), RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    executor = AutonomousExecutor(
        bus,
        oms,
        AutonomyGate(settings, switch),
        DecisionJournal(tmp_path),
        settings=settings,
        retry_interval_seconds=0.01,
    )

    await executor.start()
    await executor.stop()

    assert executor._retry_task is None
