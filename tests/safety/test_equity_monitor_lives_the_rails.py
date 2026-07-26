"""The daily-loss and drawdown rails must actually fire (spec M13).

Before M13 these two KillSwitch methods were implemented and unit-tested but
called from nowhere in `src/` - the rails the README leads with were dead code
in the running application. These tests assert the wiring, not the arithmetic
(tests/domain/risk_engine/test_kill_switch.py already covers the arithmetic).
"""

from __future__ import annotations

import json

import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position
from qat.domain.autonomy.equity_monitor import STATE_FILENAME, EquityMonitor
from qat.domain.risk_engine.kill_switch import KillSwitch


class _Broker:
    def __init__(self, equity: float) -> None:
        self.equity = equity

    async def account(self) -> AccountSummary:
        return AccountSummary(
            net_liquidation=self.equity, cash=self.equity, buying_power=self.equity
        )

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        raise NotImplementedError

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        raise NotImplementedError

    async def place_order(self, order: Order) -> Order:
        raise NotImplementedError

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> Order:
        raise NotImplementedError

    async def positions(self) -> list[Position]:
        return []


def _monitor(tmp_path, equity: float, **overrides):
    settings = Settings(_env_file=None, **overrides)  # type: ignore[arg-type]
    broker = _Broker(equity)
    switch = KillSwitch()
    monitor = EquityMonitor(broker, switch, settings=settings, data_dir=tmp_path)
    return broker, switch, monitor


@pytest.mark.asyncio
async def test_a_normal_day_does_not_trip_anything(tmp_path):
    broker, switch, monitor = _monitor(tmp_path, 100_000.0)
    await monitor.poll()
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_the_daily_loss_rail_trips(tmp_path):
    broker, switch, monitor = _monitor(tmp_path, 100_000.0, daily_loss_limit_pct=0.03)
    await monitor.poll()  # establishes day-start equity

    broker.equity = 95_000.0  # -5%, past the 3% limit
    await monitor.poll()

    assert switch.tripped is True
    assert "Daily loss" in (switch.reason or "")


@pytest.mark.asyncio
async def test_the_drawdown_rail_trips_from_the_running_peak(tmp_path):
    broker, switch, monitor = _monitor(
        tmp_path, 100_000.0, max_drawdown_limit_pct=0.20, daily_loss_limit_pct=0.99
    )
    await monitor.poll()
    broker.equity = 150_000.0  # a new high-water mark
    await monitor.poll()
    assert switch.tripped is False

    broker.equity = 110_000.0  # -26.7% from the 150k peak, though still up on the day
    await monitor.poll()

    assert switch.tripped is True
    assert "Drawdown" in (switch.reason or "")


@pytest.mark.asyncio
async def test_state_persists_across_a_restart(tmp_path):
    """Both rails are meaningless without this: a high-water mark that resets
    on launch can never register a drawdown."""
    broker, _, monitor = _monitor(tmp_path, 100_000.0)
    await monitor.poll()
    broker.equity = 150_000.0
    await monitor.poll()

    saved = json.loads((tmp_path / STATE_FILENAME).read_text(encoding="utf-8"))
    assert saved["high_water_mark"] == 150_000.0

    # A fresh monitor, as if the app had been restarted.
    broker2, switch2, monitor2 = _monitor(
        tmp_path, 110_000.0, max_drawdown_limit_pct=0.20, daily_loss_limit_pct=0.99
    )
    await monitor2.poll()

    assert switch2.tripped is True, "the peak from the previous run must still count"


@pytest.mark.asyncio
async def test_a_corrupt_state_file_does_not_prevent_startup(tmp_path):
    (tmp_path / STATE_FILENAME).write_text("{not json", encoding="utf-8")
    broker, switch, monitor = _monitor(tmp_path, 100_000.0)

    state = await monitor.poll()

    assert state.day_start_equity == 100_000.0
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_day_pnl_is_zero_before_the_first_poll(tmp_path):
    """An unknown P&L must not read as a loss - that would pause buys purely
    because the app had just started."""
    _, _, monitor = _monitor(tmp_path, 100_000.0)
    assert monitor.day_pnl_pct() == 0.0


@pytest.mark.asyncio
async def test_day_pnl_is_measured_against_the_day_start(tmp_path):
    broker, _, monitor = _monitor(tmp_path, 100_000.0)
    await monitor.poll()

    broker.equity = 97_000.0
    await monitor.poll()

    assert monitor.day_pnl_pct() == pytest.approx(-0.03)


@pytest.mark.asyncio
async def test_tripping_a_rail_publishes_an_event_so_the_ui_learns_about_it(tmp_path):
    """KillSwitch.trip() is a plain state change that publishes nothing, so a
    rail tripping here would otherwise be a real but invisible halt."""
    from qat.domain.bus import EventBus
    from qat.domain.events import KillSwitchEvent

    settings = Settings(_env_file=None, daily_loss_limit_pct=0.03)
    broker = _Broker(100_000.0)
    switch = KillSwitch()
    bus = EventBus()
    seen: list[KillSwitchEvent] = []

    async def _capture(event: KillSwitchEvent) -> None:
        seen.append(event)

    bus.subscribe(KillSwitchEvent, _capture)
    monitor = EquityMonitor(broker, switch, settings=settings, data_dir=tmp_path, bus=bus)

    await monitor.poll()
    assert seen == []

    broker.equity = 90_000.0
    await monitor.poll()

    assert len(seen) == 1
    assert "Daily loss" in seen[0].reason

    # A second poll while still tripped must not re-announce it every minute.
    await monitor.poll()
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_broker_failure_does_not_kill_the_monitor(tmp_path):
    """One bad poll must not silently end all future rail checks."""
    broker, switch, monitor = _monitor(tmp_path, 100_000.0)

    async def _fail() -> AccountSummary:
        raise ConnectionError("broker unreachable")

    broker.account = _fail  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        await monitor.poll()

    # The run loop swallows it; poll() itself is allowed to raise so callers
    # that want to know can. Recovery must then work.
    broker.account = _Broker(100_000.0).account  # type: ignore[method-assign]
    state = await monitor.poll()
    assert state.day_start_equity == 100_000.0
