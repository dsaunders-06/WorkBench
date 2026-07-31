"""Churn control: minimum hold, loss escape, time stop, turnover (M31).

Ten concurrent positions turned over weekly costs $6,240 a year at $12 a round
trip - 6.2% of a $100k account before a single losing trade. At ten trading
days it is 3.1%.

`enforce_min_holding_period` and `min_holding_trading_days` had existed as
settings since M27 and were read by nothing at all.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, OrderFilledEvent, SignalEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_NOW = datetime.now(UTC)


class _Broker(MockBroker):
    def __init__(self, held: float = 100.0) -> None:
        super().__init__(seed=1)
        self.held = held
        self.exits: list[tuple[str, float]] = []

    async def positions(self) -> list[Position]:
        if self.held <= 0:
            return []
        return [Position(symbol="AAA", quantity=self.held, avg_price=100.0)]


def _bridge(broker: _Broker, **overrides) -> SignalToOrderBridge:
    # Its own data dir: the bridge persists entry dates (M31b), and the
    # session-scoped isolate_data_dir fixture is shared by every test, so
    # without this one test's open positions would be another's.
    base = {"_env_file": None, "data_dir": tempfile.mkdtemp()}
    base.update(overrides)
    settings = Settings(**base)  # type: ignore[arg-type]
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch, settings=settings)
    oms = OMS(broker, engine, switch, bus=bus)
    bridge = SignalToOrderBridge(bus, oms, settings=settings)
    bridge.bars.add_tick("AAA", _NOW - timedelta(days=1), 100.0, 1.0)
    bridge.bars.add_tick("AAA", _NOW, 100.0, 1.0)
    return bridge


async def _opened(bridge: SignalToOrderBridge, days_ago: int, stop: float | None = 95.0) -> None:
    await bridge._on_fill(
        OrderFilledEvent(
            order_id="o1",
            symbol="AAA",
            side="buy",
            quantity=100.0,
            price=100.0,
            strategy="swing",
            stop_price=stop,
            ts=_NOW - timedelta(days=days_ago),
        )
    )


def _exit_signal() -> SignalEvent:
    return SignalEvent(
        symbol="AAA",
        side="sell",
        conviction=1.0,
        strategy="swing",
        meta={"exit_reason": "trend_broken"},
        ts=_NOW,
    )


@pytest.mark.asyncio
async def test_a_signal_exit_inside_the_minimum_hold_is_held_back():
    broker = _Broker()
    bridge = _bridge(broker, min_holding_trading_days=10)
    await _opened(bridge, days_ago=2)

    await bridge._on_signal(_exit_signal())

    assert not broker.exits and bridge._entries["AAA"] is not None
    assert "AAA" in bridge._hold_blocked


@pytest.mark.asyncio
async def test_the_hold_stops_applying_once_the_thesis_is_far_enough_wrong():
    """The escape that makes a minimum hold defensible. Sitting through a
    broken thesis to save $12 of commission is the wrong trade."""
    broker = _Broker()
    bridge = _bridge(broker, min_holding_trading_days=10, min_holding_loss_escape_r=0.5)
    await _opened(bridge, days_ago=2, stop=95.0)  # 1R = $5

    # Down $3 = 0.6R, past the 0.5R escape.
    assert bridge._blocked_by_minimum_hold("AAA", price=97.0) is False
    # Down $1 = 0.2R, not far enough.
    assert bridge._blocked_by_minimum_hold("AAA", price=99.0) is True


@pytest.mark.asyncio
async def test_a_signal_exit_after_the_minimum_hold_goes_through():
    broker = _Broker()
    bridge = _bridge(broker, min_holding_trading_days=10)
    await _opened(bridge, days_ago=30)

    assert bridge._blocked_by_minimum_hold("AAA", price=100.0) is False


@pytest.mark.asyncio
async def test_a_position_with_no_known_entry_is_never_trapped():
    """An adopted position has no entry this app recorded, and refusing to let
    a strategy exit it would be worse than churning."""
    broker = _Broker()
    bridge = _bridge(broker, min_holding_trading_days=10)

    assert bridge._blocked_by_minimum_hold("AAA", price=100.0) is False


@pytest.mark.asyncio
async def test_the_time_stop_forces_an_exit_on_an_unresolved_thesis():
    broker = _Broker()
    bridge = _bridge(broker, time_stop_trading_days=30, enforce_min_holding_period=False)
    await _opened(bridge, days_ago=60)

    await bridge._on_market_data(MarketDataEvent(symbol="AAA", price=100.0, volume=1.0, ts=_NOW))

    assert "AAA" in bridge._time_stopped


@pytest.mark.asyncio
async def test_the_time_stop_does_not_fire_early():
    broker = _Broker()
    bridge = _bridge(broker, time_stop_trading_days=30)
    await _opened(bridge, days_ago=5)

    await bridge._on_market_data(MarketDataEvent(symbol="AAA", price=100.0, volume=1.0, ts=_NOW))

    assert "AAA" not in bridge._time_stopped


@pytest.mark.asyncio
async def test_the_turnover_budget_counts_a_rolling_seven_days():
    broker = _Broker(held=0.0)
    bridge = _bridge(broker, max_entries_per_week=3)

    for day in (1, 2, 3):
        bridge._entry_times.append(_NOW - timedelta(days=day))
    assert bridge._entries_this_week(_NOW) == 3

    # An entry from a fortnight ago has aged out of the window.
    bridge._entry_times.append(_NOW - timedelta(days=14))
    assert bridge._entries_this_week(_NOW) == 3


@pytest.mark.asyncio
async def test_the_turnover_budget_blocks_a_further_entry():
    broker = _Broker(held=0.0)
    bridge = _bridge(broker, max_entries_per_week=2)
    bridge._entry_times = [_NOW - timedelta(days=1), _NOW - timedelta(days=2)]

    await bridge._submit_entry(
        SignalEvent(symbol="AAA", side="buy", conviction=1.0, strategy="swing", meta={}, ts=_NOW),
        bars=pd.DataFrame(),
        price=100.0,
        positions=[],
    )

    assert not broker._orders, "the budget must stop the order before it is built"


# --- Entry dates survive a restart (M31b/4) --------------------------------


@pytest.mark.asyncio
async def test_entry_dates_survive_a_restart():
    """Rebuilt only from live fills, the record was empty after every restart -
    and both churn rails treat an unknown entry as "never applies", so a
    restart silently disarmed them on everything already held."""
    data_dir = tempfile.mkdtemp()
    broker = _Broker()
    first = _bridge(broker, data_dir=data_dir, min_holding_trading_days=10)
    await _opened(first, days_ago=2)

    # A new process, same data directory.
    second = _bridge(_Broker(), data_dir=data_dir, min_holding_trading_days=10)

    assert "AAA" in second._entries
    assert second._blocked_by_minimum_hold("AAA", price=100.0) is True


@pytest.mark.asyncio
async def test_a_closed_position_is_forgotten_across_a_restart():
    data_dir = tempfile.mkdtemp()
    broker = _Broker()
    first = _bridge(broker, data_dir=data_dir)
    await _opened(first, days_ago=2)
    await first._on_fill(
        OrderFilledEvent(
            order_id="o2",
            symbol="AAA",
            side="sell",
            quantity=100.0,
            price=101.0,
            strategy="swing",
            stop_price=None,
            ts=_NOW,
        )
    )

    second = _bridge(_Broker(), data_dir=data_dir)

    assert "AAA" not in second._entries


def test_an_unreadable_entries_file_is_not_fatal():
    """A first run, or a corrupted file, must read as "no known entries" - the
    pre-M31b behaviour - not as a startup failure."""
    data_dir = tempfile.mkdtemp()
    (Path(data_dir) / "open_position_entries.json").write_text("{not json", encoding="utf-8")

    bridge = _bridge(_Broker(), data_dir=data_dir)

    assert bridge._entries == {}
