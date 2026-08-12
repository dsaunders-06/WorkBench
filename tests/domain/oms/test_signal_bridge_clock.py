"""Two rails read a clock, and a replay must be able to supply it (W2 step 3).

The minimum hold and the weekly churn cap compare against `now`. Against the
WALL clock in a replay, a simulated opened_at gives an enormous held_days and a
seven-day window that never contains the simulated entries - so both rails stop
binding, silently, in the harness built to measure whether rails help.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

SIMULATED = datetime(2016, 3, 15, 15, 0, tzinfo=UTC)


def _bridge(tmp_path, clock=None) -> SignalToOrderBridge:
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(MockBroker(seed=1), RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    return SignalToOrderBridge(bus, oms, settings=settings, clock=clock)


def test_the_default_clock_is_the_wall_clock(tmp_path):
    """Live behaviour must be unchanged: no caller passes a clock today."""
    bridge = _bridge(tmp_path)
    before = datetime.now(UTC)

    now = bridge._now()

    assert before <= now <= datetime.now(UTC)


def test_an_injected_clock_is_what_the_rails_read(tmp_path):
    bridge = _bridge(tmp_path, clock=lambda: SIMULATED)
    assert bridge._now() == SIMULATED


def test_the_weekly_churn_window_is_measured_on_the_injected_clock(tmp_path):
    """The rail counts entries in the last seven days. On the wall clock, a
    2016 entry is nine years old and the window is always empty."""
    bridge = _bridge(tmp_path, clock=lambda: SIMULATED)
    bridge._entry_times = [SIMULATED - timedelta(days=1), SIMULATED - timedelta(days=3)]

    assert bridge._entries_this_week(bridge._now()) == 2


def test_entries_outside_the_injected_window_still_fall_out(tmp_path):
    bridge = _bridge(tmp_path, clock=lambda: SIMULATED)
    bridge._entry_times = [SIMULATED - timedelta(days=8)]

    assert bridge._entries_this_week(bridge._now()) == 0
