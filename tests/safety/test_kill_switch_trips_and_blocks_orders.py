"""Spec-mandated safety test 3/5: the kill-switch trips for each named
trigger type and blocks new orders (spec §H/§18.2, §M, §O)."""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent, KillSwitchEvent
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch, KillSwitchEngine


def _flat_returns(n: int = 30) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.Series([0.001] * n, index=dates)


def _candidate(symbol: str = "AAA") -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=_flat_returns(),
    )


def _build() -> tuple[OMS, KillSwitch, EventBus]:
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch, settings=Settings(_env_file=None))
    broker = MockBroker(seed=1)
    oms = OMS(broker, engine, switch, max_order_pct_of_cash=1.0)
    return oms, switch, bus


@pytest.mark.asyncio
async def test_daily_loss_trigger_trips_and_blocks():
    oms, switch, _ = _build()
    switch.check_daily_loss(day_start_equity=100_000.0, current_equity=95_000.0, limit_pct=0.03)

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert switch.tripped
    assert order.status == "rejected"


@pytest.mark.asyncio
async def test_drawdown_trigger_trips_and_blocks():
    oms, switch, _ = _build()
    switch.check_drawdown(high_water_mark=100_000.0, current_equity=75_000.0, limit_pct=0.20)

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert switch.tripped
    assert order.status == "rejected"


@pytest.mark.asyncio
async def test_a_stale_quote_does_not_halt_and_does_not_block_other_symbols():
    """Inverted deliberately in M28a, and kept here because it is a safety
    property either way - just the opposite one.

    Staleness was a named kill-switch trigger, and every trip it ever produced
    was a false positive: with a 60s poll against a 60s threshold, a trade
    arriving 40s old was already past the line before the next poll. The
    operator had to suppress the rail with a 69-hour threshold to keep sessions
    running, which left genuine partial outages undetected.

    A stale print on one thin ticker now stops trading THAT ticker and nothing
    else. Halting an entire account because Berkshire had not printed on IEX by
    09:30:15 was a rail doing more damage than the hazard it guarded against.
    """
    oms, switch, bus = _build()
    engine = KillSwitchEngine(bus, switch)
    await engine.start()

    await bus.publish(DataStaleEvent(symbol="BRK.B", seconds_since_update=63_017.0))
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert not switch.tripped, "a stale quote must never halt the account"
    assert order.status != "rejected", "an unrelated symbol must keep trading"
    await engine.stop()


@pytest.mark.asyncio
async def test_reconciliation_mismatch_trigger_trips_and_blocks():
    oms, switch, _ = _build()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, operator="alice")
    oms._filled_quantities["AAA"] = 999.0  # simulate app-state/broker drift

    await oms.check_reconciliation()
    new_order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert switch.tripped
    assert new_order.status == "rejected"


@pytest.mark.asyncio
async def test_manual_trigger_trips_and_blocks():
    oms, switch, bus = _build()
    engine = KillSwitchEngine(bus, switch)
    await engine.start()

    await bus.publish(KillSwitchEvent(reason="operator halt", triggered_by="alice"))
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert switch.tripped
    assert order.status == "rejected"
    await engine.stop()


@pytest.mark.asyncio
async def test_reset_requires_explicit_operator_action_and_unblocks():
    oms, switch, _ = _build()
    switch.trigger_manual("alice")
    blocked = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    assert blocked.status == "rejected"

    switch.reset("bob")
    allowed = await oms.submit_order(_candidate("BBB"), 100_000.0, {}, {})

    assert allowed.status == "pending_signoff"
